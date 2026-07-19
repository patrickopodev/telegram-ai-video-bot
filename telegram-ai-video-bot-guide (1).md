# Telegram AI Video Generation Bot — Free-Tier Production Guide

> **Status:** Part 1 of a multi-part guide (Architecture, Accounts, Folder Structure).
> Parts 2–13 (models, bot code, backend, workers, security, scaling) will be appended
> in follow-up messages and merged into this same file.

---

## A note before you build anything

The biggest risk in this project isn't the AI models — it's the assumption that
"free GPU" means "free hosting." It doesn't, and getting this wrong will cost you
weeks of debugging a bot that mysteriously goes offline every few hours.

**The core correction to the original plan:**

| Component | Can it run on Colab/Kaggle/etc.? | Why / why not |
|---|---|---|
| Telegram bot listener (webhook or polling) | ❌ No | These are session-based notebook environments. Sessions disconnect (Colab: hours, resets on idle), have weekly quotas (Kaggle: 30h GPU/week), and most providers' ToS prohibit running always-on background services. Your bot would randomly go offline. |
| Job dispatcher / queue / state | ❌ No | Same reason — needs to be always-on and stateful. |
| Video generation (the actual GPU work) | ✅ Yes | This is exactly what these platforms are for: bursty, session-length compute. |
| Model weights storage | ✅ Yes (Hugging Face Hub / Google Drive) | Static file hosting, free, reliable. |

**The fix:** split the system into two tiers.

1. **Always-on tier (free, tiny footprint):** the Telegram bot itself, the job
   queue, and the dispatcher. This runs on a free tier that's *designed* to stay
   up — Supabase Edge Functions, Fly.io free allowance, Render free web service, or
   even a $0 always-free VM (Oracle Cloud Free Tier). It does **no** GPU work. Its
   only job is: receive Telegram messages → write a job to the queue → poll for
   results → send the video back.
2. **Burst compute tier (free, ephemeral):** Colab/Kaggle/Lightning AI/Paperspace/
   SageMaker Studio Lab notebooks that you (or a scheduler) start, which pull the
   next job from the queue, run inference, upload the result, and mark the job
   done. These come and go — the system is designed to tolerate that.

This is the actual "100% free" architecture that works in production. Everything
below is built around this split.

---

## Part 1 — Architecture

### 1.1 System overview

```
┌─────────────┐      ┌──────────────────────────┐      ┌───────────────────────┐
│   Telegram   │◄────►│   Always-On Dispatcher    │◄────►│   Job Queue (DB)       │
│   (user)     │      │   (FastAPI, free host)    │      │   Supabase Postgres    │
└─────────────┘      └──────────────────────────┘      │   or SQLite+litestream │
                                                          └───────────┬───────────┘
                                                                      │ poll for jobs
                                                          ┌───────────▼───────────┐
                                                          │   GPU Worker (notebook) │
                                                          │  Colab / Kaggle / etc.  │
                                                          │  - pulls job            │
                                                          │  - loads model          │
                                                          │  - runs inference       │
                                                          │  - uploads result       │
                                                          │  - marks job complete    │
                                                          └───────────┬───────────┘
                                                                      │
                                                          ┌───────────▼───────────┐
                                                          │  File storage           │
                                                          │  Supabase Storage /      │
                                                          │  Google Drive            │
                                                          └───────────────────────┘
```

### 1.2 Request flow

1. User sends `/generate a cat surfing at sunset` to the bot.
2. Dispatcher (always-on) validates the prompt, checks rate limits, writes a row
   to the `jobs` table with status `pending`, replies "Queued — position 3."
3. A GPU worker notebook (whichever provider is currently running — you'll start
   these manually at first, then semi-automate with a rotation script in Part 4)
   polls the `jobs` table every N seconds for `pending` jobs.
4. Worker claims the job (`pending` → `processing`), downloads/loads the model if
   not cached, runs generation, uploads the output video to Supabase Storage,
   sets status to `complete` with a result URL.
5. Dispatcher's polling loop (or a Supabase Realtime subscription) notices the
   status change, downloads the video, sends it to the user via Telegram, marks
   the job `delivered`.
6. Cleanup job removes the file from storage after delivery confirmation.

This queue-based decoupling is what lets you use *unreliable, session-limited*
free GPUs without the user ever seeing a crash — worst case, generation just
takes longer because no worker happened to be online.

### 1.3 Folder structure

```
telegram-ai-video-bot/
├── dispatcher/                  # Always-on service (deploy this, free tier)
│   ├── main.py                  # FastAPI app: Telegram webhook + polling loop
│   ├── bot/
│   │   ├── handlers.py          # /generate, /status, /cancel commands
│   │   ├── rate_limit.py
│   │   └── validation.py        # prompt validation, NSFW filtering
│   ├── queue/
│   │   ├── db.py                # Supabase client wrapper
│   │   └── models.py            # Job schema
│   ├── requirements.txt
│   └── Dockerfile               # optional, for Fly.io/Render deploy
│
├── worker/                      # Runs inside GPU notebooks (Colab/Kaggle/etc.)
│   ├── worker.py                # Poll loop: claim job → generate → upload
│   ├── models/
│   │   ├── registry.py          # Model name → loader mapping
│   │   ├── wan_loader.py
│   │   ├── cogvideox_loader.py
│   │   ├── hunyuan_loader.py
│   │   ├── ltx_loader.py
│   │   └── mochi_loader.py
│   ├── gpu_detect.py             # Detects VRAM, picks compatible model config
│   ├── notebooks/
│   │   ├── colab_worker.ipynb
│   │   ├── kaggle_worker.ipynb
│   │   ├── lightning_worker.ipynb
│   │   ├── paperspace_worker.ipynb
│   │   └── sagemaker_worker.ipynb
│   └── requirements.txt
│
├── scripts/
│   ├── download_models.py        # HF Hub download + organize by VRAM tier
│   ├── cleanup_storage.py
│   └── provider_rotation.py      # Suggests which free provider to use next
│
├── shared/
│   ├── config.py                 # Shared constants (model configs, limits)
│   └── schema.sql                # Supabase table definitions
│
├── docs/
│   └── (this guide, split by part)
│
├── .env.example
└── README.md
```

### 1.4 Technology stack

| Layer | Choice | Why |
|---|---|---|
| Bot framework | `python-telegram-bot` (async) | Mature, well-documented, handles webhooks + polling |
| Dispatcher host | Fly.io free / Render free / Oracle Free Tier | Genuinely always-on at $0, unlike notebooks |
| Queue + DB | Supabase (Postgres) free tier | 500MB DB, free, gives you Realtime + Storage in one account |
| File storage | Supabase Storage free tier (1GB) or Google Drive via `pydrive2` | Video files are large — plan cleanup aggressively |
| GPU compute | Kaggle, Colab, Lightning AI, Paperspace Gradient, SageMaker Studio Lab | Rotate based on quota availability |
| Model formats | Safetensors (primary), GGUF (for CPU-fallback/quantized cases) | Safety + broad tool support |
| Inference | `diffusers`, model-specific repos (CogVideoX, HunyuanVideo, etc.) | Covered per-model in Part 7 |

### 1.5 Free vs. paid roadmap (preview of Part 12)

- **Free:** Fly.io/Render dispatcher + Supabase + rotating notebook workers.
  Expect queue delays (minutes to hours depending on which provider has quota
  left) and a hard ceiling on concurrent users.
- **Hybrid:** Keep the dispatcher free, replace notebook workers with a single
  paid on-demand GPU (RunPod, Modal) that spins up only when jobs are queued —
  you pay per second of actual generation, not idle time.
- **Paid production:** Dedicated GPU pool, S3 + CDN for storage/delivery,
  autoscaling worker fleet. Architecture doesn't change — only the worker and
  storage layers are swapped.

---

*Next: Part 2 (account setup, exact steps per provider) and Part 3 (model
selection by VRAM + download scripts). Reply "continue" and I'll append them.*

---

## Part 2 — Accounts to Create

Create these in order — some steps (e.g. Supabase) are needed before you can test the bot end-to-end.

### 2.1 Telegram Bot
1. Open Telegram, message **@BotFather**.
2. `/newbot` → choose a display name → choose a username ending in `bot`.
3. Save the **bot token** (`123456:ABC-...`). This goes in `.env` as `TELEGRAM_BOT_TOKEN`.
4. Optional: `/setcommands` to register `/generate`, `/status`, `/cancel` for the command menu.

### 2.2 Hugging Face
1. Sign up at huggingface.co → Settings → Access Tokens → New token (Read scope is enough for downloading).
2. Some video models (HunyuanVideo, Mochi) are gated — visit the model page and accept the license before your token can download them.

### 2.3 Kaggle
1. Sign up, verify phone number (required to unlock GPU quota).
2. Settings → API → Create New Token → downloads `kaggle.json`. Needed for `kaggle kernels` CLI-based automation later.
3. You get ~30 GPU-hours/week (P100 or T4x2), reset weekly.

### 2.4 Google Colab
1. Just a Google account. Free tier gives a T4, usage-capped and dynamically throttled based on demand — don't rely on exact hour counts.
2. Colab Pro is optional/paid — skip it for the free build.

### 2.5 Lightning AI
1. Sign up at lightning.ai. Free tier includes monthly GPU credits (check current allowance in-app, it changes).
2. Studios persist code/environment between sessions, which is a real advantage over Colab/Kaggle for iterating on worker code.

### 2.6 Paperspace Gradient
1. Sign up, free tier includes a free M4000/free-tier GPU notebook (instance type availability varies — check Gradient's console).
2. Free instances auto-shutdown after idle timeout — fine for our burst-worker model.

### 2.7 Amazon SageMaker Studio Lab
1. Apply at studiolab.sagemaker.aws (approval can take a day or two — do this one first).
2. Free tier: 4 hours GPU/day session limit, no AWS billing account required.

### 2.8 GitHub
1. Used to host the worker notebooks/code so each provider can `git clone` your repo at session start instead of you re-uploading files each time.
2. Keep the repo **private** if it contains any config; never commit `.env` or tokens.

### 2.9 Supabase
1. Sign up, create a new project (free tier: 500MB Postgres, 1GB Storage, 2GB bandwidth/month).
2. Project Settings → API → copy `URL` and `anon` / `service_role` keys.
3. Run `shared/schema.sql` (Part 6) in the SQL Editor to create the `jobs` table.
4. Storage → create a bucket named `videos`, set it to private (signed URLs only).

### 2.10 Cloudflare (optional, for later scaling)
1. Only needed once you outgrow Supabase Storage bandwidth — Cloudflare R2 + CDN has a generous free egress allowance. Skip for v1.

---

## Part 3 — Downloading Models

### 3.1 Choosing models by VRAM

| Model | Min VRAM (quantized) | Recommended VRAM | Notes |
|---|---|---|---|
| LTX Video | ~8GB | 12GB | Fastest, lowest quality ceiling — good default for free T4s |
| CogVideoX-2B | ~8GB | 12GB | Good balance, 2B variant fits free tiers |
| CogVideoX-5B | ~16GB | 24GB | Better quality, needs A10/A100-class — rare on free tiers |
| Wan 2.1 (1.3B) | ~8GB | 12GB | Smaller Wan variant is free-tier friendly |
| HunyuanVideo | ~24GB+ | 45GB+ | Generally not free-tier viable except heavily quantized/short clips |
| Mochi 1 | ~24GB | 40GB+ | Same — treat as "paid tier" model, mention but don't default to it |

**Practical default for v1:** LTX Video or CogVideoX-2B as the primary model, with Wan 1.3B as a fallback. Gate HunyuanVideo/Mochi behind a premium/paid-worker flag rather than promising them on free GPUs — this avoids the guide overselling what a T4 can do.

### 3.2 Download script

```python
# scripts/download_models.py
import os
from huggingface_hub import snapshot_download

MODELS_DIR = os.environ.get("MODELS_DIR", "./models")

MODEL_REGISTRY = {
    "ltx-video": {
        "repo_id": "Lightricks/LTX-Video",
        "min_vram_gb": 8,
    },
    "cogvideox-2b": {
        "repo_id": "THUDM/CogVideoX-2b",
        "min_vram_gb": 8,
    },
    "wan-1.3b": {
        "repo_id": "Wan-AI/Wan2.1-T2V-1.3B",
        "min_vram_gb": 8,
    },
    # Gate these behind paid/large-GPU workers:
    "hunyuanvideo": {
        "repo_id": "tencent/HunyuanVideo",
        "min_vram_gb": 45,
    },
    "mochi-1": {
        "repo_id": "genmo/mochi-1-preview",
        "min_vram_gb": 40,
    },
}


def download_model(name: str, token: str | None = None):
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model '{name}'. Options: {list(MODEL_REGISTRY)}")
    cfg = MODEL_REGISTRY[name]
    dest = os.path.join(MODELS_DIR, name)
    print(f"Downloading {name} ({cfg['repo_id']}) -> {dest}")
    snapshot_download(
        repo_id=cfg["repo_id"],
        local_dir=dest,
        token=token or os.environ.get("HF_TOKEN"),
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model"],
    )
    print(f"Done: {name}")


def pick_model_for_vram(available_gb: float) -> str:
    """Return the best model that fits the given VRAM budget."""
    candidates = sorted(
        MODEL_REGISTRY.items(), key=lambda kv: kv[1]["min_vram_gb"], reverse=True
    )
    for name, cfg in candidates:
        if cfg["min_vram_gb"] <= available_gb:
            return name
    raise RuntimeError("No model fits the available VRAM")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=list(MODEL_REGISTRY) + ["auto"])
    parser.add_argument("--vram", type=float, default=8.0, help="Available VRAM in GB (for 'auto')")
    args = parser.parse_args()

    name = pick_model_for_vram(args.vram) if args.model == "auto" else args.model
    download_model(name)
```

### 3.3 Organizing checkpoints, safetensors vs GGUF

- Keep one folder per model under `models/<name>/`, never mix versions in the same folder — `diffusers`-style pipelines expect a specific file layout (`model_index.json`, `unet/`, `vae/`, etc.), and a stray extra `.safetensors` can break auto-detection.
- **Safetensors**: use for anything loaded through `diffusers`/`transformers` — safe deserialization (no arbitrary code execution risk like old `.ckpt` pickle files), and it's what all the models above ship in natively.
- **GGUF**: only relevant if you're running a quantized/CPU-fallback path (e.g. via `llama.cpp`-style runners for smaller components). For the video models listed above, stick to safetensors — GGUF tooling for video diffusion is far less mature than for LLMs.
- Delete a model's cache directory entirely before re-downloading a corrected copy; partial downloads are the #1 cause of "works on Colab, fails on Kaggle" bugs.

---

## Part 4 — Free GPU Providers: Worker Setup

### 4.1 Shared worker pattern

Every provider notebook does the same four things:
1. `git clone` your repo (so worker code stays in sync without re-uploading).
2. `pip install -r worker/requirements.txt`.
3. `python worker/gpu_detect.py` → decide which model to load.
4. `python worker/worker.py` → enter the poll loop until the session ends.

### 4.2 GPU detection

```python
# worker/gpu_detect.py
import subprocess
import torch


def get_available_vram_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    props = torch.cuda.get_device_properties(0)
    total_gb = props.total_memory / (1024 ** 3)
    return round(total_gb, 1)


def gpu_name() -> str:
    if not torch.cuda.is_available():
        return "cpu"
    return torch.cuda.get_device_name(0)


if __name__ == "__main__":
    vram = get_available_vram_gb()
    print(f"GPU: {gpu_name()} | VRAM: {vram} GB")
```

### 4.3 Colab setup (`worker/notebooks/colab_worker.ipynb` — cell contents)

```python
# Cell 1
!git clone https://github.com/<you>/telegram-ai-video-bot.git
%cd telegram-ai-video-bot
!pip install -r worker/requirements.txt -q

# Cell 2 — secrets (use Colab's "Secrets" panel, not hardcoded values)
import os
from google.colab import userdata
os.environ["SUPABASE_URL"] = userdata.get("SUPABASE_URL")
os.environ["SUPABASE_KEY"] = userdata.get("SUPABASE_KEY")
os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN")

# Cell 3
!python worker/gpu_detect.py

# Cell 4 — runs until session disconnects; that's expected behavior
!python worker/worker.py --provider colab
```

### 4.4 Kaggle setup
- New Notebook → Settings → Accelerator → GPU T4 x2 (or P100).
- Add your Supabase/HF credentials as Kaggle **Secrets** (Add-ons → Secrets), not plaintext.
- Same 4 cells as Colab, swap `--provider kaggle`.
- Kaggle kills sessions after 9 hours or on idle timeout — worker loop should checkpoint nothing mid-generation; if the session dies mid-job, the dispatcher's timeout logic (Part 9) requeues it.

### 4.5 Lightning AI setup
- Create a Studio, select a free-tier GPU.
- Studios persist a filesystem between sessions — clone the repo once, `git pull` on subsequent sessions instead of re-cloning.
- Run worker via the Studio terminal: `python worker/worker.py --provider lightning`.

### 4.6 Paperspace Gradient setup
- Create a Notebook, choose the free GPU instance type available at signup time (varies).
- Same clone → install → detect → run pattern via the notebook terminal.
- Free instances auto-terminate after 6 hours or idle timeout — this is fine, the worker is stateless between jobs.

### 4.7 SageMaker Studio Lab setup
- Start Runtime → GPU.
- 4-hour session cap, resets daily. Same worker pattern via terminal.

### 4.8 Automatic fallback / rotation strategy

You can't fully automate *starting* these sessions (each requires clicking "Run" in a browser due to how free tiers prevent headless abuse) — but you can automate *which one to try next*:

```python
# scripts/provider_rotation.py
"""
Tracks rough weekly/daily usage per provider so you know which one
still has quota left. Run this locally before opening a notebook.
"""
import json
import datetime
from pathlib import Path

STATE_FILE = Path("provider_usage.json")

PROVIDERS = {
    "kaggle": {"quota_hours": 30, "reset": "weekly"},
    "colab": {"quota_hours": None, "reset": "dynamic"},  # not fixed, throttled by demand
    "lightning": {"quota_hours": None, "reset": "monthly"},  # credit-based, check dashboard
    "paperspace": {"quota_hours": 6, "reset": "per-session"},
    "sagemaker": {"quota_hours": 4, "reset": "daily"},
}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {p: {"used_hours": 0, "last_reset": str(datetime.date.today())} for p in PROVIDERS}


def suggest_next(state):
    ranked = []
    for name, cfg in PROVIDERS.items():
        used = state[name]["used_hours"]
        quota = cfg["quota_hours"]
        remaining = (quota - used) if quota else float("inf")
        ranked.append((remaining, name))
    ranked.sort(reverse=True)
    return ranked[0][1]


if __name__ == "__main__":
    state = load_state()
    print("Suggested next provider:", suggest_next(state))
```

This is intentionally simple — a spreadsheet would do the same job. The real automation value comes later if you add a scheduler (e.g., a GitHub Action that emails/Telegram-DMs *you* a reminder to open the next provider's notebook when quota resets).

---

## Part 5 — Telegram Bot

### 5.1 Creating the bot
Covered in 2.1. Below is the actual handler code.

### 5.2 Webhooks vs polling
- **Polling** (`run_polling()`): simplest, works anywhere, no public HTTPS endpoint needed. Use this if hosting on a platform without an easy public URL.
- **Webhooks**: lower latency, but require a stable HTTPS endpoint — use once deployed to Fly.io/Render (they give you one for free).
- Recommendation: build with polling locally, switch to webhook only after dispatcher is deployed (Part 9 shows both).

### 5.3 Command handling, queueing, progress, errors

```python
# dispatcher/bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from queue.db import create_job, get_job_status, cancel_job
from bot.validation import validate_prompt
from bot.rate_limit import check_rate_limit


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prompt = " ".join(context.args)

    if not prompt:
        await update.message.reply_text("Usage: /generate <prompt>")
        return

    ok, reason = validate_prompt(prompt)
    if not ok:
        await update.message.reply_text(f"Prompt rejected: {reason}")
        return

    allowed, wait_seconds = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            f"Rate limit hit. Try again in {wait_seconds}s."
        )
        return

    job = create_job(user_id=user_id, prompt=prompt)
    await update.message.reply_text(
        f"Queued (job #{job['id']}). Use /status {job['id']} to check progress."
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <job_id>")
        return
    job_id = context.args[0]
    job = get_job_status(job_id)
    if not job:
        await update.message.reply_text("Job not found.")
        return
    await update.message.reply_text(f"Job #{job_id}: {job['status']}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cancel <job_id>")
        return
    job_id = context.args[0]
    cancelled = cancel_job(job_id, requester_id=update.effective_user.id)
    msg = "Cancelled." if cancelled else "Could not cancel (already running or not yours)."
    await update.message.reply_text(msg)
```

```python
# dispatcher/main.py
import os
import asyncio
from telegram.ext import Application, CommandHandler
from bot.handlers import generate_command, status_command, cancel_command
from queue.db import poll_completed_jobs, mark_delivered

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


async def delivery_loop(app: Application):
    """Watches for jobs marked 'complete' by workers and sends results to users."""
    while True:
        completed = poll_completed_jobs()
        for job in completed:
            try:
                await app.bot.send_video(
                    chat_id=job["user_id"],
                    video=job["result_url"],
                    caption=f"Done: {job['prompt'][:100]}",
                )
                mark_delivered(job["id"])
            except Exception as e:
                print(f"Delivery failed for job {job['id']}: {e}")
        await asyncio.sleep(5)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.job_queue.run_once(lambda ctx: asyncio.create_task(delivery_loop(app)), when=0)
    app.run_polling()  # swap to run_webhook(...) once deployed with a public URL


if __name__ == "__main__":
    main()
```

---

## Part 6 — Backend

### 6.1 Supabase schema

```sql
-- shared/schema.sql
create table if not exists jobs (
    id bigint generated always as identity primary key,
    user_id bigint not null,
    prompt text not null,
    status text not null default 'pending',  -- pending | processing | complete | failed | delivered | cancelled
    model text,
    worker_id text,
    result_url text,
    error text,
    created_at timestamptz default now(),
    claimed_at timestamptz,
    completed_at timestamptz
);

create index if not exists idx_jobs_status on jobs (status);
create index if not exists idx_jobs_user on jobs (user_id);
```

### 6.2 Queue client

```python
# dispatcher/queue/db.py  (also imported by worker.py in the notebook environment)
import os
from supabase import create_client

_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def create_job(user_id: int, prompt: str) -> dict:
    res = _client.table("jobs").insert({
        "user_id": user_id, "prompt": prompt, "status": "pending"
    }).execute()
    return res.data[0]


def get_job_status(job_id: str) -> dict | None:
    res = _client.table("jobs").select("*").eq("id", job_id).execute()
    return res.data[0] if res.data else None


def cancel_job(job_id: str, requester_id: int) -> bool:
    job = get_job_status(job_id)
    if not job or job["user_id"] != requester_id or job["status"] not in ("pending",):
        return False
    _client.table("jobs").update({"status": "cancelled"}).eq("id", job_id).execute()
    return True


def poll_completed_jobs() -> list[dict]:
    res = _client.table("jobs").select("*").eq("status", "complete").execute()
    return res.data


def mark_delivered(job_id: str):
    _client.table("jobs").update({"status": "delivered"}).eq("id", job_id).execute()


# --- worker-side helpers ---

def claim_next_job(worker_id: str) -> dict | None:
    """Atomically claim the oldest pending job. Uses a Postgres function for atomicity."""
    res = _client.rpc("claim_job", {"p_worker_id": worker_id}).execute()
    return res.data[0] if res.data else None


def mark_complete(job_id: str, result_url: str):
    _client.table("jobs").update({
        "status": "complete", "result_url": result_url
    }).eq("id", job_id).execute()


def mark_failed(job_id: str, error: str):
    _client.table("jobs").update({"status": "failed", "error": error}).eq("id", job_id).execute()
```

```sql
-- Atomic claim function (prevents two workers grabbing the same job)
create or replace function claim_job(p_worker_id text)
returns setof jobs as $$
begin
    return query
    update jobs
    set status = 'processing', worker_id = p_worker_id, claimed_at = now()
    where id = (
        select id from jobs
        where status = 'pending'
        order by created_at asc
        limit 1
        for update skip locked
    )
    returning *;
end;
$$ language plpgsql;
```

### 6.3 Session/user management

Keep it minimal for v1 — no separate `users` table needed yet. Rate limiting
(Part 10) and job history are enough, since Telegram already gives you a stable
`user_id`. Add a `users` table only when you introduce premium tiers.

---

## Part 7 — Running Video Models

### 7.1 Model loader pattern

```python
# worker/models/registry.py
from models.ltx_loader import load_ltx, generate_ltx
from models.cogvideox_loader import load_cogvideox, generate_cogvideox
from models.wan_loader import load_wan, generate_wan

LOADERS = {
    "ltx-video": (load_ltx, generate_ltx),
    "cogvideox-2b": (load_cogvideox, generate_cogvideox),
    "wan-1.3b": (load_wan, generate_wan),
}


def get_pipeline(model_name: str):
    load_fn, _ = LOADERS[model_name]
    return load_fn()


def run_generation(model_name: str, pipeline, prompt: str, **kwargs):
    _, gen_fn = LOADERS[model_name]
    return gen_fn(pipeline, prompt, **kwargs)
```

```python
# worker/models/ltx_loader.py
import torch
from diffusers import LTXPipeline
from diffusers.utils import export_to_video

MODEL_PATH = "./models/ltx-video"


def load_ltx():
    pipe = LTXPipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()  # important on 8-12GB cards
    return pipe


def generate_ltx(pipe, prompt: str, num_frames: int = 65, fps: int = 24, output_path: str = "out.mp4"):
    video = pipe(
        prompt=prompt,
        width=512,
        height=320,
        num_frames=num_frames,
        num_inference_steps=30,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path
```

`cogvideox_loader.py` and `wan_loader.py` follow the identical shape — swap the
`diffusers` pipeline class (`CogVideoXPipeline`, or the appropriate Wan pipeline)
and adjust default resolution/frame count to what fits in 8–12GB after
`enable_model_cpu_offload()` + `enable_vae_slicing()`. For HunyuanVideo/Mochi
(paid-tier workers only), skip CPU offload and instead rely on having a real
24GB+ card — offload will make them technically run but unusably slow.

### 7.2 Frame interpolation (optional quality boost)

```python
# worker/models/interpolate.py
# Uses RIFE for cheap frame interpolation to smooth low-fps output
import subprocess

def interpolate_video(input_path: str, output_path: str, target_fps: int = 24):
    subprocess.run([
        "python", "-m", "rife_ncnn_vulkan",
        "-i", input_path, "-o", output_path, "-f", str(target_fps)
    ], check=True)
```

### 7.3 Video encoding

```python
# worker/models/encode.py
import subprocess

def encode_for_telegram(input_path: str, output_path: str):
    """Telegram prefers H.264 MP4, faststart for quick preview."""
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-movflags", "+faststart",
        output_path
    ], check=True)
```

---

## Part 8 — File Management

```python
# worker/storage.py
import os
from supabase import create_client

_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
BUCKET = "videos"


def upload_result(job_id: str, file_path: str) -> str:
    dest_path = f"{job_id}.mp4"
    with open(file_path, "rb") as f:
        _client.storage.from_(BUCKET).upload(dest_path, f, {"content-type": "video/mp4"})
    # Signed URL, expires in 1 hour — enough time for the dispatcher to deliver it
    signed = _client.storage.from_(BUCKET).create_signed_url(dest_path, 3600)
    return signed["signedURL"]


def cleanup_local(file_path: str):
    if os.path.exists(file_path):
        os.remove(file_path)
```

```python
# scripts/cleanup_storage.py
"""Run periodically (e.g. via a scheduled GitHub Action) to remove delivered
job files from Supabase Storage older than 24 hours."""
import datetime
from dispatcher.queue.db import _client

def cleanup_old_files(hours: int = 24):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    res = _client.table("jobs").select("id").eq("status", "delivered").lt("completed_at", cutoff.isoformat()).execute()
    for job in res.data:
        _client.storage.from_("videos").remove([f"{job['id']}.mp4"])
    print(f"Cleaned {len(res.data)} files")

if __name__ == "__main__":
    cleanup_old_files()
```

Telegram file IDs: once a video is sent via `send_video`, Telegram returns a
`file_id` you can cache and re-send instantly (no re-upload) if a user requests
the same result again — store it on the job row as `telegram_file_id` if you
want this optimization.

---

## Part 9 — Production Workflow

### 9.1 Worker poll loop

```python
# worker/worker.py
import argparse
import time
import traceback
from models.registry import get_pipeline, run_generation
from models.encode import encode_for_telegram
from storage import upload_result, cleanup_local
from queue_client import claim_next_job, mark_complete, mark_failed  # worker-side wrapper around dispatcher/queue/db.py

POLL_INTERVAL_SECONDS = 10
MAX_RETRIES = 2


def main(provider: str, model_name: str):
    worker_id = f"{provider}-{int(time.time())}"
    pipeline = get_pipeline(model_name)
    print(f"Worker {worker_id} ready with model {model_name}")

    while True:
        job = claim_next_job(worker_id)
        if not job:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        print(f"Processing job {job['id']}: {job['prompt'][:60]}")
        attempt = 0
        while attempt <= MAX_RETRIES:
            try:
                raw_path = run_generation(model_name, pipeline, job["prompt"])
                final_path = f"encoded_{job['id']}.mp4"
                encode_for_telegram(raw_path, final_path)
                url = upload_result(job["id"], final_path)
                mark_complete(job["id"], url)
                cleanup_local(raw_path)
                cleanup_local(final_path)
                break
            except Exception as e:
                attempt += 1
                print(f"Attempt {attempt} failed: {e}")
                traceback.print_exc()
                if attempt > MAX_RETRIES:
                    mark_failed(job["id"], str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default="ltx-video")
    args = parser.parse_args()
    main(args.provider, args.model)
```

### 9.2 Stuck-job timeout (dispatcher side)

Add a periodic check that requeues jobs stuck in `processing` for too long
(handles the case where a Kaggle/Colab session dies mid-generation):

```python
# dispatcher/queue/timeout_check.py
import datetime
from queue.db import _client

STUCK_THRESHOLD_MINUTES = 20

def requeue_stuck_jobs():
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    _client.table("jobs").update({"status": "pending", "worker_id": None}) \
        .eq("status", "processing").lt("claimed_at", cutoff.isoformat()).execute()
```

Run this on a timer inside the dispatcher's job queue (e.g. every 5 minutes via
`app.job_queue.run_repeating`).

---

## Part 10 — Security

```python
# dispatcher/bot/validation.py
import re

BLOCKED_TERMS = {"csam", "cp", "child"}  # extend with a real moderation list/service
MAX_PROMPT_LENGTH = 300

def validate_prompt(prompt: str) -> tuple[bool, str]:
    if len(prompt) > MAX_PROMPT_LENGTH:
        return False, f"Prompt too long (max {MAX_PROMPT_LENGTH} chars)."
    lowered = prompt.lower()
    if any(term in lowered for term in BLOCKED_TERMS):
        return False, "Prompt violates content policy."
    if not re.search(r"[a-zA-Z]", prompt):
        return False, "Prompt must contain readable text."
    return True, ""
```

```python
# dispatcher/bot/rate_limit.py
import time

_last_request: dict[int, float] = {}
MIN_SECONDS_BETWEEN_REQUESTS = 60

def check_rate_limit(user_id: int) -> tuple[bool, int]:
    now = time.time()
    last = _last_request.get(user_id, 0)
    elapsed = now - last
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        return False, int(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request[user_id] = now
    return True, 0
```

**Secrets management:**
- Never commit `.env`. Use `.env.example` with placeholder keys.
- On Fly.io/Render: use their secrets manager (`fly secrets set KEY=value`), not env vars baked into the Docker image.
- On notebooks: use each platform's built-in secrets store (Colab Secrets, Kaggle Secrets) — never paste tokens directly into notebook cells that might get shared/forked publicly.
- Rotate the Supabase `service_role` key immediately if a notebook is ever accidentally made public.

**Real content moderation note:** the `BLOCKED_TERMS` list above is a placeholder, not real moderation. For anything user-facing, route prompts through a proper moderation API (e.g. an LLM moderation endpoint) before generation — a keyword blocklist alone will both over- and under-block.

---

## Part 11 — Monitoring

```python
# dispatcher/monitoring/logging_setup.py
import logging

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("telegram-video-bot")
```

- **Logs:** structured logging as above is enough for v1; ship to a free tier like Better Stack / Logtail if you want searchable history.
- **Error reports:** wrap the dispatcher's top-level handlers in a try/except that posts failures to a private Telegram channel you control — free, instant alerting with zero extra infra.
- **Performance metrics:** track `completed_at - claimed_at` per job in the `jobs` table itself; a simple `select avg(...)` query gives you generation-time trends without needing a metrics stack.

---

## Part 12 — Scaling Path

1. **Free architecture (this guide):** Fly.io/Render dispatcher + Supabase + rotating free-tier GPU notebooks. Expect variable latency (minutes–hours) and a low realistic ceiling (a handful of concurrent users before queue times become unacceptable).
2. **Hybrid architecture:** Keep dispatcher + Supabase as-is. Replace manual notebook rotation with a paid on-demand GPU (RunPod serverless, Modal) that spins up automatically when a job is queued and shuts down after — you pay per second of actual compute, typically far cheaper than a dedicated always-on GPU box.
3. **Paid production architecture:** Dedicated GPU pool (RunPod/Lambda/AWS) with autoscaling, S3 + Cloudflare CDN replacing Supabase Storage for bandwidth headroom, Redis replacing the Postgres-based queue for lower latency at high job volume. The dispatcher's *interface* to the queue stays the same — only the implementation underneath changes, so none of the Telegram bot code needs to change.

---

## Part 13 — Future Upgrades

- **Modal / RunPod / Beam:** serverless GPU functions — natural replacement for the notebook rotation once you're ready to pay. Each has a Python SDK that maps closely to the `worker.py` poll loop you already built, so migration is mostly swapping the "how do I get a GPU" step.
- **S3 + Cloudflare CDN:** swap in once Supabase's free 1GB storage / 2GB bandwidth becomes the bottleneck — usually the first free-tier limit you'll hit if the bot gets real traction.
- **Multiple GPUs / concurrent workers:** the `claim_job` Postgres function (Part 6) already supports multiple workers claiming from the same queue safely (`for update skip locked`) — scaling to N workers requires no queue changes, just running more worker instances.

---

*Guide complete — Parts 1–13.*

---

## Part 14 — Free-Tier Model Addendum (Wan 2.2 / Wan-Dancer Reality Check)

### 14.1 Why Wan2.2-TI2V-5B and Wan-Dancer-14B don't fit the free tier

| Model | Size | Min VRAM (offload) | Free-tier viable? |
|-------|------|-------------------|-------------------|
| Wan2.2-TI2V-5B | 34.2 GB | 24 GB (A100/4090) | ❌ Colab T4 = 16 GB |
| Wan-Dancer-14B | 85.7 GB | 48–80 GB (H100/A100 80GB) | ❌ Not even paid Colab Pro |

**Use Wan2.1-T2V-1.3B instead** for free-tier text-to-video:
- ~8 GB VRAM with `enable_model_cpu_offload()` + `enable_vae_slicing()`
- Runs on Colab T4 / Kaggle T4x2 / Paperspace free GPU
- 480p, ~2–4 second clips

### 14.2 Updated MODEL_REGISTRY with clip limits

```python
# scripts/download_models.py (updated)
MODEL_REGISTRY = {
    "ltx-video": {
        "repo_id": "Lightricks/LTX-Video",
        "min_vram_gb": 8,
        "max_seconds": 4,
        "resolution": "512x320",
        "fps": 24,
    },
    "cogvideox-2b": {
        "repo_id": "THUDM/CogVideoX-2b",
        "min_vram_gb": 8,
        "max_seconds": 6,
        "resolution": "480x480",
        "fps": 8,
    },
    "wan-1.3b": {
        "repo_id": "Wan-AI/Wan2.1-T2V-1.3B",
        "min_vram_gb": 8,
        "max_seconds": 4,
        "resolution": "480x832",  # Wan native aspect
        "fps": 16,
    },
    # Paid-tier only (require A100/H100):
    "wan-2.2-ti2v-5b": {
        "repo_id": "Wan-AI/Wan2.2-TI2V-5B",
        "min_vram_gb": 24,
        "max_seconds": 5,
        "resolution": "1280x704",
        "fps": 24,
    },
    "wan-dancer-14b": {
        "repo_id": "Wan-AI/Wan-Dancer-14B",
        "min_vram_gb": 48,
        "max_seconds": 60,  # minute-scale, but needs massive VRAM
        "resolution": "720p",
        "fps": 24,
    },
    "hunyuanvideo": {
        "repo_id": "tencent/HunyuanVideo",
        "min_vram_gb": 45,
        "max_seconds": 5,
        "resolution": "720p",
        "fps": 24,
    },
    "mochi-1": {
        "repo_id": "genmo/mochi-1-preview",
        "min_vram_gb": 40,
        "max_seconds": 5,
        "resolution": "480p",
        "fps": 30,
    },
}
```

### 14.3 Prompt validation with duration awareness

```python
# dispatcher/bot/validation.py (addition)
MAX_SECONDS_BY_MODEL = {
    "ltx-video": 4,
    "cogvideox-2b": 6,
    "wan-1.3b": 4,
}

def validate_prompt(prompt: str, model: str = "ltx-video") -> tuple[bool, str]:
    # ... existing checks ...
    
    # Parse optional --seconds N suffix
    import re
    sec_match = re.search(r"--seconds\s+(\d+)$", prompt)
    if sec_match:
        requested = int(sec_match.group(1))
        max_allowed = MAX_SECONDS_BY_MODEL.get(model, 4)
        if requested > max_allowed:
            return False, f"Max {max_allowed}s for {model} on free GPU. Requested {requested}s."
    
    return True, ""
```

---

## Part 15 — Google Drive Model Storage for Colab Workers

### 15.1 One-time setup: Download models to Drive

Run once in a Colab notebook (or locally with `gdown`):

```python
# Colab notebook: download_models_to_drive.ipynb
from google.colab import drive
drive.mount('/content/drive')

import os
from huggingface_hub import snapshot_download

MODELS_ROOT = "/content/drive/MyDrive/ai-video-models"
os.makedirs(MODELS_ROOT, exist_ok=True)

MODELS = {
    "ltx-video": "Lightricks/LTX-Video",
    "cogvideox-2b": "THUDM/CogVideoX-2b",
    "wan-1.3b": "Wan-AI/Wan2.1-T2V-1.3B",
}

for name, repo_id in MODELS.items():
    dest = os.path.join(MODELS_ROOT, name)
    print(f"Downloading {name} -> {dest}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=dest,
        token=os.environ.get("HF_TOKEN"),
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model"],
    )
    print(f"Done: {name}")
```

### 15.2 Worker loads from Drive (Colab cell)

```python
# Colab worker notebook — Cell 2 (after git clone & pip install)
from google.colab import userdata
import os

# Secrets (set in Colab's 🔑 Secrets panel)
os.environ["SUPABASE_URL"] = userdata.get("SUPABASE_URL")
os.environ["SUPABASE_KEY"] = userdata.get("SUPABASE_KEY")
os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN")

# Mount Drive
from google.colab import drive
drive.mount('/content/drive', force_remount=True)

MODELS_DIR = "/content/drive/MyDrive/ai-video-models"
print("Available models:", os.listdir(MODELS_DIR))
```

### 15.3 Model loader uses Drive path

```python
# worker/models/wan_loader.py (updated)
import os
import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL_PATH = os.environ.get("MODELS_DIR", "./models")

def load_wan(model_name: str = "wan-1.3b"):
    model_path = os.path.join(MODEL_PATH, model_name)
    pipe = WanPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        variant="fp16",
    )
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    return pipe


def generate_wan(pipe, prompt: str, num_frames: int = 64, fps: int = 16, output_path: str = "out.mp4"):
    video = pipe(
        prompt=prompt,
        width=832,
        height=480,
        num_frames=num_frames,
        num_inference_steps=30,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path
```

---

## Part 16 — Hybrid Worker: RunPod Serverless (Pay-per-Second Upgrade)

When free-tier queue times become unacceptable, replace manual notebook rotation with **RunPod Serverless** — you pay only while generating.

### 16.1 RunPod worker template (Dockerfile)

```dockerfile
# worker/Dockerfile.runpod
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ ./worker/
COPY shared/ ./shared/
COPY scripts/download_models.py ./scripts/

# Pre-download the free-tier model (Wan 1.3B) into image
RUN python scripts/download_models.py wan-1.3b

ENV MODELS_DIR=/app/models
CMD ["python", "worker/worker.py", "--provider", "runpod"]
```

### 16.2 Deploy to RunPod Serverless

```bash
# Build & push
docker build -f worker/Dockerfile.runpod -t yourname/wan-worker .
docker push yourname/wan-worker

# In RunPod Console: Serverless → New Endpoint
# - Image: yourname/wan-worker
# - GPU: RTX A4000 (24GB) or A100 (40GB) — pay per second
# - Secrets: SUPABASE_URL, SUPABASE_KEY, HF_TOKEN
# - Min workers: 0 (scales to zero)
# - Max workers: 3 (your concurrency cap)
```

### 16.3 Dispatcher calls RunPod instead of polling DB

```python
# dispatcher/queue/runpod_client.py
import os
import requests

RUNPOD_ENDPOINT_ID = os.environ["RUNPOD_ENDPOINT_ID"]
RUNPOD_API_KEY = os.environ["RUNPOD_API_KEY"]
BASE = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}"

def submit_job(prompt: str, model: str = "wan-1.3b") -> str:
    """Submit async job, returns runpod job ID."""
    resp = requests.post(
        f"{BASE}/run",
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
        json={"input": {"prompt": prompt, "model": model}},
    )
    resp.raise_for_status()
    return resp.json()["id"]

def poll_result(job_id: str, timeout: int = 300) -> dict:
    """Poll until complete or timeout."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(
            f"{BASE}/status/{job_id}",
            headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
        )
        data = resp.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            return data
        time.sleep(2)
    raise TimeoutError(f"RunPod job {job_id} timed out")
```

### 16.4 Hybrid queue: free workers first, RunPod fallback

```python
# dispatcher/queue/hybrid.py
import os
from queue.db import create_job, get_job_status
from queue.runpod_client import submit_job, poll_result

FREE_PROVIDERS = ["colab", "kaggle", "lightning", "paperspace", "sagemaker"]
RUNPOD_FALLBACK = os.environ.get("RUNPOD_ENDPOINT_ID") is not None

def dispatch_job(job_id: str, prompt: str, model: str):
    # Check if any free worker claimed it recently (via DB)
    job = get_job_status(job_id)
    if job and job["status"] == "processing":
        return  # Free worker picked it up

    # No free worker available → fire RunPod
    if RUNPOD_FALLBACK:
        runpod_id = submit_job(prompt, model)
        # Background task polls RunPod, updates Supabase when done
        # (run via app.job_queue.run_once in dispatcher)
        from queue.runpod_client import poll_result
        import asyncio
        asyncio.create_task(_wait_and_update(job_id, runpod_id))

async def _wait_and_update(local_job_id: str, runpod_id: str):
    result = await asyncio.to_thread(poll_result, runpod_id)
    if result["status"] == "COMPLETED":
        from queue.db import mark_complete
        mark_complete(local_job_id, result["output"]["video_url"])
    else:
        from queue.db import mark_failed
        mark_failed(local_job_id, result.get("error", "RunPod failed"))
```

---

## Part 17 — Prompt Enhancement (Free LLM via Groq)

Add cinematic detail to user prompts before generation — costs ~$0 on Groq free tier.

```python
# dispatcher/bot/enhance.py
import os
from groq import Groq

_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))  # free tier: 14.4k req/day

ENHANCE_PROMPT = """Expand the user's short prompt into a detailed, cinematic video generation prompt.
Include: subject, motion, camera angle, lighting, style, atmosphere, color palette.
Keep under 300 words. Output ONLY the enhanced prompt."""

def enhance_prompt(user_prompt: str) -> str:
    try:
        resp = _client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": ENHANCE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return user_prompt  # fallback to original
```

Wire into `/generate` handler:

```python
# dispatcher/bot/handlers.py (modify generate_command)
from bot.enhance import enhance_prompt

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... existing validation ...
    
    raw_prompt = " ".join(context.args)
    enhanced = enhance_prompt(raw_prompt)
    
    job = create_job(user_id=user_id, prompt=enhanced, raw_prompt=raw_prompt)
    await update.message.reply_text(
        f"Queued (job #{job['id']}). Enhanced prompt:\n<code>{enhanced[:200]}...</code>",
        parse_mode="HTML"
    )
```

Add `raw_prompt` column to `jobs` table (Part 6 schema) for transparency.

---

## Part 18 — Worker Health: GPU Memory Cleanup Between Jobs

Prevents OOM on consecutive jobs in same notebook session.

```python
# worker/worker.py (add to main loop)
import gc
import torch

def cleanup_gpu():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()
    # Log memory for monitoring
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        print(f"GPU mem: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")

# Inside the while True loop, after each job (success or failure):
cleanup_gpu()
```

---

## Part 19 — Telegram file_id Caching (Instant Re-send)

```python
# dispatcher/queue/db.py (add to mark_delivered)
def mark_delivered(job_id: str, telegram_file_id: str):
    _client.table("jobs").update({
        "status": "delivered",
        "telegram_file_id": telegram_file_id
    }).eq("id", job_id).execute()


# dispatcher/main.py (modify delivery_loop)
async def delivery_loop(app: Application):
    while True:
        completed = poll_completed_jobs()
        for job in completed:
            try:
                # Check cache first
                if job.get("telegram_file_id"):
                    await app.bot.send_video(
                        chat_id=job["user_id"],
                        video=job["telegram_file_id"],
                        caption=f"Done: {job['prompt'][:100]}"
                    )
                else:
                    msg = await app.bot.send_video(
                        chat_id=job["user_id"],
                        video=job["result_url"],
                        caption=f"Done: {job['prompt'][:100]}"
                    )
                    # Cache the file_id for next time
                    mark_delivered(job["id"], msg.video.file_id)
                mark_delivered(job["id"])
            except Exception as e:
                print(f"Delivery failed for job {job['id']}: {e}")
        await asyncio.sleep(5)
```

---

## Part 20 — Colab Notebook Template (Complete, Copy-Paste Ready)

Save as `worker/notebooks/colab_worker.ipynb` in your repo.

```json
{
  "nbformat": 4,
  "nbformat_minor": 4,
  "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}},
  "cells": [
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {"colab": {"name": "1. Clone repo & install deps"}},
      "outputs": [],
      "source": [
        "!git clone https://github.com/<YOUR_GITHUB>/telegram-ai-video-bot.git\n",
        "%cd telegram-ai-video-bot\n",
        "!pip install -r worker/requirements.txt -q\n"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {"colab": {"name": "2. Secrets & Drive mount"}},
      "outputs": [],
      "source": [
        "import os\n",
        "from google.colab import userdata, drive\n",
        "\n",
        "# Secrets (set in Colab 🔑 panel: SUPABASE_URL, SUPABASE_KEY, HF_TOKEN, GROQ_API_KEY)\n",
        "os.environ[\"SUPABASE_URL\"] = userdata.get(\"SUPABASE_URL\")\n",
        "os.environ[\"SUPABASE_KEY\"] = userdata.get(\"SUPABASE_KEY\")\n",
        "os.environ[\"HF_TOKEN\"] = userdata.get(\"HF_TOKEN\")\n",
        "os.environ[\"GROQ_API_KEY\"] = userdata.get(\"GROQ_API_KEY\")\n",
        "\n",
        "# Mount Google Drive (models stored here)\n",
        "drive.mount('/content/drive', force_remount=True)\n",
        "os.environ[\"MODELS_DIR\"] = \"/content/drive/MyDrive/ai-video-models\"\n",
        "print(\"Models dir:\", os.listdir(os.environ[\"MODELS_DIR\"]))\n"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {"colab": {"name": "3. GPU detect & model select"}},
      "outputs": [],
      "source": [
        "!python worker/gpu_detect.py\n",
        "\n",
        "# Auto-pick model for this GPU\n",
        "import subprocess, json\n",
        "result = subprocess.run([\"python\", \"worker/gpu_detect.py\"], capture_output=True, text=True)\n",
        "print(result.stdout)\n"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {"colab": {"name": "4. Run worker (runs until session ends)"}},
      "outputs": [],
      "source": [
        "# Uses auto-detected model from gpu_detect.py\n",
        "!python worker/worker.py --provider colab --model auto\n"
      ]
    }
  ]
}
```

---

## Part 21 — Updated Build Order (with new parts)

| Phase | Parts | Goal |
|-------|-------|------|
| **0. Foundations** | 6, 5 (local polling), 14 | DB schema → bot skeleton → confirm Wan 1.3B fits free VRAM |
| **1. First generation** | 3 (download Wan 1.3B), 15 (to Drive), 7, 9, 20 | Download model → Colab worker notebook → one successful generation |
| **2. Hardening** | 10, 11, 18, 19 | Security, monitoring, GPU cleanup, file_id caching |
| **3. UX polish** | 17, 4 (other providers) | Prompt enhancement, Kaggle/Lightning notebooks |
| **4. Scale** | 12, 13, 16 | Hybrid RunPod fallback, S3/CDN, serverless GPUs |

---

## Part 22 — `.env.example` (Complete)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...

# Supabase (Project Settings → API)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Hugging Face (Settings → Access Tokens → Read)
HF_TOKEN=hf_xxxxxxxxxxxx

# Groq (console.groq.com → API Keys, free tier)
GROQ_API_KEY=gsk_xxxxxxxxxxxx

# RunPod (optional, for hybrid fallback)
RUNPOD_ENDPOINT_ID=xxxxxxxx
RUNPOD_API_KEY=rpa_xxxxxxxxxxxx

# Local development only
MODELS_DIR=./models
```

---

**That's the complete, production-aware guide with your constraints addressed.** The Colab notebook (Part 20) + Drive download (Part 15) + Wan 1.3B model (Part 14) is your working v1. Run Parts 6→5→14→3→15→20 in that order and you'll have a video in Telegram within an hour.

---

## Part 23 — Missing Implementation Files (Copy-Paste Ready)

These were referenced but not fully shown. Save each to the path in your repo.

### 23.1 `shared/schema.sql` — Supabase tables

```sql
-- Run in Supabase SQL Editor
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,
    raw_prompt TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'ltx-video',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, claimed, processing, complete, failed, delivered
    provider TEXT,                           -- colab, kaggle, lightning, runpod, etc.
    worker_id TEXT,                          -- identifies which worker claimed it
    result_url TEXT,
    telegram_file_id TEXT,                   -- cached file_id for instant re-send
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_user ON jobs(user_id);

-- Atomic claim function (prevents race conditions)
CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id TEXT, p_provider TEXT)
RETURNS SETOF jobs LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    UPDATE jobs
    SET status = 'processing',
        worker_id = p_worker_id,
        provider = p_provider,
        claimed_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'pending'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING *;
END;
$$;

-- Mark complete
CREATE OR REPLACE FUNCTION mark_job_complete(p_job_id UUID, p_result_url TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    UPDATE jobs
    SET status = 'complete',
        result_url = p_result_url,
        completed_at = now()
    WHERE id = p_job_id;
END;
$$;

-- Mark failed
CREATE OR REPLACE FUNCTION mark_job_failed(p_job_id UUID, p_error TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    UPDATE jobs
    SET status = 'failed',
        error = p_error,
        completed_at = now()
    WHERE id = p_job_id;
END;
$$;
```

### 23.2 `shared/config.py` — Shared constants

```python
# shared/config.py
import os
from dataclasses import dataclass

@dataclass
class ModelConfig:
    name: str
    repo_id: str
    min_vram_gb: float
    max_seconds: int
    resolution: tuple[int, int]
    fps: int
    loader: str  # python module path to loader function

MODEL_CONFIGS = {
    "ltx-video": ModelConfig(
        name="ltx-video",
        repo_id="Lightricks/LTX-Video",
        min_vram_gb=8,
        max_seconds=4,
        resolution=(512, 320),
        fps=24,
        loader="worker.models.ltx_loader.load_ltx",
    ),
    "cogvideox-2b": ModelConfig(
        name="cogvideox-2b",
        repo_id="THUDM/CogVideoX-2b",
        min_vram_gb=8,
        max_seconds=6,
        resolution=(480, 480),
        fps=8,
        loader="worker.models.cogvideox_loader.load_cogvideox",
    ),
    "wan-1.3b": ModelConfig(
        name="wan-1.3b",
        repo_id="Wan-AI/Wan2.1-T2V-1.3B",
        min_vram_gb=8,
        max_seconds=4,
        resolution=(832, 480),
        fps=16,
        loader="worker.models.wan_loader.load_wan",
    ),
}

# Queue polling
POLL_INTERVAL_SEC = 5
JOB_TIMEOUT_SEC = 600  # 10 min max generation

# Rate limiting
MIN_SECONDS_BETWEEN_REQUESTS = 60
```

### 23.3 `dispatcher/queue/db.py` — Supabase wrapper

```python
# dispatcher/queue/db.py
import os
import uuid
from datetime import datetime
from supabase import create_client, Client

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]  # service_role key for dispatcher
_client: Client = create_client(URL, KEY)

def create_job(user_id: int, prompt: str, raw_prompt: str, model: str = "ltx-video") -> dict:
    job = {
        "user_id": user_id,
        "prompt": prompt,
        "raw_prompt": raw_prompt,
        "model": model,
        "status": "pending",
    }
    res = _client.table("jobs").insert(job).execute()
    return res.data[0]

def get_job_status(job_id: str) -> dict | None:
    res = _client.table("jobs").select("*").eq("id", job_id).single().execute()
    return res.data

def poll_completed_jobs() -> list[dict]:
    res = _client.table("jobs").select("*").eq("status", "complete").execute()
    return res.data

def mark_delivered(job_id: str, telegram_file_id: str = None):
    update = {"status": "delivered", "delivered_at": datetime.utcnow().isoformat()}
    if telegram_file_id:
        update["telegram_file_id"] = telegram_file_id
    _client.table("jobs").update(update).eq("id", job_id).execute()

# Worker-side (uses anon key or service_role)
def claim_job(worker_id: str, provider: str) -> dict | None:
    # Calls the Postgres function defined in schema.sql
    res = _client.rpc("claim_next_job", {"p_worker_id": worker_id, "p_provider": provider}).execute()
    return res.data[0] if res.data else None

def mark_complete(job_id: str, result_url: str):
    _client.rpc("mark_job_complete", {"p_job_id": job_id, "p_result_url": result_url}).execute()

def mark_failed(job_id: str, error: str):
    _client.rpc("mark_job_failed", {"p_job_id": job_id, "p_error": error}).execute()
```

### 23.4 `worker/models/wan_loader.py` — Wan 1.3B loader with Drive support

```python
# worker/models/wan_loader.py
import os
import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODELS_DIR = os.environ.get("MODELS_DIR", "./models")

def load_wan(model_name: str = "wan-1.3b"):
    model_path = os.path.join(MODELS_DIR, model_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found at {model_path}. Run download script first.")

    pipe = WanPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        variant="fp16",
    )
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    return pipe

def generate_wan(pipe, prompt: str, num_frames: int = 64, fps: int = 16, output_path: str = "output.mp4"):
    # Wan 1.3B native resolution: 832x480 at 16fps
    video = pipe(
        prompt=prompt,
        width=832,
        height=480,
        num_frames=num_frames,
        num_inference_steps=30,
        guidance_scale=5.0,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path
```

### 23.5 `worker/models/ltx_loader.py` — LTX-Video loader (fastest for T4)

```python
# worker/models/ltx_loader.py
import os
import torch
from diffusers import LTXPipeline
from diffusers.utils import export_to_video

MODELS_DIR = os.environ.get("MODELS_DIR", "./models")

def load_ltx(model_name: str = "ltx-video"):
    model_path = os.path.join(MODELS_DIR, model_name)
    pipe = LTXPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        variant="fp16",
    )
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    return pipe

def generate_ltx(pipe, prompt: str, num_frames: int = 96, fps: int = 24, output_path: str = "output.mp4"):
    # LTX: 512x320 at 24fps, ~4s = 96 frames
    video = pipe(
        prompt=prompt,
        width=512,
        height=320,
        num_frames=num_frames,
        num_inference_steps=30,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path
```

### 23.6 `worker/models/registry.py` — Dynamic model loading

```python
# worker/models/registry.py
import importlib
from shared.config import MODEL_CONFIGS

def get_loader(model_name: str):
    cfg = MODEL_CONFIGS.get(model_name)
    if not cfg:
        raise ValueError(f"Unknown model: {model_name}")
    module_path, func_name = cfg.loader.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)

def get_generate_fn(model_name: str):
    cfg = MODEL_CONFIGS.get(model_name)
    if not cfg:
        raise ValueError(f"Unknown model: {model_name}")
    if "wan" in model_name:
        from worker.models.wan_loader import generate_wan
        return generate_wan
    elif "ltx" in model_name:
        from worker.models.ltx_loader import generate_ltx
        return generate_ltx
    elif "cogvideo" in model_name:
        from worker.models.cogvideox_loader import generate_cogvideox
        return generate_cogvideox
    raise ValueError(f"No generate fn for {model_name}")
```

### 23.7 `worker/gpu_detect.py` — Auto-pick model for current GPU

```python
# worker/gpu_detect.py
import torch
from shared.config import MODEL_CONFIGS

def get_available_vram_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    props = torch.cuda.get_device_properties(0)
    total_gb = props.total_memory / (1024 ** 3)
    return round(total_gb, 1)

def gpu_name() -> str:
    if not torch.cuda.is_available():
        return "cpu"
    return torch.cuda.get_device_name(0)

def pick_model_for_vram(vram_gb: float) -> str:
    # Sort by min_vram descending, pick first that fits
    candidates = sorted(MODEL_CONFIGS.values(), key=lambda c: c.min_vram_gb, reverse=True)
    for cfg in candidates:
        if cfg.min_vram_gb <= vram_gb:
            return cfg.name
    raise RuntimeError(f"No model fits {vram_gb}GB VRAM. Smallest needs {min(c.min_vram_gb for c in MODEL_CONFIGS.values())}GB")

if __name__ == "__main__":
    vram = get_available_vram_gb()
    name = gpu_name()
    model = pick_model_for_vram(vram)
    print(f"GPU: {name} | VRAM: {vram} GB | Selected model: {model}")
```

### 23.8 `worker/worker.py` — Complete poll loop

```python
# worker/worker.py
import os
import sys
import time
import uuid
import argparse
import traceback
from dotenv import load_dotenv

load_dotenv()

# Ensure shared modules importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import MODEL_CONFIGS, POLL_INTERVAL_SEC
from worker.models.registry import get_loader, get_generate_fn
from worker.gpu_detect import get_available_vram_gb, pick_model_for_vram
from dispatcher.queue.db import claim_job, mark_complete, mark_failed
import gc
import torch

def cleanup_gpu():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["colab", "kaggle", "lightning", "paperspace", "sagemaker", "runpod"])
    parser.add_argument("--model", default="auto", help="Model name or 'auto'")
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args()

    worker_id = args.worker_id or f"{args.provider}-{uuid.uuid4().hex[:8]}"
    print(f"Worker {worker_id} starting on {args.provider}")

    # Detect GPU & pick model
    vram = get_available_vram_gb()
    model_name = pick_model_for_vram(vram) if args.model == "auto" else args.model
    cfg = MODEL_CONFIGS[model_name]
    print(f"VRAM: {vram}GB | Model: {model_name} | Max clip: {cfg.max_seconds}s @ {cfg.resolution[0]}x{cfg.resolution[1]}")

    # Load model once
    print("Loading model...")
    load_fn = get_loader(model_name)
    pipe = load_fn(model_name)
    generate_fn = get_generate_fn(model_name)
    print("Model loaded.")

    while True:
        try:
            job = claim_job(worker_id, args.provider)
            if not job:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            job_id = job["id"]
            prompt = job["prompt"]
            print(f"Claimed job {job_id}: {prompt[:80]}...")

            # Generate
            output_path = f"/tmp/{job_id}.mp4"
            num_frames = cfg.fps * min(cfg.max_seconds, 4)  # cap at 4s for safety
            generate_fn(pipe, prompt, num_frames=num_frames, fps=cfg.fps, output_path=output_path)

            # Upload to Supabase Storage
            from supabase import create_client
            supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
            with open(output_path, "rb") as f:
                supabase.storage.from_("videos").upload(f"{job_id}.mp4", f, {"content-type": "video/mp4"})
            result_url = supabase.storage.from_("videos").get_public_url(f"{job_id}.mp4")

            mark_complete(job_id, result_url)
            print(f"Job {job_id} complete -> {result_url}")

            os.remove(output_path)
            cleanup_gpu()

        except Exception as e:
            print(f"Job failed: {e}")
            traceback.print_exc()
            if 'job_id' in locals():
                mark_failed(job_id, str(e))
            cleanup_gpu()
            time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    main()
```

### 23.9 `worker/requirements.txt`

```text
# worker/requirements.txt
torch==2.4.0 --index-url https://download.pytorch.org/whl/cu124
torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu124
diffusers==0.34.0
transformers==4.46.2
accelerate==1.3.0
supabase==2.10.0
python-dotenv==1.0.1
huggingface-hub==0.26.2
safetensors==0.4.5
moviepy==1.0.3
imageio==2.35.1
imageio-ffmpeg==0.4.9
einops==0.8.0
```

### 23.10 `dispatcher/requirements.txt`

```text
# dispatcher/requirements.txt
python-telegram-bot==21.7
supabase==2.10.0
python-dotenv==1.0.1
groq==0.12.0
fastapi==0.115.0
uvicorn==0.30.6
httpx==0.28.1
```

### 23.11 `dispatcher/main.py` — Complete bot with webhook support

```python
# dispatcher/main.py
import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

load_dotenv()

from bot.handlers import generate_command, status_command, cancel_command
from bot.enhance import enhance_prompt
from queue.db import poll_completed_jobs, mark_delivered

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("telegram-video-bot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

async def delivery_loop(app: Application):
    while True:
        try:
            completed = poll_completed_jobs()
            for job in completed:
                try:
                    if job.get("telegram_file_id"):
                        await app.bot.send_video(
                            chat_id=job["user_id"],
                            video=job["telegram_file_id"],
                            caption=f"Done: {job['raw_prompt'][:100]}"
                        )
                    else:
                        msg = await app.bot.send_video(
                            chat_id=job["user_id"],
                            video=job["result_url"],
                            caption=f"Done: {job['raw_prompt'][:100]}"
                        )
                        mark_delivered(job["id"], msg.video.file_id)
                    mark_delivered(job["id"])
                except Exception as e:
                    logger.error(f"Delivery failed for job {job['id']}: {e}")
        except Exception as e:
            logger.error(f"Delivery loop error: {e}")
        await asyncio.sleep(5)

async def post_init(app: Application):
    asyncio.create_task(delivery_loop(app))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # For local dev: polling. For Fly.io/Render: webhook (see below)
    if os.environ.get("WEBHOOK_URL"):
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            url_path=TOKEN,
            webhook_url=f"{os.environ['WEBHOOK_URL']}/{TOKEN}",
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
```

### 23.12 `scripts/download_models.py` — Download to Drive or local

```python
# scripts/download_models.py
import os
import argparse
from huggingface_hub import snapshot_download
from shared.config import MODEL_CONFIGS

def download_model(name: str, dest_root: str, token: str = None):
    cfg = MODEL_CONFIGS.get(name)
    if not cfg:
        raise ValueError(f"Unknown model: {name}")
    dest = os.path.join(dest_root, name)
    os.makedirs(dest, exist_ok=True)
    print(f"Downloading {cfg.repo_id} -> {dest}")
    snapshot_download(
        repo_id=cfg.repo_id,
        local_dir=dest,
        token=token or os.environ.get("HF_TOKEN"),
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model"],
    )
    print(f"Done: {name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=list(MODEL_CONFIGS.keys()) + ["all", "auto"])
    parser.add_argument("--dest", default=os.environ.get("MODELS_DIR", "./models"))
    parser.add_argument("--vram", type=float, default=8.0)
    args = parser.parse_args()

    if args.model == "all":
        for name in MODEL_CONFIGS:
            download_model(name, args.dest)
    elif args.model == "auto":
        from worker.gpu_detect import get_available_vram_gb, pick_model_for_vram
        vram = get_available_vram_gb() or args.vram
        name = pick_model_for_vram(vram)
        download_model(name, args.dest)
    else:
        download_model(args.model, args.dest)
```

---

## Part 24 — Deploy Dispatcher to Fly.io (Free Tier, Always-On)

```bash
# 1. Install flyctl
curl -L https://fly.io/install.sh | sh

# 2. Login & launch
fly auth login
fly launch --name telegram-video-bot --region iad --no-deploy

# 3. Set secrets (never commit these)
fly secrets set TELEGRAM_BOT_TOKEN=123:ABC...
fly secrets set SUPABASE_URL=https://xxx.supabase.co
fly secrets set SUPABASE_KEY=eyJ...
fly secrets set HF_TOKEN=hf_...
fly secrets set GROQ_API_KEY=gsk_...
fly secrets set WEBHOOK_URL=https://telegram-video-bot.fly.dev

# 4. Deploy
fly deploy

# 5. Set Telegram webhook (run once)
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://telegram-video-bot.fly.dev/$TELEGRAM_BOT_TOKEN"
```

---

## Part 25 — Quick Test Checklist (Run in Order)

```bash
# 1. Supabase: run schema.sql in SQL Editor, create 'videos' bucket (private)
# 2. Local: test bot polling
cd dispatcher
cp .env.example .env  # fill in tokens
python main.py        # /generate a cat surfing -> should queue job

# 3. Download Wan 1.3B to Drive
#    Open Part 20 notebook in Colab, run cells 1-2, then run:
python scripts/download_models.py wan-1.3b --dest /content/drive/MyDrive/ai-video-models

# 4. Colab: run Part 20 notebook cells 3-4 (worker starts polling)
# 5. Telegram: /generate a cat surfing at sunset
# 6. Watch: job claimed -> video generated -> uploaded -> delivered to chat
```

---

**You now have every file needed to run this end-to-end.** The only things you must provide are the API tokens (Telegram, Supabase, HF, Groq) and ~30 minutes to run the checklist.
