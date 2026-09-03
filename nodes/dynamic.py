"""
Dynamic node generation for Modly extensions.

Reads manifest.json files from the local extensions directory
(configured in addon preferences) and dynamically creates Blender
node classes for each model node defined in those manifests.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import bpy
from .inputs import ModlyNodeBase

log = logging.getLogger(__name__)

_dynamic_classes = []


class ModlyDynamicNodeBase(ModlyNodeBase):
    """Base class for all dynamically generated extension nodes."""

    bl_idname = ""
    bl_label = ""
    _model_id = ""
    _inputs_schema = []
    _outputs_schema = []

    # Run state
    run_id: bpy.props.StringProperty(name="Run ID", default="")
    status_text: bpy.props.StringProperty(name="Status", default="Idle")
    progress: bpy.props.IntProperty(name="Progress", default=0, min=0, max=100)

    def init(self, context):
        if not hasattr(self.__class__, "_inputs_schema"):
            return

        inputs = self.__class__._inputs_schema
        if isinstance(inputs, str):
            inputs = [inputs]

        for inp in inputs:
            if inp == "image":
                self.inputs.new("ModlyImageSocket", "Image")
            elif inp == "text":
                self.inputs.new("ModlyTextSocket", "Prompt")
            elif inp == "mesh":
                self.inputs.new("ModlyMeshRefSocket", "Mesh")

        outputs = self.__class__._outputs_schema
        if isinstance(outputs, str):
            outputs = [outputs]

        for out in outputs:
            if out == "mesh":
                self.outputs.new("ModlyMeshRefSocket", "Mesh")
            elif out == "image":
                self.outputs.new("ModlyImageSocket", "Image")

    def draw_buttons(self, context, layout):
        if hasattr(self, "_params_schema"):
            for param in self._params_schema:
                layout.prop(self, param["id"])

        if self.run_id or self.status_text != "Idle":
            box = layout.box()
            row = box.row()
            row.label(text=self.status_text)
            if 0 < self.progress < 100:
                box.prop(self, "progress", text="Progress", slider=True)

    def get_params(self) -> dict:
        params = {}
        if hasattr(self, "_params_schema"):
            for param in self._params_schema:
                prop_id = param["id"]
                if hasattr(self, prop_id):
                    val = getattr(self, prop_id)
                    # Convert Enum strings to actual numeric values if needed
                    if param["type"] == "select":
                        for opt in param.get("options", []):
                            if str(opt["value"]) == val:
                                params[prop_id] = opt["value"]
                                break
                        else:
                            params[prop_id] = val
                    else:
                        params[prop_id] = val
        return params

    def get_model_id(self) -> str:
        return self.__class__._model_id

    @property
    def is_text_only(self) -> bool:
        """Tell serializer to inject dummy image if this node takes text but no image."""
        inputs = self.__class__._inputs_schema
        if isinstance(inputs, str):
            inputs = [inputs]
        return "text" in inputs and "image" not in inputs


def _load_manifests_from_disk() -> list:
    """
    Read all manifest.json files from the local Modly extensions directory.
    Returns a list of parsed manifest dicts.
    """
    try:
        from ..preferences import get_extensions_dir
        ext_dir = get_extensions_dir()
    except Exception:
        ext_dir = Path.home() / ".modly" / "extensions"

    if not ext_dir.is_dir():
        log.warning(f"Extensions directory not found: {ext_dir}")
        return []

    allowed_extensions = {"trellis-text", "trellis2", "hunyuan3d-mini-turbo"}
    manifests = []
    for child in sorted(ext_dir.iterdir()):
        manifest_path = child / "manifest.json"
        if child.is_dir() and manifest_path.is_file():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Filter to only the requested models
                if data.get("id") in allowed_extensions:
                    manifests.append(data)
            except Exception as e:
                log.warning(f"Failed to read {manifest_path}: {e}")

    return manifests


def sync_extensions():
    """
    Read extension manifests from disk, generate node classes,
    and rebuild the Add menu categories.
    """
    global _dynamic_classes
    import nodeitems_utils
    from nodeitems_utils import NodeItem
    from .categories import ModlyNodeCategory, _CATEGORY_ID, get_base_categories

    # 1. Unregister old dynamic classes
    for cls in reversed(_dynamic_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            log.warning(f"Failed to unregister {cls}: {e}")
    _dynamic_classes.clear()

    # 2. Load manifests from local disk
    extensions = _load_manifests_from_disk()
    if not extensions:
        log.warning("No extensions found on disk.")

    dynamic_categories = []

    # 3. Create classes and categories for each extension
    for ext in extensions:
        ext_id = ext.get("id", "unknown_ext")
        ext_name = ext.get("name", ext_id)
        nodes = ext.get("nodes", [])

        node_items = []
        safe_ext = ext_id.replace('-', '_').replace('.', '_')

        for node in nodes:
            node_id = node.get("id", "unknown_node")
            node_name = node.get("name", node_id)

            # Prefer "inputs" (list) over "input" (string) for full fidelity
            inputs = node.get("inputs", node.get("input", []))
            outputs = node.get("output", [])

            # Safe Python class name
            safe_node = node_id.replace('-', '_').replace('.', '_')
            class_name = f"ModlyDynamicNode_{safe_ext}_{safe_node}"

            params_schema = node.get("params_schema", [])

            class_dict = {
                "bl_idname": class_name,
                "bl_label": node_name,
                "bl_icon": "MODIFIER",
                "bl_width_default": 220,
                "_model_id": f"{ext_id}:{node_id}",
                "_inputs_schema": inputs,
                "_outputs_schema": outputs,
                "_params_schema": params_schema,
            }

            annotations = {}
            for param in params_schema:
                prop_id = param.get("id")
                if not prop_id:
                    continue
                prop_type = param.get("type", "string")
                prop_label = param.get("label", prop_id)
                prop_default = param.get("default")
                prop_tooltip = param.get("tooltip", "")
                
                if prop_type == "int":
                    safe_min = max(int(param.get("min", -2147483648)), -2147483648)
                    safe_max = min(int(param.get("max", 2147483647)), 2147483647)
                    raw_default = int(prop_default) if prop_default is not None else 0
                    safe_default = max(safe_min, min(raw_default, safe_max))
                    annotations[prop_id] = bpy.props.IntProperty(
                        name=prop_label,
                        description=prop_tooltip,
                        default=safe_default,
                        min=safe_min,
                        max=safe_max,
                    )
                elif prop_type == "float":
                    annotations[prop_id] = bpy.props.FloatProperty(
                        name=prop_label,
                        description=prop_tooltip,
                        default=float(prop_default) if prop_default is not None else 0.0,
                        min=param.get("min", -3.4e38),
                        max=param.get("max", 3.4e38),
                    )
                elif prop_type == "string":
                    annotations[prop_id] = bpy.props.StringProperty(
                        name=prop_label,
                        description=prop_tooltip,
                        default=str(prop_default) if prop_default is not None else "",
                    )
                elif prop_type == "select":
                    items = []
                    for opt in param.get("options", []):
                        val = str(opt.get("value", ""))
                        lbl = str(opt.get("label", val))
                        items.append((val, lbl, ""))
                    
                    default_val = str(prop_default) if prop_default is not None else None
                    if default_val and not any(i[0] == default_val for i in items):
                        default_val = items[0][0] if items else ""
                    
                    if items:
                        annotations[prop_id] = bpy.props.EnumProperty(
                            name=prop_label,
                            description=prop_tooltip,
                            items=items,
                            default=default_val if default_val else items[0][0],
                        )

            class_dict["__annotations__"] = annotations

            new_class = type(
                class_name,
                (ModlyDynamicNodeBase, bpy.types.Node),
                class_dict
            )

            from ..utils import safe_register_class
            safe_register_class(new_class)
            _dynamic_classes.append(new_class)

            node_items.append(NodeItem(class_name))

        if node_items:
            cat_id = f"MODLY_DYNAMIC_{safe_ext.upper()}"
            dynamic_categories.append(
                ModlyNodeCategory(cat_id, ext_name, items=node_items)
            )

    # 4. Rebuild categories
    try:
        nodeitems_utils.unregister_node_categories(_CATEGORY_ID)
    except Exception:
        pass

    base_cats = get_base_categories()
    new_categories = []

    if len(base_cats) > 0:
        new_categories.append(base_cats[0])  # Inputs

    new_categories.extend(dynamic_categories)

    if len(base_cats) > 1:
        new_categories.append(base_cats[1])  # Outputs

    nodeitems_utils.register_node_categories(_CATEGORY_ID, new_categories)
    log.info(f"Synced {len(extensions)} extensions, {len(_dynamic_classes)} nodes.")


def register():
    # Auto-sync on startup so nodes appear immediately without
    # requiring the user to click a button.
    try:
        sync_extensions()
    except Exception as e:
        log.warning(f"Auto-sync on register failed: {e}")


def unregister():
    global _dynamic_classes
    for cls in reversed(_dynamic_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _dynamic_classes.clear()

    import nodeitems_utils
    from .categories import _CATEGORY_ID
    try:
        nodeitems_utils.unregister_node_categories(_CATEGORY_ID)
    except Exception:
        pass
