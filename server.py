from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import subprocess
import uuid
import os
import math
import requests

app = FastAPI()

# Public files folder
FILES_ROOT = "/app/files"
os.makedirs(FILES_ROOT, exist_ok=True)

# Serve public frames to VLM
app.mount("/files", StaticFiles(directory=FILES_ROOT), name="files")

MAX_FRAMES = 20   # Hard VLM limit

@app.post("/run")
def run(video_url: str):

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(FILES_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    video_path = f"/tmp/{job_id}.mp4"

    # ---------------------------
    # 1️⃣ Download remote MP4
    # ---------------------------
    try:
        with requests.get(video_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to download video")

    # ---------------------------
    # 2️⃣ Probe duration
    # ---------------------------
    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            video_path
        ]).decode().strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to probe video")

    # ---------------------------
# 3️⃣ Smart Phase Sampling
# ---------------------------
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
    end_t   = duration * end_r

    interval = max((end_t - start_t) / frames_per_phase, 1)

    ffmpeg_cmd = [
        "ffmpeg", "-ss", str(start_t), "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-frames:v", str(frames_per_phase),
        f"{phase_dir}/scene_%03d.jpg"
    ]

    subprocess.run(ffmpeg_cmd, check=True)

    for f in sorted(os.listdir(phase_dir)):
        url = f"/files/{job_id}/{phase}/{f}"
        frame_urls.append(url)

frame_urls = frame_urls[:MAX_FRAMES]
