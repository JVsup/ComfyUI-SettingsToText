import json
import time
from typing import Any, Dict, Tuple, List


def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


class SettingsToText:
    """
    Outputs a STRING built from the currently executing prompt (graph),
    so you can feed node settings into any text input during the same run.

    Features:
    - mode=summary: human-readable summary (checkpoint, diffusion model/UNet, AuraFlow sampling, LoRAs, sampler, size)
    - mode=raw: JSON dump of selected nodes from PROMPT
    - filters: node_ids (comma-separated) or class_types (comma-separated)
    - always_refresh: forces re-execution every run (cache-busting)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["summary", "raw"],),
                "always_refresh": ("BOOLEAN", {"default": True}),
                # Optional filters (leave empty for whole prompt)
                "node_ids": ("STRING", {"default": "", "multiline": False}),
                "class_types": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "prefix": ("STRING", {"default": "", "multiline": True}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Force re-execution on every queue/run when enabled
        if kwargs.get("always_refresh", True):
            return time.time_ns()
        return 0

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "run"
    CATEGORY = "utils"

    def run(
        self,
        mode: str,
        always_refresh: bool,
        node_ids: str,
        class_types: str,
        prefix: str = "",
        prompt: Dict[str, Any] = None,
        unique_id: str = None,
    ) -> Tuple[str]:
        prompt = prompt or {}

        # --- filtering base set ---
        ids = _split_csv(node_ids)
        types = _split_csv(class_types)

        if ids:
            base: Dict[str, Any] = {nid: prompt[nid] for nid in ids if nid in prompt}
        elif types:
            base = {nid: nd for nid, nd in prompt.items() if nd.get("class_type") in types}
        else:
            base = prompt

        # --- raw dump (debug / discover IDs & class_types) ---
        if mode == "raw":
            text = json.dumps(base, indent=2, ensure_ascii=False, sort_keys=True)
            if prefix.strip():
                text = prefix.rstrip() + "\n" + text
            return (text,)

        # --- summary ---
        lines: List[str] = []
        if prefix.strip():
            lines.append(prefix.rstrip())

        # checkpoint (classic SD checkpoints)
        for nid, nd in base.items():
            if nd.get("class_type") in ("CheckpointLoaderSimple", "CheckpointLoader"):
                ckpt = (nd.get("inputs") or {}).get("ckpt_name")
                lines.append(f"checkpoint: {ckpt}" if ckpt else "checkpoint: <missing ckpt_name>")
                break

        # diffusion model / UNet (Load Diffusion Model)
        # Common mapping: "Load Diffusion Model" => class_type "UNETLoader"
        # Typical inputs: unet_name, weight_dtype
        for nid, nd in base.items():
            if nd.get("class_type") == "UNETLoader":
                inp = nd.get("inputs") or {}
                unet_name = inp.get("unet_name") or inp.get("model_name") or inp.get("name")
                weight_dtype = inp.get("weight_dtype")
                if unet_name and weight_dtype is not None:
                    lines.append(f"diffusion_model: {unet_name} (dtype={weight_dtype})")
                elif unet_name:
                    lines.append(f"diffusion_model: {unet_name}")
                else:
                    lines.append(f"diffusion_model: <missing unet_name>")

        # AuraFlow sampling (ModelSamplingAuraFlow)
        # Typical inputs: model (link), shift (float)
        for nid, nd in base.items():
            if nd.get("class_type") == "ModelSamplingAuraFlow":
                inp = nd.get("inputs") or {}
                shift = inp.get("shift")
                lines.append(
                    f"auraflow_sampling: shift={shift}" if shift is not None
                    else f"auraflow_sampling: shift=<missing>"
                )

        # LoRAs (all)
        for nid, nd in base.items():
            if nd.get("class_type") in ("LoraLoader", "LoraLoaderModelOnly", "LoraLoaderModelAndCLIP"):
                inp = nd.get("inputs") or {}
                name = inp.get("lora_name")
                sm = inp.get("strength_model")
                sc = inp.get("strength_clip", sm)
                if name:
                    lines.append(f"lora: {name} (model={sm}, clip={sc})")
                else:
                    lines.append(f"lora: <missing lora_name>")

        # Sampler (first KSampler)
        for nid, nd in base.items():
            if nd.get("class_type") == "KSampler":
                inp = nd.get("inputs") or {}
                lines.append(
                    "sampler: {sampler}/{scheduler}, steps={steps}, cfg={cfg}, denoise={denoise}, seed={seed}".format(
                        nid=nid,
                        sampler=inp.get("sampler_name"),
                        scheduler=inp.get("scheduler"),
                        steps=inp.get("steps"),
                        cfg=inp.get("cfg"),
                        denoise=inp.get("denoise"),
                        seed=inp.get("seed"),
                    )
                )
                break

        # Size (first EmptyLatentImage)
        for nid, nd in base.items():
            if nd.get("class_type") == "EmptyLatentImage":
                inp = nd.get("inputs") or {}
                w = inp.get("width")
                h = inp.get("height")
                b = inp.get("batch_size")
                lines.append(f"size: {w}x{h}, batch={b}")
                break

        if not lines:
            lines.append("No settings found (prompt empty or filters too strict).")

        return ("\n".join(lines),)


# Internal node id -> class
NODE_CLASS_MAPPINGS = {
    "SettingsToText": SettingsToText,
}

# What you see in the ComfyUI node menu
NODE_DISPLAY_NAME_MAPPINGS = {
    "SettingsToText": "Settings to text",
}
