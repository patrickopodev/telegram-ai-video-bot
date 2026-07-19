import os
import torch
from diffusers import CogVideoXPipeline
from diffusers.utils import export_to_video

MODEL_PATH = os.environ.get("MODELS_DIR", "./models")


def load_cogvideox(model_name: str = "cogvideox-2b"):
    model_path = os.path.join(MODEL_PATH, model_name)
    pipe = CogVideoXPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    return pipe


def generate_cogvideox(pipe, prompt: str, num_frames: int = 49, fps: int = 8, output_path: str = "out.mp4", **kwargs):
    video = pipe(
        prompt=prompt,
        num_frames=num_frames,
        num_inference_steps=50,
        guidance_scale=6,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path