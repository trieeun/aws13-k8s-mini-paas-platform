# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import db
import k8s_client

app = FastAPI()
db.init_db()


class DeployRequest(BaseModel):
    app_name: str   # 예: "myapp"
    image:    str   # 예: "ghcr.io/owner/myapp:latest"
    port:     int   # 예: 8080


@app.post("/deploy")
def deploy(req: DeployRequest):
    # 중복 배포 방지
    existing = db.get_deployment(req.app_name)
    if existing:
        raise HTTPException(status_code=400, detail=f"{req.app_name} 이미 배포됨")

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
            finished_at=finished_at
        )

        # 배포 시간 계산
        elapsed = (
            datetime.fromisoformat(finished_at) -
            datetime.fromisoformat(started_at)
        ).seconds

        return {
            "app_name": req.app_name,
            "url":      url,
            "elapsed":  f"{elapsed}초",
            "status":   "Running"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/deploy/{app_name}")
def delete(app_name: str):
    existing = db.get_deployment(app_name)
    if not existing:
        raise HTTPException(status_code=404, detail="앱 없음")

    k8s_client.delete_app(app_name)
    return {"result": f"{app_name} 삭제 완료"}
