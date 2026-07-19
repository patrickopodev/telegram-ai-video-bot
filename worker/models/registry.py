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