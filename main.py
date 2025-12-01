from flask import Flask, request, jsonify
import os
import subprocess
import uuid

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "Flask video server with FFmpeg is running", 200


@app.route("/process", methods=["POST"])
def process_video():
    data = request.get_json(force=True)

    video_url = data.get("video_url")
    fps = int(data.get("fps", 1))

    if not video_url:
        return jsonify({"error": "video_url is required"}), 400

    task_id = str(uuid.uuid4())
    base_dir = os.path.join("/tmp", task_id)
    frames_dir = os.path.join(base_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    video_path = os.path.join(base_dir, "input.mp4")

    try:
        subprocess.run(
            ["yt-dlp", "-f", "mp4", "-o", video_path, video_url],
            check=True
        )

        subprocess.run(
            [
                "ffmpeg",
                "-i", video_path,
                "-vf", f"fps={fps}",
                os.path.join(frames_dir, "frame_%04d.jpg"),
            ],
            check=True
        )

        frames = sorted(os.listdir(frames_dir))

        events = []
        for i, f in enumerate(frames):
            events.append(
                {
                    "time_sec": i,
                    "frame": f,
                    "event": "placeholder_event",
                    "confidence": 0,
                }
            )

        return jsonify(
            {
                "task_id": task_id,
                "fps": fps,
                "total_frames": len(frames),
                "events": events,
            }
        ), 200

    except subprocess.CalledProcessError as e:
        return jsonify(
            {
                "task_id": task_id,
                "error": "processing failed",
                "details": str(e),
            }
        ), 500


if __name__ == "__main__":
    # This is ONLY for local testing. Render will use gunicorn.
    app.run(host="127.0.0.1", port=5000, debug=True)
