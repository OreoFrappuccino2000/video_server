from fastapi import FastAPI
import subprocess
import uuid
import os
import zipfile

app = FastAPI()

@app.post("/run")
def run_ffmpeg(video_url: str):
    job_id = str(uuid.uuid4())
    os.makedirs(job_id, exist_ok=True)

    # 1. Get duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        video_url
    ]
    duration = subprocess.check_output(probe_cmd).decode().strip()

    # 2. Extract frames every 10s
    ffmpeg_cmd = [
        "ffmpeg", "-i", video_url,
        "-vf", "fps=1/10",
        f"{job_id}/frame_%04d.jpg"
    ]
    subprocess.run(ffmpeg_cmd, check=True)

    # 3. Zip output
    zip_path = f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for f in os.listdir(job_id):
            zipf.write(f"{job_id}/{f}", f)

    return {
        "duration": duration,
        "zip_file": zip_path
    }
