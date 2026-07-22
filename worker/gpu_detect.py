import os
import sys
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    if vram_gb <= 0:
        raise RuntimeError("No GPU detected (0 GB VRAM). A CUDA-capable GPU is required.")
    candidates = sorted(MODEL_CONFIGS.values(), key=lambda c: c.min_vram_gb, reverse=True)
    for cfg in candidates:
        if cfg.min_vram_gb <= vram_gb:
            return cfg.name
    smallest = min(c.min_vram_gb for c in MODEL_CONFIGS.values())
    raise RuntimeError(f"No model fits {vram_gb}GB VRAM. Smallest needs {smallest}GB")


if __name__ == "__main__":
    vram = get_available_vram_gb()
    name = gpu_name()
    print(f"GPU: {name} | VRAM: {vram} GB")
    if vram <= 0:
        print("No GPU detected. Make sure Colab runtime is set to GPU (Runtime → Change runtime type → T4 GPU).")
    else:
        model = pick_model_for_vram(vram)
        print(f"Selected model: {model}")