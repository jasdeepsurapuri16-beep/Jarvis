from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from urllib.parse import urlparse
from datetime import datetime, timezone
import uuid
import os
import threading
import requests
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
# DOWNLOAD LOAD BALANCER
# ============================================================

download_counter = 0
download_counter_lock = threading.Lock()

PC_JOB_PERCENTAGE = 30


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
# FORWARD DOWNLOAD TO SECONDARY PC
# ============================================================

def forward_to_pc(url: str):

    worker_url = pc_worker.get("url")

    if not worker_url:
        raise Exception("No secondary PC worker is registered.")

    if not PC_WORKER_TOKEN:
        raise Exception("PC worker token is not configured.")

    response = requests.post(
        f"{worker_url}/api/worker/download",
        json={
            "url": url,
            "platform": "facebook",
            "permission_confirmed": True
        },
        headers={
            "X-Worker-Token": PC_WORKER_TOKEN
        },
        timeout=15
    )

    response.raise_for_status()

    return response.json()

    worker_url = pc_worker.get("url")

    if not worker_url:
        raise Exception("No secondary PC worker is registered.")

    response = requests.post(
        f"{worker_url}/api/download",
        json={
            "url": url,
            "platform": "facebook",
            "permission_confirmed": True
        },
        timeout=15
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# CHOOSE DOWNLOAD WORKER
# ============================================================

def choose_worker():

    global download_counter

    with download_counter_lock:
        download_counter += 1

        position = download_counter % 10

    if position in (4, 8, 0) and pc_worker.get("url"):
        return "pc"

    return "render"


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
# SECONDARY WORKER STATUS
# ============================================================

@app.get("/api/worker/status")
def worker_status():

    return {
        "success": True,
        "worker": "pc",
        "registered": bool(pc_worker["url"]),
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


       worker = choose_worker()

    if worker == "pc":
        try:
            pc_result = forward_to_pc(video_url)

            jobs[job_id]["worker"] = "pc"
            jobs[job_id]["pc_job_id"] = pc_result["job_id"]

            return {
                "success": True,
                "job_id": job_id,
                "platform": "facebook",
                "status": "queued",
                "worker": "pc",
                "message": "Download job sent to PC worker."
            }

        except Exception as e:
            worker = "render"
            jobs[job_id]["worker"] = "render"
            jobs[job_id]["worker_error"] = str(e)

    if worker == "render":

        jobs[job_id]["worker"] = "render"

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
            "worker": "render",
            "message": "Facebook download job started."
        }


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
    # PC worker job
    if job.get("worker") == "pc":

        pc_job_id = job.get("pc_job_id")
        worker_url = pc_worker.get("url")

        if not pc_job_id or not worker_url:
            return {
                "success": True,
                "job_id": job_id,
                "status": "failed",
                "error": "PC worker is unavailable."
            }

        try:
            pc_response = requests.get(
                f"{worker_url}/api/status/{pc_job_id}",
                timeout=10
            )

            pc_response.raise_for_status()
            pc_status = pc_response.json()

        except Exception:
            return {
                "success": True,
                "job_id": job_id,
                "status": "processing",
                "worker": "pc"
            }

        response = {
            "success": True,
            "job_id": job_id,
            "platform": "facebook",
            "status": pc_status.get("status"),
            "worker": "pc",
            "created_at": job["created_at"]
        }

        if "title" in pc_status:
            response["title"] = pc_status["title"]

        if "error" in pc_status:
            response["error"] = pc_status["error"]

        if pc_status.get("status") == "completed":
            response["download_url"] = f"/api/file/{job_id}"

        return response

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
            f"https://jarvis-iu3f.onrender.com/api/file/{job_id}"
        )

    return response

# ============================================================
# DOWNLOAD COMPLETED FILE
# ============================================================

@app.get("/api/file/{job_id}")
def download_file(job_id: str):

    job = jobs.get(job_id)

    # PC worker file
    if job and job.get("worker") == "pc":
        worker_url = pc_worker.get("url")
        pc_job_id = job.get("pc_job_id")

        if not worker_url or not pc_job_id:
            raise HTTPException(
                status_code=404,
                detail="PC worker file is unavailable."
            )

        return RedirectResponse(
            url=f"{worker_url}/api/file/{pc_job_id}"
        )

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
