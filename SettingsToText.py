import json
import nodes  # Import ComfyUI nodes registry to find widget names

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
                "extra_pnginfo": "EXTRA_PNGINFO",  # Access full workflow data
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
        # 1. Parsing JSON
        try:
            selected_items = json.loads(settings_json)
        except:
            return ("Error: Invalid JSON selection",)

        if not isinstance(selected_items, list) or len(selected_items) == 0:
            return ("No parameters selected",)

        # 2. Grouping
        grouped_nodes = {}
        for item in selected_items:
            node_id = str(item.get("id"))
            if node_id not in grouped_nodes:
                grouped_nodes[node_id] = {
                    "title": item.get("title", f"Node #{node_id}"),
                    "params": []
                }
            grouped_nodes[node_id]["params"].append(item.get("param"))

        # --- Helper: Convert to number ---
        def to_number(val):
            try:
                if isinstance(val, str) and "." in val: return float(val)
                return int(val)
            except: return None

        # --- FALLBACK MECHANISM FOR MISSING NODES ---
        # If a node is disconnected or in a subgraph, it might be missing from 'prompt'.
        # We reconstruct it from 'extra_pnginfo' (the raw workflow).
        
        workflow_nodes_map = {}
        if extra_pnginfo and 'workflow' in extra_pnginfo:
            for node in extra_pnginfo['workflow'].get('nodes', []):
                workflow_nodes_map[str(node['id'])] = node

        def get_node_data_fallback(node_id):
            # If node is in the execution graph (prompt), return it directly
            if node_id in prompt:
                return prompt[node_id], True # True = is_active

            # Fallback to full workflow data
            if node_id in workflow_nodes_map:
                wf_node = workflow_nodes_map[node_id]
                class_type = wf_node.get('type')
                
                # Reconstruct inputs dictionary
                inputs = {}
                
                # 1. Map Links (inputs)
                if 'inputs' in wf_node:
                    for inp in wf_node['inputs']:
                        if 'link' in inp and inp['link'] is not None:
                            # In workflow, links are IDs. We need to find [NodeID, Slot]
                            # This is complex to reverse fully without link map, 
                            # but usually we just want to know it's a link.
                            # For simple display, we assume the link ID connects somewhere.
                            # To be precise, we need the link list from workflow.
                            inputs[inp['name']] = ["Unknown", 0] # Placeholder for link traversal logic
                            
                            # Try to find the link source if possible (from workflow links)
                            links = extra_pnginfo['workflow'].get('links', [])
                            for l in links:
                                # Link structure: [id, source_id, source_slot, target_id, target_slot, type]
                                if l[0] == inp['link']:
                                    inputs[inp['name']] = [str(l[1]), l[2]]
                                    break

                # 2. Map Widgets (values)
                # Workflow stores values as a list. We need to match them to names via Class Def.
                if 'widgets_values' in wf_node and class_type in nodes.NODE_CLASS_MAPPINGS:
                    node_cls = nodes.NODE_CLASS_MAPPINGS[class_type]
                    input_config = node_cls.INPUT_TYPES()
                    
                    # Gather all expected widget names in order
                    widget_names = []
                    # Required
                    for name in input_config.get('required', {}):
                        # Skip if it's a connection point (not a value widget)
                        # ComfyUI heuristic: if config is list/tuple, it's usually a widget (COMBO)
                        # or if it's "INT", "FLOAT", "STRING". 
                        # Simple Input (connections) are usually ignored in widgets_values
                        widget_names.append(name)
                    # Optional
                    for name in input_config.get('optional', {}):
                        widget_names.append(name)

                    # Assign values
                    vals = wf_node['widgets_values']
                    # Use simpler list because optional widgets might be tricky
                    # This is a best-effort mapping.
                    for i, val in enumerate(vals):
                        if i < len(widget_names):
                            inputs[widget_names[i]] = val

                return {
                    "class_type": class_type,
                    "inputs": inputs
                }, False # False = is_fallback
            
            return None, False

        # --- RECURSIVE TRAVERSAL ---
        def find_source_value(current_node_id, input_name, visited=None, recursion_depth=0):
            if visited is None: visited = set()
            if current_node_id in visited or recursion_depth > 20: return "..."
            visited.add(current_node_id)

            # Get node data (either from prompt or fallback)
            node_data, is_active = get_node_data_fallback(current_node_id)

            if not node_data: return "[Node missing]"

            inputs = node_data.get("inputs", {})
            class_type = node_data.get("class_type", "Unknown")

            # A) Math Simulation
            target_key = input_name
            if input_name and input_name not in inputs:
                if "value" in inputs: target_key = "value"
                elif "text" in inputs: target_key = "text"
                elif "int" in inputs: target_key = "int"
                elif "float" in inputs: target_key = "float"
                elif "Reroute" in class_type and len(inputs) > 0:
                    target_key = list(inputs.keys())[0]
                else:
                    calc = try_calculate_math(current_node_id, input_name, visited, recursion_depth)
                    if calc is not None: return str(calc)
                    return "[Param Not Found]"

            val = inputs[target_key] if target_key else None

            # B) Direct Value
            if not isinstance(val, list) or len(val) != 2:
                return str(val)

            # C) Link -> Traversal
            source_id = str(val[0])
            if source_id == "Unknown": return "[Link (Inactive)]"

            calc = try_calculate_math(source_id, input_name, visited, recursion_depth + 1)
            if calc is not None: return str(calc)

            source_data, _ = get_node_data_fallback(source_id)
            if not source_data: return f"[Link to #{source_id}]"

            source_inputs = source_data.get("inputs", {})
            
            if target_key in source_inputs:
                return find_source_value(source_id, target_key, visited, recursion_depth + 1)
            
            common = ["value", "text", "int", "float", "ckpt_name", "lora_name"]
            for key in common:
                if key in source_inputs:
                    return find_source_value(source_id, key, visited, recursion_depth + 1)
            
            if "Reroute" in source_data.get("class_type", "") and len(source_inputs) > 0:
                 first = list(source_inputs.keys())[0]
                 return find_source_value(source_id, first, visited, recursion_depth + 1)

            src_cls = source_data.get("class_type", "Unknown")
            return f"[From {src_cls} #{source_id}]"

        # --- MATH SIMULATOR ---
        def try_calculate_math(node_id, param_name, visited, depth):
            node, _ = get_node_data_fallback(node_id)
            if not node: return None
            
            ctype = node.get("class_type", "")
            inputs = node.get("inputs", {})

            def get_num(key):
                if key not in inputs: return None
                raw = find_source_value(node_id, key, visited.copy(), depth + 1)
                return to_number(raw)

            if "Multiply" in ctype or "Resolution" in ctype:
                mult = get_num("multiplier")
                if mult is None: mult = 1.0
                if param_name == "width":
                    w = get_num("width")
                    return int(w * mult) if w is not None else None
                if param_name == "height":
                    h = get_num("height")
                    return int(h * mult) if h is not None else None

            if "Math" in ctype:
                a = get_num("a") or get_num("value_a")
                b = get_num("b") or get_num("value_b")
                if a is not None and b is not None:
                    op = ctype.lower()
                    if "multiply" in op: return a * b
                    if "divide" in op and b != 0: return a / b
                    if "add" in op: return a + b
                    if "subtract" in op: return a - b
            return None

        # 4. Output Generation
        output_lines = []
        sorted_ids = sorted(grouped_nodes.keys(), key=lambda x: int(x) if x.isdigit() else x)

        for node_id in sorted_ids:
            data = grouped_nodes[node_id]
            node_title = data["title"]
            params = data["params"]

            # Check if node exists (active or fallback)
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