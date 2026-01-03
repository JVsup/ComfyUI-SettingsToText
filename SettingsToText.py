import json
import nodes  # Import ComfyUI nodes registry

class SettingsToText:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "settings_json": ("STRING", {"default": "[]", "multiline": False}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("Result String",)
    FUNCTION = "process"
    CATEGORY = "utils"
    OUTPUT_NODE = True

    def validate_inputs(self, input_types):
        return True

    @classmethod
    def IS_CHANGED(s, **kwargs):
        return float("nan")

    def process(self, settings_json, unique_id, prompt, extra_pnginfo=None):
        try:
            selected_items = json.loads(settings_json)
        except:
            return ("Error: Invalid JSON selection",)

        if not isinstance(selected_items, list) or len(selected_items) == 0:
            return ("No parameters selected",)

        grouped_nodes = {}
        for item in selected_items:
            node_id = str(item.get("id"))
            if node_id not in grouped_nodes:
                grouped_nodes[node_id] = {
                    "title": item.get("title", f"Node #{node_id}"),
                    "params": []
                }
            grouped_nodes[node_id]["params"].append(item.get("param"))

        def to_number(val):
            try:
                if isinstance(val, str) and "." in val: return float(val)
                return int(val)
            except: return None

        # --- DATA PREPARATION ---
        workflow_nodes_map = {}
        if extra_pnginfo and 'workflow' in extra_pnginfo:
            for node in extra_pnginfo['workflow'].get('nodes', []):
                workflow_nodes_map[str(node['id'])] = node

        def get_node_data_fallback(node_id):
            # A) Active Graph
            if node_id in prompt:
                return prompt[node_id], True

            # B) Inactive/Subgraph
            if node_id in workflow_nodes_map:
                wf_node = workflow_nodes_map[node_id]
                class_type = wf_node.get('type')
                
                # Try to get a readable title from meta
                title = wf_node.get('title')
                if not title and 'properties' in wf_node:
                    title = wf_node['properties'].get('Node name for S&R')

                inputs = {}
                
                # 1. Map Links
                if 'inputs' in wf_node:
                    for inp in wf_node['inputs']:
                        if 'link' in inp and inp['link'] is not None:
                            inputs[inp['name']] = ["Unknown", 0]
                            links = extra_pnginfo['workflow'].get('links', [])
                            for l in links:
                                if l[0] == inp['link']:
                                    inputs[inp['name']] = [str(l[1]), l[2]]
                                    break

                # 2. Raw Widgets for Fuzzy Lookup
                if 'widgets_values' in wf_node:
                    inputs['__raw_widgets__'] = wf_node['widgets_values']

                return {
                    "class_type": class_type,
                    "title_hint": title,
                    "inputs": inputs
                }, False
            
            return None, False

        # --- FUZZY LOOKUP ---
        def fuzzy_widget_lookup(raw_values, param_name):
            if not raw_values or not isinstance(raw_values, list): return None
            param_lower = param_name.lower()

            # 1. Models/Files
            if any(x in param_lower for x in ["name", "model", "clip", "lora", "vae"]):
                for val in raw_values:
                    if isinstance(val, str) and any(ext in val for ext in [".safetensors", ".ckpt", ".pt", ".bin"]):
                        return val
            
            # 2. Seeds / Steps (Ints)
            if "seed" in param_lower or "step" in param_lower:
                for val in raw_values:
                    if isinstance(val, (int, float)) and val > 0: return val
                    if isinstance(val, str) and val.isdigit(): return val # legacy string seeds
            
            # 3. Floats (Strength, cfg)
            if any(x in param_lower for x in ["strength", "denoise", "scale", "cfg", "weight"]):
                 for val in raw_values:
                    if isinstance(val, (int, float)): return val

            # 4. Text/Prompts
            if "text" in param_lower or "prompt" in param_lower:
                longest = ""
                for val in raw_values:
                    if isinstance(val, str) and len(val) > len(longest): longest = val
                if longest: return longest

            # 5. Booleans
            if "bool" in param_lower:
                for val in raw_values:
                    if isinstance(val, bool) or str(val).lower() in ["true", "false", "enable", "disable"]:
                        return val

            return None

        # --- TRAVERSAL ---
        def find_source_value(current_node_id, input_name, visited=None, recursion_depth=0):
            if visited is None: visited = set()
            if current_node_id in visited or recursion_depth > 20: return "..."
            visited.add(current_node_id)

            node_data, is_active = get_node_data_fallback(current_node_id)
            if not node_data: return "[Node missing]"

            inputs = node_data.get("inputs", {})
            class_type = node_data.get("class_type", "Unknown")

            # Resolve key
            target_key = input_name
            if input_name and ":" in input_name:
                target_key = input_name.split(":")[-1].strip()

            val = None
            if target_key and target_key in inputs:
                val = inputs[target_key]
            
            # Fallback keys
            if val is None:
                if "value" in inputs: val = inputs["value"]
                elif "text" in inputs: val = inputs["text"]
                elif "Reroute" in class_type and len(inputs) > 0 and "__raw" not in list(inputs.keys())[0]:
                     val = list(inputs.values())[0]

            # Emergency Fuzzy Lookup
            if val is None and "__raw_widgets__" in inputs:
                found = fuzzy_widget_lookup(inputs["__raw_widgets__"], target_key or input_name)
                if found is not None: return str(found)
                # If checking for 'name' and we have widgets, take the first one (common for loaders)
                if target_key and "name" in target_key and len(inputs["__raw_widgets__"]) > 0:
                    return str(inputs["__raw_widgets__"][0])

            if val is None:
                calc = try_calculate_math(current_node_id, input_name, visited, recursion_depth)
                if calc is not None: return str(calc)
                return "[Param Not Found]"

            # Handle Value
            if not isinstance(val, list) or len(val) != 2:
                return str(val)

            # Handle Link
            source_id = str(val[0])
            
            # CLEANUP: If source_id is a UUID (Group Port)
            if len(source_id) > 25 and "-" in source_id:
                return f"[Shared/Group Port]"

            if source_id == "Unknown": return "[Link (Inactive)]"

            # Check math
            calc = try_calculate_math(source_id, input_name, visited, recursion_depth + 1)
            if calc is not None: return str(calc)

            source_data, _ = get_node_data_fallback(source_id)
            if not source_data: return f"[Link to #{source_id}]"

            source_inputs = source_data.get("inputs", {})
            
            # Traversal
            lookup_names = [target_key]
            if target_key != input_name: lookup_names.append(input_name)
            
            for lname in lookup_names:
                if lname in source_inputs:
                    return find_source_value(source_id, lname, visited, recursion_depth + 1)

            common = ["value", "text", "int", "float", "ckpt_name", "lora_name", "vae_name", "clip_name", "unet_name", "seed"]
            for key in common:
                if key in source_inputs:
                    return find_source_value(source_id, key, visited, recursion_depth + 1)
            
            if "Reroute" in source_data.get("class_type", ""):
                 for k in source_inputs:
                     if k != "__raw_widgets__":
                         return find_source_value(source_id, k, visited, recursion_depth + 1)

            src_cls = source_data.get("class_type", "Unknown")
            src_title = source_data.get("title_hint", src_cls)

            # CLEANUP: If class type looks like UUID, make it readable
            if len(src_cls) > 25 and "-" in src_cls:
                src_cls = "Subgraph/Group"
                if src_title == src_cls: # If title wasn't found
                    src_title = "Group Node"

            # Use Title if available and cleaner
            display_name = src_title if src_title and src_title != "Unknown" else src_cls
            
            return f"[From {display_name} #{source_id}]"

        # --- MATH ---
        def try_calculate_math(node_id, param_name, visited, depth):
            node, _ = get_node_data_fallback(node_id)
            if not node: return None
            ctype = node.get("class_type", "")
            inputs = node.get("inputs", {})

            def get_num(key):
                if key in inputs:
                    raw = find_source_value(node_id, key, visited.copy(), depth + 1)
                    return to_number(raw)
                return None

            if "Multiply" in ctype or "Resolution" in ctype:
                mult = get_num("multiplier")
                if mult is None: mult = 1.0
                req = param_name
                if req and ":" in req: req = req.split(":")[-1].strip()
                if req == "width":
                    w = get_num("width")
                    return int(w * mult) if w is not None else None
                if req == "height":
                    h = get_num("height")
                    return int(h * mult) if h is not None else None
            return None

        # Output
        output_lines = []
        sorted_ids = sorted(grouped_nodes.keys(), key=lambda x: int(x) if x.isdigit() else x)

        for node_id in sorted_ids:
            data = grouped_nodes[node_id]
            node_title = data["title"]
            params = data["params"]
            node_data, is_active = get_node_data_fallback(node_id)
            
            status_suffix = "" if is_active else " (Inactive/Subgraph)"
            output_lines.append(f"{node_title} - #{node_id}{status_suffix}")

            if node_data:
                for param in params:
                    final_value = find_source_value(node_id, param)
                    output_lines.append(f"{param}: {final_value}")
            else:
                output_lines.append("(Node missing - deleted?)")

            output_lines.append("---")

        if output_lines and output_lines[-1] == "---":
            output_lines.pop()

        return ("\n".join(output_lines),)