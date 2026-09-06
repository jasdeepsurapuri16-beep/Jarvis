from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from urllib.parse import urlparse
from datetime import datetime, timezone
import uuid

app = FastAPI(
    title="Universal Downloader API",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jasdeepsurapuri16-beep.github.io"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


SUPPORTED_PLATFORMS = {
    "youtube": {
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "m.youtube.com"
    },
    "facebook": {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "fb.watch"
    },
    "tiktok": {
        "tiktok.com",
        "www.tiktok.com",
        "vm.tiktok.com"
    }
}


class DownloadRequest(BaseModel):
    url: HttpUrl
    platform: str
    permission_confirmed: bool


jobs = {}


def detect_platform(url: str):
    host = urlparse(url).hostname

    if not host:
        return None

    host = host.lower()

    for platform, domains in SUPPORTED_PLATFORMS.items():

        if host in domains:
            return platform

        for domain in domains:
            if host.endswith("." + domain):
                return platform

    return None


@app.get("/")
def root():
    return {
        "service": "Universal Downloader API",
        "status": "online",
        "version": "1.1.0"
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/download")
def create_download(request: DownloadRequest):

    if not request.permission_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Permission confirmation is required."
        )

    detected_platform = detect_platform(str(request.url))

    if not detected_platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video URL."
        )

    if detected_platform != request.platform.lower():
        raise HTTPException(
            status_code=400,
            detail="Platform does not match the URL."
        )

    job_id = uuid.uuid4().hex

    jobs[job_id] = {
        "job_id": job_id,
        "platform": detected_platform,
        "url": str(request.url),
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": "Download job created."
    }

    return {
        "success": True,
        "job_id": job_id,
        "platform": detected_platform,
        "status": "queued",
        "message": "Download job created successfully."
    }


@app.get("/api/status/{job_id}")
def get_status(job_id: str):

    job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    return {
        "success": True,
        **job
    }
