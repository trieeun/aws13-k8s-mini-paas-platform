from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import db
import k8s_client

app = FastAPI()
db.init_db()


class DeployRequest(BaseModel):
    app_name: str  # 예: "myapp"
    image: str  # 예: "ghcr.io/owner/myapp:latest"
    port: int  # 예: 8080


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.post("/deploy")
def deploy(req: DeployRequest):
    # 중복 배포 방지
    existing = db.get_deployment(req.app_name)
    if existing:
        raise HTTPException(
            status_code=400, detail=f"{req.app_name} 이미 배포됨"
        )

    try:
        url, started_at, finished_at = k8s_client.deploy(
            req.app_name, req.image, req.port
        )

        # 배포 이력 저장
        db.save_deployment(
            app_name=req.app_name,
            image=req.image,
            port=req.port,
            url=url,
            status="Running",
            started_at=started_at,
            finished_at=finished_at,
        )

        # 배포 시간 계산
        elapsed = (
            datetime.fromisoformat(finished_at)
            - datetime.fromisoformat(started_at)
        ).seconds

        return {
            "app_name": req.app_name,
            "url": url,
            "elapsed": f"{elapsed}초",
            "status": "Running",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{app_name}")
def status(app_name: str):
    existing = db.get_deployment(app_name)
    if not existing:
        raise HTTPException(status_code=404, detail="앱 없음")

    try:
        k8s_info = k8s_client.get_status(app_name)
        return {
            "app_name": app_name,
            "url": k8s_info["url"],
            "status": k8s_info["pods"],
            "replicas": f"{k8s_info['ready_replicas']}/{k8s_info['total_replicas']}",
            "hpa": k8s_info["hpa"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/deployments")
def deployments():
    rows = db.get_all_deployments()
    result = []
    for row in rows:
        app_name, image, port, url, status, started_at, finished_at = row

        # 배포 시간 계산
        if started_at and finished_at:
            elapsed = (
                datetime.fromisoformat(finished_at)
                - datetime.fromisoformat(started_at)
            ).seconds
        else:
            elapsed = None

        result.append(
            {
                "app_name": app_name,
                "image": image,
                "url": url,
                "status": status,
                "started_at": started_at,
                "elapsed": f"{elapsed}초" if elapsed else "-",
            }
        )
    return result


@app.delete("/deploy/{app_name}")
def delete(app_name: str):
    existing = db.get_deployment(app_name)
    if not existing:
        raise HTTPException(status_code=404, detail="앱 없음")

    try:
        k8s_client.delete_app(app_name)
        db.delete_deployment(app_name)
        return {"result": f"{app_name} 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
