import os
import argparse
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
    "wan-2.2-ti2v-5b": {
        "repo_id": "Wan-AI/Wan2.2-TI2V-5B",
        "min_vram_gb": 24,
    },
    "wan-dancer-14b": {
        "repo_id": "Wan-AI/Wan-Dancer-14B",
        "min_vram_gb": 48,
    },
    "hunyuanvideo": {
        "repo_id": "tencent/HunyuanVideo",
        "min_vram_gb": 45,
    },
    "mochi-1": {
        "repo_id": "genmo/mochi-1-preview",
        "min_vram_gb": 40,
    },
}


def download_model(name: str, dest_dir: str | None = None, token: str | None = None):
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model '{name}'. Options: {list(MODEL_REGISTRY)}")
    cfg = MODEL_REGISTRY[name]
    dest = dest_dir or os.path.join(MODELS_DIR, name)
    print(f"Downloading {name} ({cfg['repo_id']}) -> {dest}")
    snapshot_download(
        repo_id=cfg["repo_id"],
        local_dir=dest,
        token=token or os.environ.get("HF_TOKEN"),
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model", "*.pth"],
    )
    print(f"Done: {name}")


def pick_model_for_vram(available_gb: float) -> str:
    candidates = sorted(
        MODEL_REGISTRY.items(), key=lambda kv: kv[1]["min_vram_gb"], reverse=True
    )
    for name, cfg in candidates:
        if cfg["min_vram_gb"] <= available_gb:
            return name
    raise RuntimeError("No model fits the available VRAM")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=list(MODEL_REGISTRY) + ["auto"])
    parser.add_argument("--vram", type=float, default=8.0, help="Available VRAM in GB (for 'auto')")
    parser.add_argument("--dest", help="Custom destination directory")
    args = parser.parse_args()

    name = pick_model_for_vram(args.vram) if args.model == "auto" else args.model
    download_model(name, dest_dir=args.dest)