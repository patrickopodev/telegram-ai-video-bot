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
    loader: str


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

POLL_INTERVAL_SEC = 5
JOB_TIMEOUT_SEC = 600
MIN_SECONDS_BETWEEN_REQUESTS = 60