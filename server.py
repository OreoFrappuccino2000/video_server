from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import subprocess
import uuid
import os
import math
import requests

app = FastAPI()

# ---------------------------
# Public files directory
# ---------------------------
FILES_ROOT = "/app/files"
os.makedirs(FILES_ROOT, exist_ok=True)

# Expose frames publicly for VLM access
app.mount("/files", StaticFiles(directory=FILES_ROOT), name="files")

# ---------------------------
# Configuration
# ---------------------------
MAX_FRAMES = 20
DOWNLOAD_TIMEOUT = 120  # seconds
CHUNK_SIZE = 1024 * 1024  # 1MB

# ---------------------------
# Health Check
# ---------------------------
@app.get("/")
def health():
    return {"status": "ok"}

# ---------------------------
# Main Smart Extractor Endpoint
# ---------------------------
@app.post("/run")
def run(video_url: str):

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(FILES_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    video_path = f"/tmp/{job_id}.mp4"

    # ===========================
    # 1️⃣ Download Remote Video
    # ===========================
    try:
        with requests.get(video_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download video: {e}")

    # ===========================
    # 2️⃣ Probe Video Duration
    # ===========================
    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            video_path
        ]).decode().strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to probe video: {e}")

    # ===========================
    # 3️⃣ Smart Phase Sampling
    # ===========================
    phases = {
        "early": (0.05, 0.25),
        "mid":   (0.35, 0.60),
        "late":  (0.70, 0.90),
        "final": (0.90, 0.98)
    }

    frame_urls = []
    frames_per_phase = math.ceil(MAX_FRAMES / len(phases))

    for phase, (start_r, end_r) in phases.items():
        phase_dir = os.path.join(job_dir, phase)
        os.makedirs(phase_dir, exist_ok=True)

        start_t = duration * start_r
        end_t = duration * end_r
        interval = max((end_t - start_t) / frames_per_phase, 1)

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_t),
            "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-frames:v", str(frames_per_phase),
            f"{phase_dir}/scene_%03d.jpg"
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"FFmpeg failed: {e}")

        for f in sorted(os.listdir(phase_dir)):
            url = f"/files/{job_id}/{phase}/{f}"
            frame_urls.append(url)

    frame_urls = frame_urls[:MAX_FRAMES]

    # ===========================
    # ✅ Final Structured Output
    # ===========================
    return {
        "job_id": job_id,
        "duration": duration,
        "total_frames": len(frame_urls),
        "frame_urls": frame_urls
    }
