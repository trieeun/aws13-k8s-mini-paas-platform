from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
import os
import db
import k8s_client

app = FastAPI()

_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

@app.get("/")
def dashboard():
    return FileResponse(os.path.join(_static_dir, "index.html"))
db.init_db()


class DeployRequest(BaseModel):
    app_name:   str  # 예: "hello-kubernetes"
    github_url: str  # 예: "https://github.com/myaccount/hello-kubernetes"
    port:       int  # 예: 8080


@app.post("/deploy")
def deploy(req: DeployRequest):
    if db.get_deployment(req.app_name):
        raise HTTPException(status_code=400, detail=f"{req.app_name} 이미 배포됨")

    try:
        url, image, started_at, finished_at = k8s_client.deploy(
            req.app_name, req.github_url, req.port
        )
        db.save_deployment(
            app_name   = req.app_name,
            github_url = req.github_url,
            image      = image,
            port       = req.port,
            url        = url,
            status     = "Running",
            started_at = started_at,
            finished_at= finished_at
        )
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


@app.get("/status/{app_name}")
def status(app_name: str):
    if not db.get_deployment(app_name):
        raise HTTPException(status_code=404, detail="앱 없음")
    try:
        info = k8s_client.get_status(app_name)
        return {
            "app_name": app_name,
            "url":      info["url"],
            "status":   info["pods"],
            "replicas": f"{info['ready_replicas']}/{info['total_replicas']}",
            "hpa":      info["hpa"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/deployments")
def deployments():
    rows = db.get_all_deployments()
    result = []
    for row in rows:
        app_name, github_url, image, port, url, \
            status, started_at, finished_at = row
        elapsed = (
            (datetime.fromisoformat(finished_at) -
             datetime.fromisoformat(started_at)).seconds
            if started_at and finished_at else None
        )
        result.append({
            "app_name":   app_name,
            "github_url": github_url,
            "image":      image,
            "url":        url,
            "status":     status,
            "started_at": started_at,
            "elapsed":    f"{elapsed}초" if elapsed else "-"
        })
    return result


@app.delete("/deploy/{app_name}")
def delete(app_name: str):
    if not db.get_deployment(app_name):
        raise HTTPException(status_code=404, detail="앱 없음")
    try:
        k8s_client.delete_app(app_name)
        db.delete_deployment(app_name)
        return {"result": f"{app_name} 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))