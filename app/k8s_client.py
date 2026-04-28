from kubernetes import client, config

def get_k8s_client():
    config.load_kube_config()
    return client.CoreV1Api()