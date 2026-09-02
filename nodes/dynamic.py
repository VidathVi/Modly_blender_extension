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

    seed: bpy.props.IntProperty(
        name="Seed",
        description="Random seed (0 = random)",
        default=0,
        min=0,
    )

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
                self.inputs.new("ModlyMeshRefSocket", "Mesh File")

        # Nodes that accept mesh input can also chain from an upstream Job
        if "mesh" in inputs:
            self.inputs.new("ModlyJobSocket", "Mesh Job")

        self.outputs.new("ModlyJobSocket", "Job")

    def draw_buttons(self, context, layout):
        layout.prop(self, "seed")

        if self.run_id:
            box = layout.box()
            row = box.row()
            row.label(text=self.status_text)
            if 0 < self.progress < 100:
                box.prop(self, "progress", text="Progress", slider=True)

    def get_params(self) -> dict:
        params = {}
        if self.seed > 0:
            params["seed"] = self.seed
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

    manifests = []
    for child in sorted(ext_dir.iterdir()):
        manifest_path = child / "manifest.json"
        if child.is_dir() and manifest_path.is_file():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
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

            new_class = type(
                class_name,
                (ModlyDynamicNodeBase, bpy.types.Node),
                {
                    "bl_idname": class_name,
                    "bl_label": node_name,
                    "bl_icon": "MODIFIER",
                    "bl_width_default": 220,
                    "_model_id": f"{ext_id}:{node_id}",
                    "_inputs_schema": inputs,
                    "_outputs_schema": outputs,
                }
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
    except KeyError:
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
