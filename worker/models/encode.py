import subprocess


def encode_for_telegram(input_path: str, output_path: str):
    """Telegram prefers H.264 MP4 with faststart for quick preview."""
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-movflags", "+faststart",
        output_path
    ], check=True, capture_output=True)