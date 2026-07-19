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