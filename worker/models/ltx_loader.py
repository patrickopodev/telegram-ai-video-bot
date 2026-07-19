import torch
from diffusers import LTXPipeline
from diffusers.utils import export_to_video

MODEL_PATH = os.environ.get("MODELS_DIR", "./models")


def load_ltx(model_name: str = "ltx-video"):
    import os
    model_path = os.path.join(MODEL_PATH, model_name)
    pipe = LTXPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
    pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    return pipe


def generate_ltx(pipe, prompt: str, num_frames: int = 65, fps: int = 24, output_path: str = "out.mp4", **kwargs):
    video = pipe(
        prompt=prompt,
        width=512,
        height=320,
        num_frames=num_frames,
        num_inference_steps=30,
    ).frames[0]
    export_to_video(video, output_path, fps=fps)
    return output_path