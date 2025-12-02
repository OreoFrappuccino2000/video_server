from fastapi import FastAPI, HTTPException, Query
import subprocess
import uuid
import os
import shutil
import requests
import glob

app = FastAPI()

MAX_TOTAL_FRAMES = 20
SOFT_PER_PHASE = 5


def run(cmd):
    subprocess.run(cmd, check=True)


@app.post("/run")
def run_smart(video_url: str = Query(...)):
    job_id = str(uuid.uuid4())
    work_dir = os.path.join("/tmp", job_id)
    os.makedirs(work_dir, exist_ok=True)

    local_video = os.path.join(work_dir, "input.mp4")

    # ---------------------------------------------------
    # 1) Download video safely (works for HuggingFace)
    # ---------------------------------------------------
    try:
        r = requests.get(video_url, stream=True, timeout=600)
        r.raise_for_status()
        with open(local_video, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Video download failed: {e}")

    # ---------------------------------------------------
    # 2) Get duration
    # ---------------------------------------------------
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            local_video
        ]
        duration = float(subprocess.check_output(probe_cmd).decode().strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to probe video")

    # ---------------------------------------------------
    # 3) Define soft phase ranges (time only)
    # ---------------------------------------------------
    phases = {
        "early": (0.00, 0.25),
        "mid":   (0.25, 0.55),
        "late":  (0.55, 0.85),
        "final": (0.85, 1.00),
    }

    phase_ranges = {
        k: (v[0] * duration, v[1] * duration)
        for k, v in phases.items()
    }

    phase_results = {}

    # ---------------------------------------------------
    # 4) Scene + Motion detection per phase
    # ---------------------------------------------------
    for phase, (start, end) in phase_ranges.items():
        phase_dir = os.path.join(work_dir, phase)
        os.makedirs(phase_dir, exist_ok=True)

        scene_pattern = os.path.join(phase_dir, "scene_%03d.jpg")
        motion_pattern = os.path.join(phase_dir, "motion_%03d.jpg")

        try:
            # Scene changes
            run([
                "ffmpeg", "-ss", str(start), "-to", str(end),
                "-i", local_video,
                "-vf", "select='gt(scene,0.35)'",
                "-vsync", "vfr",
                scene_pattern,
                "-y"
            ])

            # Motion intensity
            run([
                "ffmpeg", "-ss", str(start), "-to", str(end),
                "-i", local_video,
                "-vf", "tblend=all_mode=difference,select='gt(scene,0.12)'",
                "-vsync", "vfr",
                motion_pattern,
                "-y"
            ])
        except Exception:
            pass

        scene_frames = sorted(glob.glob(os.path.join(phase_dir, "scene_*.jpg")))
        motion_frames = sorted(glob.glob(os.path.join(phase_dir, "motion_*.jpg")))

        merged = scene_frames + motion_frames
        phase_results[phase] = merged[:SOFT_PER_PHASE]

    # ---------------------------------------------------
    # 5) Merge phases with hard cap = 20
    # ---------------------------------------------------
    selected = []
    seen = set()

    for phase in ["early", "mid", "late", "final"]:
        for f in phase_results.get(phase, []):
            if f not in seen:
                seen.add(f)
                selected.append(f)

    selected = selected[:MAX_TOTAL_FRAMES]

    # ---------------------------------------------------
    # 6) Fallback if insufficient activity
    # ---------------------------------------------------
    if len(selected) < 8:
        fallback_pattern = os.path.join(work_dir, "fallback_%03d.jpg")
        try:
            run([
                "ffmpeg", "-i", local_video,
                "-vf", "fps=1/120",
                fallback_pattern,
                "-y"
            ])
            fallback_frames = sorted(glob.glob(os.path.join(work_dir, "fallback_*.jpg")))
            for f in fallback_frames:
                if f not in seen and len(selected) < MAX_TOTAL_FRAMES:
                    selected.append(f)
        except Exception:
            pass

    # ---------------------------------------------------
    # 7) Safety check
    # ---------------------------------------------------
    if not selected:
        raise HTTPException(status_code=400, detail="No valid frames extracted")

    # ---------------------------------------------------
    # 8) Return for prepare_vlm
    # ---------------------------------------------------
    return {
        "job_id": job_id,
        "duration": duration,
        "total_frames": len(selected),
        "frame_paths": selected
    }
