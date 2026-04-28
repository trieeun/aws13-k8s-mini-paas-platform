# k8s_client.py
import os
import subprocess
from datetime import datetime
from kubernetes import client, config

# kubeconfig 로드 (마스터 노드에서 실행 시)
config.load_kube_config()

LB_IP = "211.183.3.200"       # 팀원 A가 확인한 External-IP
TMPL_DIR = "/k8s/paas/templates"
OUT_DIR  = "/k8s/paas/out"


def render_template(app_name, image, port):
    """템플릿 변수 치환 → out/{app_name}/ 에 저장"""
    out_path = f"{OUT_DIR}/{app_name}"
    os.makedirs(out_path, exist_ok=True)

    for f in ["namespace", "deployment", "service", "ingress", "hpa"]:
        tmpl = open(f"{TMPL_DIR}/{f}.yml").read()
        result = tmpl \
            .replace("{{ app_name }}", app_name) \
            .replace("{{ image }}",    image) \
            .replace("{{ port }}",     str(port)) \
            .replace("{{ lb_ip }}",    LB_IP)

        open(f"{out_path}/{f}.yml", "w").write(result)

    return out_path


def kubectl_apply(yaml_path):
    subprocess.run(
        ["kubectl", "apply", "-f", yaml_path],
        check=True
    )


def deploy(app_name, image, port):
    """전체 배포 실행 + 배포 시간 측정"""
    started_at = datetime.now().isoformat()

    # 1. 템플릿 치환
    out_path = render_template(app_name, image, port)

    # 2. 순서대로 apply
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


def wait_for_pod(app_name, timeout=120):
    """Pod가 Running 상태가 될 때까지 대기"""
    subprocess.run([
        "kubectl", "wait",
        f"--namespace=ns-{app_name}",
        "--for=condition=ready", "pod",
        "--selector=app=" + app_name,
        f"--timeout={timeout}s"
    ], check=True)


def delete_app(app_name):
    """Namespace 삭제 → 하위 모든 리소스 자동 삭제"""
    subprocess.run([
        "kubectl", "delete", "namespace",
        f"ns-{app_name}"
    ], check=True)
