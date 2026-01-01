import json
import time
from typing import Any, Dict, Tuple, List, Optional, Set


def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool))


def _is_link(v: Any) -> bool:
    # ComfyUI link is typically [node_id, output_index]
    return (
        isinstance(v, (list, tuple))
        and len(v) == 2
        and isinstance(v[0], (str, int))
        and isinstance(v[1], int)
    )


def _safe_bool(x: Any) -> Optional[bool]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return x
        if isinstance(x, (int, float)):
            return bool(int(x))
        s = str(x).strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off", ""):
            return False
        return None
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return float(int(x))
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(x)
        s = str(x).strip()
        if not s:
            return None
        f = float(s)  # allow "2.0"
        return int(f)
    except Exception:
        return None


def _eval_math_int(op: str, a: int, b: int) -> Optional[int]:
    try:
        op = (op or "").strip().lower()
        if op in ("add", "+"):
            return a + b
        if op in ("sub", "subtract", "-"):
            return a - b
        if op in ("mul", "multiply", "*"):
            return a * b
        if op in ("div", "divide", "/"):
            return int(a / b) if b != 0 else None
        if op in ("mod", "%"):
            return a % b if b != 0 else None
        if op in ("min",):
            return min(a, b)
        if op in ("max",):
            return max(a, b)
        return None
    except Exception:
        return None


def _resolve_node_output_scalar(
    nid: str,
    nd: Dict[str, Any],
    prompt: Dict[str, Any],
    *,
    max_depth: int,
    depth: int,
    visited: Set[str],
) -> Any:
    """
    Best-effort evaluation of a linked node's output to a scalar (or scalar-like).
    If it cannot be evaluated, returns None.
    """
    class_type = (nd.get("class_type") or "").strip()
    inputs = nd.get("inputs") or {}
    if not isinstance(inputs, dict):
        return None

    # Primitive / constant-like nodes
    if class_type.startswith("Primitive") and "value" in inputs:
        v = inputs.get("value")
        if _is_scalar(v):
            return v
        return _resolve_value(v, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)

    # Easy-Use nodes: "easy int" etc.
    if class_type in ("easy int", "easy float", "easy boolean", "easy string") and "value" in inputs:
        v = inputs.get("value")
        if _is_scalar(v):
            return v
        return _resolve_value(v, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)

    # easy mathInt
    if class_type == "easy mathInt":
        a_raw = inputs.get("a")
        b_raw = inputs.get("b")
        op = inputs.get("operation")

        a_val = _resolve_value(a_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)
        b_val = _resolve_value(b_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)

        a_int = _safe_int(a_val)
        b_int = _safe_int(b_val)
        if a_int is None or b_int is None:
            return None

        return _eval_math_int(str(op), a_int, b_int)

    # easy textSwitch (if input==1 -> text1 else text2)
    if class_type == "easy textSwitch" or "textSwitch" in class_type:
        sel_raw = inputs.get("input")
        t1 = inputs.get("text1")
        t2 = inputs.get("text2")

        sel_val = _resolve_value(sel_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)
        sel_int = _safe_int(sel_val)

        chosen = t1 if sel_int == 1 else t2
        return _resolve_value(chosen, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)

    # Crystools: Switch any [Crystools]
    # Inputs: boolean, on_true, on_false
    if class_type == "Switch any [Crystools]" or ("Switch any" in class_type and "Crystools" in class_type):
        b_raw = inputs.get("boolean")
        on_t = inputs.get("on_true")
        on_f = inputs.get("on_false")

        b_val = _resolve_value(b_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)
        b = _safe_bool(b_val)
        if b is None:
            return None

        chosen = on_t if b else on_f
        return _resolve_value(chosen, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)

    # String conversions
    if class_type == "StringToInt":
        s_raw = inputs.get("string")
        s_val = _resolve_value(s_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)
        return _safe_int(s_val)

    if class_type == "String to Float":
        s_raw = inputs.get("String")  # capital S (as in your raw output)
        s_val = _resolve_value(s_raw, prompt, max_depth=max_depth, depth=depth + 1, visited=visited)
        return _safe_float(s_val)

    return None


def _resolve_value(
    v: Any,
    prompt: Dict[str, Any],
    *,
    max_depth: int = 24,
    depth: int = 0,
    visited: Optional[Set[str]] = None,
) -> Any:
    """
    Resolve linked values like [node_id, out_index] into a scalar, if possible.
    If not resolvable, returns a descriptive placeholder (keeps IDs for debugging).
    """
    if visited is None:
        visited = set()

    if not _is_link(v):
        return v

    nid_raw, out_idx = v[0], v[1]
    nid = str(nid_raw)

    if depth >= max_depth or nid in visited:
        return f"<link:{nid}:{out_idx}>"

    nd = prompt.get(nid)
    if not isinstance(nd, dict):
        return f"<link:{nid}:{out_idx}>"

    class_type = nd.get("class_type") or "?"
    visited.add(nid)

    evaluated = _resolve_node_output_scalar(
        nid, nd, prompt, max_depth=max_depth, depth=depth, visited=visited
    )
    if evaluated is not None:
        return evaluated

    return f"<link:{nid}:{out_idx} ({class_type})>"


def _fmt(v: Any, prompt: Dict[str, Any], resolve_links: bool) -> str:
    if resolve_links:
        v = _resolve_value(v, prompt)

    if v is None:
        return "<missing>"

    if _is_scalar(v):
        return str(v)

    if _is_link(v):
        return f"<link:{v[0]}:{v[1]}>"

    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def _label(base: str, idx: int, show_node_ids: bool, nid: Optional[str] = None) -> str:
    """
    If show_node_ids=True and nid is provided -> base[nid]
    Else if idx==1 -> base
    Else -> base#idx
    """
    if show_node_ids and nid is not None:
        return f"{base}[{nid}]"
    return base if idx == 1 else f"{base}#{idx}"


class SettingsToText:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["summary", "raw"],),
                "always_refresh": ("BOOLEAN", {"default": True}),
                "resolve_links": ("BOOLEAN", {"default": True}),
                "show_node_ids": ("BOOLEAN", {"default": False}),
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
        resolve_links: bool,
        show_node_ids: bool,
        node_ids: str,
        class_types: str,
        prefix: str = "",
        prompt: Dict[str, Any] = None,
        unique_id: str = None,
    ) -> Tuple[str]:
        prompt = prompt or {}

        ids = _split_csv(node_ids)
        types = _split_csv(class_types)

        if ids:
            base: Dict[str, Any] = {nid: prompt[nid] for nid in ids if nid in prompt}
        elif types:
            base = {nid: nd for nid, nd in prompt.items() if nd.get("class_type") in types}
        else:
            base = prompt

        if mode == "raw":
            text = json.dumps(base, indent=2, ensure_ascii=False, sort_keys=True)
            if prefix.strip():
                text = prefix.rstrip() + "\n" + text
            return (text,)

        lines: List[str] = []
        if prefix.strip():
            lines.append(prefix.rstrip())

        # Diffusion model / UNet (Load Diffusion Model)
        unet_i = 0
        for nid, nd in base.items():
            if nd.get("class_type") == "UNETLoader":
                unet_i += 1
                inp = nd.get("inputs") or {}
                unet_name = inp.get("unet_name") or inp.get("model_name") or inp.get("name")
                weight_dtype = inp.get("weight_dtype")

                head = _label("diffusion_model", unet_i, show_node_ids, nid if show_node_ids else None)
                if unet_name is None:
                    lines.append(f"{head}: <missing unet_name>")
                else:
                    if weight_dtype is not None:
                        lines.append(
                            f"{head}: {_fmt(unet_name, prompt, resolve_links)} (dtype={_fmt(weight_dtype, prompt, resolve_links)})"
                        )
                    else:
                        lines.append(f"{head}: {_fmt(unet_name, prompt, resolve_links)}")

        # AuraFlow sampling (ModelSamplingAuraFlow)
        aura_i = 0
        for nid, nd in base.items():
            if nd.get("class_type") == "ModelSamplingAuraFlow":
                aura_i += 1
                inp = nd.get("inputs") or {}
                shift = inp.get("shift")

                head = _label("auraflow_sampling", aura_i, show_node_ids, nid if show_node_ids else None)
                if shift is None:
                    lines.append(f"{head}: shift=<missing>")
                else:
                    lines.append(f"{head}: shift={_fmt(shift, prompt, resolve_links)}")

        # LoRAs
        lora_i = 0
        for nid, nd in base.items():
            if nd.get("class_type") in ("LoraLoader", "LoraLoaderModelOnly", "LoraLoaderModelAndCLIP"):
                lora_i += 1
                inp = nd.get("inputs") or {}
                name = inp.get("lora_name")
                sm = inp.get("strength_model")
                sc = inp.get("strength_clip", sm)

                head = _label("lora", lora_i, show_node_ids, nid if show_node_ids else None)
                if name is None:
                    lines.append(f"{head}: <missing lora_name>")
                else:
                    lines.append(
                        f"{head}: {_fmt(name, prompt, resolve_links)} "
                        f"(model={_fmt(sm, prompt, resolve_links)}, clip={_fmt(sc, prompt, resolve_links)})"
                    )

        # Sampler (first KSampler)
        for nid, nd in base.items():
            if nd.get("class_type") == "KSampler":
                inp = nd.get("inputs") or {}
                sampler_name = inp.get("sampler_name")
                scheduler = inp.get("scheduler")
                steps = inp.get("steps")
                cfg = inp.get("cfg")
                denoise = inp.get("denoise")
                seed = inp.get("seed")

                head = "sampler" if not show_node_ids else f"sampler[{nid}]"
                lines.append(
                    f"{head}: "
                    f"{_fmt(sampler_name, prompt, resolve_links)}/{_fmt(scheduler, prompt, resolve_links)}, "
                    f"steps={_fmt(steps, prompt, resolve_links)}, "
                    f"cfg={_fmt(cfg, prompt, resolve_links)}, "
                    f"denoise={_fmt(denoise, prompt, resolve_links)}, "
                    f"seed={_fmt(seed, prompt, resolve_links)}"
                )
                break

        # Size (first EmptyLatentImage)
        for nid, nd in base.items():
            if nd.get("class_type") == "EmptyLatentImage":
                inp = nd.get("inputs") or {}
                w = inp.get("width")
                h = inp.get("height")
                b = inp.get("batch_size")

                head = "size" if not show_node_ids else f"size[{nid}]"
                lines.append(
                    f"{head}: {_fmt(w, prompt, resolve_links)}x{_fmt(h, prompt, resolve_links)}, "
                    f"batch={_fmt(b, prompt, resolve_links)}"
                )
                break

        if not lines:
            lines.append("No settings found (prompt empty or filters too strict).")

        return ("\n".join(lines),)


NODE_CLASS_MAPPINGS = {
    "SettingsToText": SettingsToText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SettingsToText": "Settings to text",
}
