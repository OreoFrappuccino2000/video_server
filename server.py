from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import subprocess
import uuid
import os
import math
import requests
from urllib.parse import unquote

app = FastAPI()

FILES_ROOT = "/app/files"
os.makedirs(FILES_ROOT, exist_ok=True)

app.mount("/files", StaticFiles(directory=FILES_ROOT), name="files")

MAX_FRAMES = 20


@app.post("/run")
def run(video_url: str):

    # ✅ Decode encoded URLs from Dify
    video_url = unquote(video_url)

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(FILES_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    video_path = f"/tmp/{job_id}.mp4"

    # ---------------------------
    # 1️⃣ Download MP4
    # ---------------------------
    try:
        with requests.get(video_url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        raise HTTPException(400, f"Failed to download video: {str(e)}")

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
        raise HTTPException(400, "Failed to probe video")

    # ---------------------------
    # 3️⃣ Smart phase sampling
    # ---------------------------
    phases = {
        "early": (0.05, 0.25),
        "mid":   (0.35, 0.60),
        "late":  (0.70, 0.90),
        "final": (0.90, 0.98)
    }

    frames_per_phase = math.ceil(MAX_FRAMES / len(phases))
    frame_urls = []

    for phase, (start_r, end_r) in phases.items():

        phase_dir = os.path.join(job_dir, phase)
        os.makedirs(phase_dir, exist_ok=True)

        start_t = duration * start_r
        end_t = duration * end_r
        interval = max((end_t - start_t) / frames_per_phase, 1)

        ffmpeg_cmd = [
            "ffmpeg", "-ss", str(start_t), "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-frames:v", str(frames_per_phase),
            f"{phase_dir}/scene_%03d.jpg"
        ]

        subprocess.run(ffmpeg_cmd, check=True)

        for f in sorted(os.listdir(phase_dir)):
            frame_urls.append(f"/files/{job_id}/{phase}/{f}")

    frame_urls = frame_urls[:MAX_FRAMES]

    return {
        "job_id": job_id,
        "duration": duration,
        "total_frames": len(frame_urls),
        "frame_urls": frame_urls
    }
