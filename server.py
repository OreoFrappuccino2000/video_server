from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import subprocess
import uuid
import os
import zipfile
import shutil
import time

app = FastAPI()

# ============================
# SAFETY LIMITS (ADJUSTABLE)
# ============================
MAX_DURATION_SECONDS = 3600        # 1 hour max video
FRAME_INTERVAL = 10                # 1 frame every 10 seconds
MAX_FRAMES = 20                   # hard cap on frames
JOB_TTL_SECONDS = 60 * 60          # auto-clean jobs older than 1 hour

BASE_DIR = os.getcwd()


# ============================
# HELPER: CLEANUP OLD JOBS
# ============================
def cleanup_old_jobs():
    now = time.time()
    for item in os.listdir(BASE_DIR):
        if item.endswith(".zip"):
            zip_path = os.path.join(BASE_DIR, item)
            if os.path.isfile(zip_path):
                if now - os.path.getmtime(zip_path) > JOB_TTL_SECONDS:
                    os.remove(zip_path)

        job_dir = os.path.join(BASE_DIR, item)
        if os.path.isdir(job_dir):
            if now - os.path.getmtime(job_dir) > JOB_TTL_SECONDS:
                shutil.rmtree(job_dir, ignore_errors=True)


# ============================
# MAIN PROCESSING ENDPOINT
# ============================
@app.post("/run")
def run_ffmpeg(video_url: str):

    cleanup_old_jobs()  # clean before starting new work

    job_id = str(uuid.uuid4())
    os.makedirs(job_id, exist_ok=True)

    # -------- 1. PROBE DURATION --------
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        video_url
    ]

    try:
        duration = float(subprocess.check_output(probe_cmd).decode().strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to probe video")

    if duration > MAX_DURATION_SECONDS:
        shutil.rmtree(job_id, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"Video too long. Max allowed is {MAX_DURATION_SECONDS} seconds."
        )

    # -------- 2. FRAME EXTRACTION --------
    expected_frames = int(duration // FRAME_INTERVAL)

    if expected_frames > MAX_FRAMES:
        shutil.rmtree(job_id, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"Too many frames ({expected_frames}). Max allowed is {MAX_FRAMES}."
        )

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", video_url,
        "-vf", f"fps=1/{FRAME_INTERVAL}",
        f"{job_id}/frame_%04d.jpg"
    ]

    try:
        subprocess.run(ffmpeg_cmd, check=True)
    except subprocess.CalledProcessError:
        shutil.rmtree(job_id, ignore_errors=True)
        raise HTTPException(status_code=500, detail="FFmpeg frame extraction failed")

    # -------- 3. ZIP OUTPUT --------
    zip_path = f"{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for f in os.listdir(job_id):
            zipf.write(os.path.join(job_id, f), f)

    return {
        "duration": round(duration, 3),
        "zip_file": zip_path,
        "download_url": f"/download/{zip_path}"
    }


# ============================
# PUBLIC ZIP DOWNLOAD ENDPOINT
# ============================
@app.get("/download/{zip_name}")
def download_zip(zip_name: str):

    zip_path = os.path.join(BASE_DIR, zip_name)

    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP not found")

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_name
    )
