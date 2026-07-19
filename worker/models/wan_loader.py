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