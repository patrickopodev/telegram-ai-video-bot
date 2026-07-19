import os
from supabase import create_client

_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
BUCKET = "videos"


def upload_result(job_id: str, file_path: str) -> str:
    dest = f"{job_id}.mp4"
    with open(file_path, "rb") as f:
        _client.storage.from_(BUCKET).upload(dest, f, {"content-type": "video/mp4"})
    signed = _client.storage.from_(BUCKET).create_signed_url(dest, 3600)
    return signed["signedURL"]


def cleanup_local(file_path: str):
    if os.path.exists(file_path):
        os.remove(file_path)