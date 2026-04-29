import os
import subprocess
from datetime import datetime
from urllib.parse import urlparse
from kubernetes import client, config

config.load_kube_config()

LB_IP    = "211.183.3.200"
TMPL_DIR = "/k8s/paas/templates"
OUT_DIR  = "/k8s/paas/out"


def build_and_push(app_name, github_url):
    """git clone → docker build → ghcr.io push"""
    parts = urlparse(github_url).path.strip("/").split("/")
    owner = parts[0]

    work_dir = f"/tmp/build-{app_name}"
    image    = f"ghcr.io/{owner}/{app_name}:latest"

    # 이전 빌드 잔재 제거 (재배포 시 git clone 실패 방지)
    subprocess.run(["rm", "-rf", work_dir], check=True)

    try:
        # 1. clone
        subprocess.run(["git", "clone", github_url, work_dir], check=True)

        if not os.path.exists(f"{work_dir}/Dockerfile"):
            raise ValueError(f"Dockerfile not found in {github_url}")

        # 2. build
        subprocess.run(["docker", "build", "-t", image, work_dir], check=True)

        # 3. push (마스터 노드에서 docker login ghcr.io 미리 필요)
        subprocess.run(["docker", "push", image], check=True)
    finally:
        # 성공/실패 무관하게 항상 정리
        subprocess.run(["rm", "-rf", work_dir])
        subprocess.run(["docker", "rmi", "-f", image])

    return image


def render_template(app_name, image, port):
    out_path = f"{OUT_DIR}/{app_name}"
    os.makedirs(out_path, exist_ok=True)

    for f in ["namespace", "deployment", "service", "ingress", "hpa"]:
        tmpl = open(f"{TMPL_DIR}/{f}.yml").read()
        result = (tmpl
            .replace("{{ app_name }}", app_name)
            .replace("{{ image }}",    image)
            .replace("{{ port }}",     str(port))
            .replace("{{ lb_ip }}",    LB_IP))
        open(f"{out_path}/{f}.yml", "w").write(result)

    return out_path


def kubectl_apply(yaml_path):
    subprocess.run(["kubectl", "apply", "-f", yaml_path], check=True)


# def copy_ghcr_secret(app_name):
#     subprocess.run(
#         f"kubectl get secret ghcr-secret -o yaml "
#         f"| sed 's/namespace: default/namespace: ns-{app_name}/' "
#         f"| kubectl apply -f -",
#         shell=True, check=True
#     )


def wait_for_pod(app_name, timeout=120):
    subprocess.run([
        "kubectl", "wait",
        f"--namespace=ns-{app_name}",
        "--for=condition=ready", "pod",
        f"--selector=app={app_name}",
        f"--timeout={timeout}s"
    ], check=True)


def deploy(app_name, github_url, port):
    started_at = datetime.now().isoformat()

    # 1. 빌드 (github_url에서 owner 자동 추출)
    image = build_and_push(app_name, github_url)

    # 2. 템플릿 치환
    out_path = render_template(app_name, image, port)

    # 3. namespace 먼저
    kubectl_apply(f"{out_path}/namespace.yml")

    # 4. 나머지 리소스 (ghcr.io Public이므로 imagePullSecrets 불필요)
    for f in ["deployment", "service", "ingress", "hpa"]:
        kubectl_apply(f"{out_path}/{f}.yml")

    # 6. Pod Ready 대기
    wait_for_pod(app_name)

    finished_at = datetime.now().isoformat()
    url = f"http://{app_name}.{LB_IP}.nip.io"

    return url, image, started_at, finished_at


def delete_app(app_name):
    import time
    ns_name = f"ns-{app_name}"
    v1 = client.CoreV1Api()

    try:
        v1.delete_namespace(ns_name)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise

    # Terminating 상태에서 finalizer가 걸리면 강제 제거
    for _ in range(15):
        time.sleep(2)
        try:
            ns = v1.read_namespace(ns_name)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return
            raise

        if ns.spec.finalizers:
            ns.spec.finalizers = []
            try:
                v1.replace_namespace_finalize(ns_name, ns)
            except client.exceptions.ApiException:
                pass


def get_status(app_name):
    v1         = client.CoreV1Api()
    apps       = client.AppsV1Api()
    autoscaling = client.AutoscalingV2Api()
    namespace  = f"ns-{app_name}"

    pods = v1.list_namespaced_pod(namespace, label_selector=f"app={app_name}")
    pod_list = [
        {
            "name":   pod.metadata.name,
            "status": pod.status.phase,
            "node":   pod.spec.node_name
        }
        for pod in pods.items
    ]

    dep = apps.read_namespaced_deployment(f"dep-{app_name}", namespace)
    ready_replicas = dep.status.ready_replicas or 0
    total_replicas = dep.status.replicas or 0

    hpa = autoscaling.read_namespaced_horizontal_pod_autoscaler(
        f"hpa-{app_name}", namespace
    )
    hpa_info = {
        "current_replicas": hpa.status.current_replicas,
        "desired_replicas": hpa.status.desired_replicas,
        "max_replicas":     hpa.spec.max_replicas,
        "cpu_utilization":  (
            hpa.status.current_metrics[0].resource.current.average_utilization
            if hpa.status.current_metrics else 0
        )
    }

    return {
        "pods":           pod_list,
        "ready_replicas": ready_replicas,
        "total_replicas": total_replicas,
        "hpa":            hpa_info,
        "url":            f"http://{app_name}.{LB_IP}.nip.io"
    }