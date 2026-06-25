"""
TEMPORARY dev backend — a stand-in for the (not-yet-built) Java backend.

Target topology:   frontend  ──►  Java backend  ──►  Python LLM service
This file plays the middle box so you can exercise the **real** LLM service from
the frontend before the Java backend exists. It is deliberately **independent of
the LLM_service package** (no imports from it) — it only speaks HTTP to the LLM
service, exactly as the Java backend will. Throw it away once Java is ready.

What it does: receives the frontend's content requests and forwards each to the
LLM service, reshaping the response into the small envelope the frontend's
Next.js proxies (`/api/text`, `/api/brand`, `/api/video`) expect.

Run it (LLM service must already be up on :8080):

    /opt/anaconda3/envs/TeamProject/bin/python3 dev_backend.py
    # env: LLM_SERVICE_URL (default http://localhost:8080)
    #      DEV_BACKEND_HOST (default 0.0.0.0), DEV_BACKEND_PORT (default 8090)

Then point the frontend at it (frontend_service/.env.local):
    BRAND_AGENT_URL=http://localhost:8090
    BRAND_VIDEO_AGENT_URL=http://localhost:8090
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://localhost:8080").rstrip("/")
# HTML-card generation on real Azure can take ~60–70s, so keep a generous read budget.
_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

app = FastAPI(
    title="Starlight DEV backend (Java stand-in)",
    version="0.1",
    summary="Temporary gateway: frontend ──► (this) ──► Python LLM service.",
)

# This is a throwaway dev box; allow the browser to hit it directly too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# `history` mirrors what the real Java backend will do: look the conversation up by
# its id in the DB, assemble the prior {role, content} turns, and forward them so the
# (stateless) LLM service can continue a multi-turn thread. Optional / pass-through here.
class GenerateTextRequest(BaseModel):
    prompt: str
    platform: Optional[str] = "linkedin"
    history: Optional[list] = None


class GenerateHtmlRequest(BaseModel):
    prompt: str
    history: Optional[list] = None


class GenerateVideoRequest(BaseModel):
    brief: str
    history: Optional[list] = None


async def _forward(method: str, path: str, *, json: Optional[dict] = None) -> JSONResponse:
    """Proxy one call to the LLM service, passing the upstream status straight through
    and turning a connection failure into a clear 502 (so the frontend can show it)."""
    url = f"{LLM_SERVICE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": f"LLM service unreachable at {url}: {exc}"},
        )
    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text}
    return JSONResponse(status_code=resp.status_code, content=body)


@app.get("/health", summary="Liveness + LLM-service reachability")
async def health() -> dict:
    reachable, detail = True, "ok"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{LLM_SERVICE_URL}/health")
            reachable = r.status_code == 200
            detail = r.text
    except httpx.HTTPError as exc:
        reachable, detail = False, str(exc)
    return {"status": "ok", "llm_service": LLM_SERVICE_URL,
            "llm_reachable": reachable, "llm_detail": detail}


# ── Content generation — forwarded 1:1 to the LLM service ─────────────────────

@app.post("/generate-text", summary="Platform-native post copy")
async def generate_text(body: GenerateTextRequest) -> JSONResponse:
    return await _forward("POST", "/generate-text",
                          json={"prompt": body.prompt, "platform": body.platform,
                                "history": body.history})


@app.post("/generate", summary="Animated HTML brand card")
async def generate(body: GenerateHtmlRequest) -> JSONResponse:
    return await _forward("POST", "/generate",
                          json={"prompt": body.prompt, "history": body.history})


@app.post("/generate-video", summary="Start a BrandVideoProps spec job")
async def generate_video(body: GenerateVideoRequest) -> JSONResponse:
    return await _forward("POST", "/generate-video",
                          json={"brief": body.brief, "history": body.history})


@app.get("/jobs/{job_id}", summary="Poll a video-spec job")
async def video_job(job_id: str) -> JSONResponse:
    return await _forward("GET", f"/jobs/{job_id}")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("DEV_BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("DEV_BACKEND_PORT", "8090"))
    print(f"DEV backend (Java stand-in) on http://{host}:{port}  →  LLM service {LLM_SERVICE_URL}")
    uvicorn.run(app, host=host, port=port, log_level="info")
