import os
import subprocess
from datetime import datetime
from kubernetes import client, config

LB_IP = os.getenv("LB_IP", "211.183.3.200")  # MetalLB External-IP
TMPL_DIR = os.getenv("TMPL_DIR", "../k8s/paas/templates")
OUT_DIR = os.getenv("OUT_DIR", "../k8s/paas/out")


def _load_config():
    """kubeconfig 로드 - 마스터 노드에서만 동작"""
    try:
        config.load_incluster_config()  # Pod 내부에서 실행 시
    except Exception:
        config.load_kube_config()  # 로컬 kubeconfig 사용 시


def render_template(app_name, image, port):
    """템플릿 변수 치환 → out/{app_name}/ 에 저장"""
    out_path = f"{OUT_DIR}/{app_name}"
    os.makedirs(out_path, exist_ok=True)

    for f in ["namespace", "deployment", "service", "ingress", "hpa"]:
        tmpl = open(f"{TMPL_DIR}/{f}.yml").read()
        result = (
            tmpl
            .replace("{{ app_name }}", app_name)
            .replace("{{ image }}", image)
            .replace("{{ port }}", str(port))
            .replace("{{ lb_ip }}", LB_IP)
        )
        open(f"{out_path}/{f}.yml", "w").write(result)

    return out_path


def kubectl_apply(yaml_path):
    subprocess.run(["kubectl", "apply", "-f", yaml_path], check=True)


def copy_ghcr_secret(app_name):
    """default namespace의 ghcr-secret을 새 namespace로 복사"""
    try:
        subprocess.run(
            f'kubectl get secret ghcr-secret -o yaml '
            f'| sed "s/namespace: default/namespace: ns-{app_name}/" '
            f'| kubectl apply -f -',
            shell=True, check=True
        )
    except subprocess.CalledProcessError:
        pass  # ghcr-secret 없으면 무시 (public 이미지 사용 시)


def wait_for_pod(app_name, timeout=120):
    """Pod가 Running 상태가 될 때까지 대기"""
    subprocess.run([
        "kubectl", "wait",
        f"--namespace=ns-{app_name}",
        "--for=condition=ready", "pod",
        f"--selector=app={app_name}",
        f"--timeout={timeout}s"
    ], check=True)


def deploy(app_name, image, port):
    """전체 배포 실행 + 배포 시간 측정"""
    _load_config()
    started_at = datetime.now().isoformat()

    # 1. 템플릿 치환
    out_path = render_template(app_name, image, port)

    # 2. namespace 먼저 apply
    kubectl_apply(f"{out_path}/namespace.yml")

    # 3. ghcr-secret 복사 (namespace 생성 직후)
    copy_ghcr_secret(app_name)

    # 4. 나머지 리소스 apply
    for f in ["deployment", "service", "ingress", "hpa"]:
        kubectl_apply(f"{out_path}/{f}.yml")

    # 5. Pod Running 될 때까지 대기 + 시간 측정
    wait_for_pod(app_name)
    finished_at = datetime.now().isoformat()

    url = f"http://{app_name}.{LB_IP}.nip.io"
    return url, started_at, finished_at


def get_status(app_name):
    """Pod 상태 + HPA 현황 조회"""
    _load_config()
    v1 = client.CoreV1Api()
    apps = client.AppsV1Api()
    autoscaling = client.AutoscalingV2Api()
    namespace = f"ns-{app_name}"

    # Pod 상태
    pods = v1.list_namespaced_pod(namespace, label_selector=f"app={app_name}")
    pod_list = [
        {
            "name": pod.metadata.name,
            "status": pod.status.phase,
            "node": pod.spec.node_name,
        }
        for pod in pods.items
    ]

    # Deployment 현황
    dep = apps.read_namespaced_deployment(f"dep-{app_name}", namespace)
    ready_replicas = dep.status.ready_replicas or 0
    total_replicas = dep.status.replicas or 0

    # HPA 현황
    hpa = autoscaling.read_namespaced_horizontal_pod_autoscaler(
        f"hpa-{app_name}", namespace
    )
    cpu_util = 0
    if hpa.status.current_metrics:
        cpu_util = hpa.status.current_metrics[0].resource.current.average_utilization or 0

    hpa_info = {
        "current_replicas": hpa.status.current_replicas,
        "desired_replicas": hpa.status.desired_replicas,
        "max_replicas": hpa.spec.max_replicas,
        "cpu_utilization": cpu_util,
    }

    return {
        "pods": pod_list,
        "ready_replicas": ready_replicas,
        "total_replicas": total_replicas,
        "hpa": hpa_info,
        "url": f"http://{app_name}.{LB_IP}.nip.io",
    }


def delete_app(app_name):
    """Namespace 삭제 → 하위 모든 리소스 자동 삭제"""
    subprocess.run(
        ["kubectl", "delete", "namespace", f"ns-{app_name}"],
        check=True
    )
