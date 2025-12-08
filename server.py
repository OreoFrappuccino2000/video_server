import hashlib
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import subprocess
import uuid
import os
import math
import requests
import zipfile

app = FastAPI()

FILES_ROOT = "/app/files"
CACHE_ROOT = "/tmp/cache"   # ✅ cache directory
os.makedirs(FILES_ROOT, exist_ok=True)
os.makedirs(CACHE_ROOT, exist_ok=True)

app.mount("/files", StaticFiles(directory=FILES_ROOT), name="files")

MAX_FRAMES = 20


@app.post("/run")
def run(video_url: str):
    video_url = video_url.strip()

    # --------------------------------------------------
    # ✅ 0️⃣ HASH KEY FOR CACHING
    # --------------------------------------------------
    video_hash = hashlib.md5(video_url.encode()).hexdigest()

    cached_video_path = os.path.join(CACHE_ROOT, f"{video_hash}.mp4")
    cached_zip_path   = os.path.join(FILES_ROOT, f"{video_hash}.zip")

    # ✅ If final ZIP already exists → return immediately
    if os.path.exists(cached_zip_path):
        BASE_URL = "https://videoserver-production.up.railway.app"
        zip_url = f"{BASE_URL}/files/{video_hash}.zip"

        return {
            "job_id": video_hash,
            "duration": 0,
            "total_frames": MAX_FRAMES,
            "frame_urls": [],
            "zip_file": zip_url,
            "cached": True
        }

    # --------------------------------------------------
    # ✅ 1️⃣ VIDEO DOWNLOAD (CACHED)
    # --------------------------------------------------
    if not os.path.exists(cached_video_path):
        try:
            with requests.get(video_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(cached_video_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        except Exception as e:
            raise HTTPException(400, f"Failed to download video: {e}")

    video_path = cached_video_path
    job_id = video_hash
    job_dir = os.path.join(FILES_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    # --------------------------------------------------
    # ✅ 2️⃣ PROBE DURATION (ONCE PER VIDEO)
    # --------------------------------------------------
    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            video_path
        ]).decode().strip())
    except:
        raise HTTPException(400, "Failed to probe video")

    # --------------------------------------------------
    # ✅ 3️⃣ SMART PHASE SAMPLING (ONLY IF NOT DONE)
    # --------------------------------------------------
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

        # ✅ Skip extraction if frames already exist
        if not os.listdir(phase_dir):
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

            subprocess.run(ffmpeg_cmd, check=True)

        for f in sorted(os.listdir(phase_dir)):
            url = f"/files/{job_id}/{phase}/{f}"
            frame_urls.append(url)

    frame_urls = frame_urls[:MAX_FRAMES]

    # --------------------------------------------------
    # ✅ 4️⃣ ZIP ALL FRAMES (CACHED)
    # --------------------------------------------------
    with zipfile.ZipFile(cached_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(job_dir):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, job_dir)
                zipf.write(full_path, arcname)

    BASE_URL = "https://videoserver-production.up.railway.app"
    zip_url = f"{BASE_URL}/files/{job_id}.zip"

    # --------------------------------------------------
    # ✅ 5️⃣ FINAL RESPONSE
    # --------------------------------------------------
    return {
        "job_id": job_id,
        "duration": duration,
        "total_frames": len(frame_urls),
        "frame_urls": frame_urls,
        "zip_file": zip_url,
        "cached": False
    }
