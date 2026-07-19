import os
import sys
import time
import uuid
import argparse
import traceback
from dotenv import load_dotenv

load_dotenv()

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
    parser.add_argument("--model", default="auto")
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args()

    worker_id = args.worker_id or f"{args.provider}-{uuid.uuid4().hex[:8]}"
    print(f"Worker {worker_id} starting on {args.provider}")

    vram = get_available_vram_gb()
    model_name = pick_model_for_vram(vram) if args.model == "auto" else args.model
    cfg = MODEL_CONFIGS[model_name]
    print(f"VRAM: {vram}GB | Model: {model_name} | Max clip: {cfg.max_seconds}s @ {cfg.resolution[0]}x{cfg.resolution[1]}")

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

            output_path = f"/tmp/{job_id}.mp4"
            num_frames = cfg.fps * min(cfg.max_seconds, 4)
            generate_fn(pipe, prompt, num_frames=num_frames, fps=cfg.fps, output_path=output_path)

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