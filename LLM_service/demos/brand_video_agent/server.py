import uuid
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.generate import generate_brand_props
from agent.render import OUT_DIR, render_video

app = FastAPI(title="Brand Video Agent")

# { job_id: { "status": "pending"|"done"|"error", "path": str|None, "error": str|None } }
jobs: dict[str, dict] = {}

OUT_DIR.mkdir(exist_ok=True)
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")


class GenerateRequest(BaseModel):
    brief: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "done", "error"]
    download_url: str | None = None
    error: str | None = None
    props: dict | None = None


def _run_job(job_id: str, brief: str) -> None:
    try:
        props = generate_brand_props(brief)
        props_dict = props.model_dump()
        jobs[job_id]["props"] = props_dict

        output_path = render_video(props_dict, job_id=job_id)
        jobs[job_id]["status"] = "done"
        jobs[job_id]["path"] = str(output_path)
    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(exc)


@app.post("/generate-video", response_model=JobStatus, status_code=202)
def generate_video(request: GenerateRequest, background_tasks: BackgroundTasks):
    if not request.brief.strip():
        raise HTTPException(status_code=400, detail="Brief cannot be empty.")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "path": None, "error": None, "props": None}
    background_tasks.add_task(_run_job, job_id, request.brief)

    return JobStatus(job_id=job_id, status="pending")


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    download_url = None
    if job["status"] == "done" and job["path"]:
        filename = Path(job["path"]).name
        download_url = f"/out/{filename}"

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        download_url=download_url,
        error=job.get("error"),
        props=job.get("props"),
    )


@app.get("/download/{job_id}")
def download_video(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job is '{job['status']}', not done yet.")

    path = Path(job["path"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="Video file no longer available.")

    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/health")
def health():
    return {"status": "ok"}
