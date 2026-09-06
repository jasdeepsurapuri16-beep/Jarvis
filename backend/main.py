from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from urllib.parse import urlparse
from datetime import datetime, timezone
import uuid
import os
import threading
import yt_dlp

app = FastAPI(
    title="Universal Downloader API",
    version="1.2.0"
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

DOWNLOAD_DIR = "/tmp/universal_downloader"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


class DownloadRequest(BaseModel):
    url: HttpUrl
    platform: str
    permission_confirmed: bool


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


def process_download(job_id: str, url: str):

    try:
        jobs[job_id]["status"] = "processing"

        output_template = os.path.join(
            DOWNLOAD_DIR,
            f"{job_id}.%(ext)s"
        )

        options = {
            "outtmpl": output_template,
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            filename = ydl.prepare_filename(info)

        if not os.path.exists(filename):

            possible_files = [
                os.path.join(
                    DOWNLOAD_DIR,
                    f
                )
                for f in os.listdir(DOWNLOAD_DIR)
                if f.startswith(job_id + ".")
            ]

            if possible_files:
                filename = possible_files[0]

        if not os.path.exists(filename):
            raise Exception("Downloaded file could not be located.")

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["file"] = filename
        jobs[job_id]["title"] = info.get("title", "video")

    except Exception as e:

        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/")
def root():
    return {
        "service": "Universal Downloader API",
        "status": "online",
        "version": "1.2.0"
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
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    thread = threading.Thread(
        target=process_download,
        args=(job_id, str(request.url)),
        daemon=True
    )

    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "platform": detected_platform,
        "status": "queued",
        "message": "Download job started."
    }


@app.get("/api/status/{job_id}")
def get_status(job_id: str):

    job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    response = {
        "success": True,
        "job_id": job["job_id"],
        "platform": job["platform"],
        "status": job["status"],
        "created_at": job["created_at"]
    }

    if "title" in job:
        response["title"] = job["title"]

    if "error" in job:
        response["error"] = job["error"]

    if job["status"] == "completed":
        response["download_url"] = (
            f"/api/file/{job_id}"
        )

    return response


@app.get("/api/file/{job_id}")
def download_file(job_id: str):

    job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="File is not ready."
        )

    filename = job.get("file")

    if not filename or not os.path.exists(filename):
        raise HTTPException(
            status_code=404,
            detail="Downloaded file no longer exists."
        )

    return FileResponse(
        filename,
        filename=os.path.basename(filename),
        media_type="application/octet-stream"
    )
