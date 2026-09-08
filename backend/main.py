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
    title="Facebook Video Downloader API",
    version="1.3.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jasdeepsurapuri16-beep.github.io"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ============================================================
# DOWNLOAD STORAGE
# ============================================================

DOWNLOAD_DIR = "/tmp/universal_downloader"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ============================================================
# JOB STORAGE
# ============================================================

jobs = {}

# ============================================================
# SECONDARY WORKER
# ============================================================

PC_WORKER_URL = os.getenv("PC_WORKER_URL", "").rstrip("/")
PC_WORKER_TOKEN = os.getenv("PC_WORKER_TOKEN", "")

pc_worker = {
    "url": PC_WORKER_URL,
    "last_seen": None
}


# ============================================================
# REQUEST MODEL
# ============================================================

class DownloadRequest(BaseModel):
    url: HttpUrl
    platform: str
    permission_confirmed: bool


# ============================================================
# FACEBOOK URL VALIDATION
# ============================================================

FACEBOOK_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.watch"
}


def is_facebook_url(url: str):
    host = urlparse(url).hostname

    if not host:
        return False

    host = host.lower()

    if host in FACEBOOK_DOMAINS:
        return True

    for domain in FACEBOOK_DOMAINS:
        if host.endswith("." + domain):
            return True

    return False


# ============================================================
# DOWNLOAD PROCESSOR
# ============================================================

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
                    filename_only
                )
                for filename_only in os.listdir(DOWNLOAD_DIR)
                if filename_only.startswith(job_id + ".")
            ]

            if possible_files:
                filename = possible_files[0]


        if not os.path.exists(filename):

            raise Exception(
                "Downloaded file could not be located."
            )


        jobs[job_id]["status"] = "completed"
        jobs[job_id]["file"] = filename
        jobs[job_id]["title"] = info.get(
            "title",
            "Facebook Video"
        )


    except Exception as e:

        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "service": "Facebook Video Downloader API",
        "status": "online",
        "version": "1.3.0"
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat()
    }


# ============================================================
# REGISTER SECONDARY WORKER
# ============================================================

class WorkerRegistration(BaseModel):
    url: HttpUrl
    token: str


@app.post("/api/worker/register")
def register_worker(request: WorkerRegistration):

    if not PC_WORKER_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Worker registration is not configured."
        )

    if request.token != PC_WORKER_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid worker token."
        )

    pc_worker["url"] = str(request.url).rstrip("/")
    pc_worker["last_seen"] = datetime.now(timezone.utc).isoformat()

    return {
        "success": True,
        "worker": "pc",
        "status": "registered",
        "url": pc_worker["url"],
        "last_seen": pc_worker["last_seen"]
    }


# ============================================================
# CREATE DOWNLOAD JOB
# ============================================================

@app.post("/api/download")
def create_download(request: DownloadRequest):

    if not request.permission_confirmed:

        raise HTTPException(
            status_code=400,
            detail="Permission confirmation is required."
        )


    if request.platform.lower() != "facebook":

        raise HTTPException(
            status_code=400,
            detail="Only Facebook videos are currently supported."
        )


    video_url = str(request.url)

    if not is_facebook_url(video_url):

        raise HTTPException(
            status_code=400,
            detail="Please provide a valid Facebook video URL."
        )


    job_id = uuid.uuid4().hex


    jobs[job_id] = {
        "job_id": job_id,
        "platform": "facebook",
        "url": video_url,
        "status": "queued",
        "created_at":
            datetime.now(timezone.utc).isoformat()
    }


    thread = threading.Thread(
        target=process_download,
        args=(job_id, video_url),
        daemon=True
    )

    thread.start()


    return {
        "success": True,
        "job_id": job_id,
        "platform": "facebook",
        "status": "queued",
        "message":
            "Facebook download job started."
    }


# ============================================================
# CHECK JOB STATUS
# ============================================================

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


# ============================================================
# DOWNLOAD COMPLETED FILE
# ============================================================

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


    if not filename:

        raise HTTPException(
            status_code=404,
            detail="Downloaded file was not found."
        )


    if not os.path.exists(filename):

        raise HTTPException(
            status_code=404,
            detail="Downloaded file no longer exists."
        )


    # Send the correct video MIME type and a real video filename.
    extension = os.path.splitext(filename)[1].lower()

    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
    }

    media_type = media_types.get(
        extension,
        "application/octet-stream"
    )

    download_name = f"Facebook_Video{extension}"

    return FileResponse(
        filename,
        filename=download_name,
        media_type=media_type
    )
