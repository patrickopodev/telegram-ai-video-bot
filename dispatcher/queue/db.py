import os
from datetime import datetime
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _client = create_client(url, key)
    return _client


def create_job(user_id: int, prompt: str, raw_prompt: str, model: str = "ltx-video") -> dict:
    job = {
        "user_id": user_id,
        "prompt": prompt,
        "raw_prompt": raw_prompt,
        "model": model,
        "status": "pending",
    }
    res = _get_client().table("jobs").insert(job).execute()
    return res.data[0]


def get_job_status(job_id: str) -> dict | None:
    res = _get_client().table("jobs").select("*").eq("id", job_id).single().execute()
    return res.data


def poll_completed_jobs() -> list[dict]:
    res = _get_client().table("jobs").select("*").eq("status", "complete").execute()
    return res.data


def mark_delivered(job_id: str, telegram_file_id: str = None):
    update = {"status": "delivered", "delivered_at": datetime.utcnow().isoformat()}
    if telegram_file_id:
        update["telegram_file_id"] = telegram_file_id
    _get_client().table("jobs").update(update).eq("id", job_id).execute()


def claim_job(worker_id: str, provider: str) -> dict | None:
    res = _get_client().rpc("claim_next_job", {"p_worker_id": worker_id, "p_provider": provider}).execute()
    return res.data[0] if res.data else None


def mark_complete(job_id: str, result_url: str):
    _get_client().rpc("mark_job_complete", {"p_job_id": job_id, "p_result_url": result_url}).execute()


def mark_failed(job_id: str, error: str):
    _get_client().rpc("mark_job_failed", {"p_job_id": job_id, "p_error": error}).execute()