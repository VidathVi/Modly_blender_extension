"""
Input nodes for the Modly node tree.

- Image Input: file picker for a reference image
- Text Prompt: text field for prompt-driven generation
- Selection-In: exports the currently selected Blender object to temp GLB
"""
from __future__ import annotations

import os
import tempfile
import time

import bpy

# Mixin to restrict nodes to the Modly tree
_POLL_TREE = "ModlyNodeTree"


class ModlyNodeBase:
    """Mixin for all Modly nodes — restricts them to the Modly tree type."""

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == _POLL_TREE

    def update_status_color(self, status: str = "idle"):
        """Set the node header color based on status."""
        if status == "running":
            self.use_custom_color = True
            self.color = (0.15, 0.35, 0.7)  # Blue
        elif status == "completed":
            self.use_custom_color = True
            self.color = (0.15, 0.6, 0.25)  # Green
        elif status == "failed":
            self.use_custom_color = True
            self.color = (0.7, 0.15, 0.15)  # Red
        else:
            self.use_custom_color = False


# ------------------------------------------------------------------ #
# Image Input
# ------------------------------------------------------------------ #

class ModlyImageInputNode(ModlyNodeBase, bpy.types.Node):
    """Reference image input — pick an image file for image-to-mesh generation."""

    bl_idname = "ModlyImageInputNode"
    bl_label = "Image Input"
    bl_icon = "IMAGE_DATA"
    bl_width_default = 200

    image_path: bpy.props.StringProperty(
        name="Image",
        description="Path to a reference image (PNG, JPG, etc.)",
        subtype='FILE_PATH',
        default="",
    )

    def init(self, context):
        self.outputs.new("ModlyImageSocket", "Image")

    def draw_buttons(self, context, layout):
        layout.prop(self, "image_path", text="")

    def get_value(self) -> str:
        """Return the resolved image path."""
        return bpy.path.abspath(self.image_path)


# ------------------------------------------------------------------ #
# Text Prompt
# ------------------------------------------------------------------ #

class ModlyTextPromptNode(ModlyNodeBase, bpy.types.Node):
    """Text prompt input — type a description for text-to-mesh generation."""

    bl_idname = "ModlyTextPromptNode"
    bl_label = "Text Prompt"
    bl_icon = "TEXT"
    bl_width_default = 250

    prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Describe the 3D model you want to generate",
        default="",
    )

    def init(self, context):
        self.outputs.new("ModlyTextSocket", "Prompt")

    def draw_buttons(self, context, layout):
        layout.prop(self, "prompt", text="")

    def get_value(self) -> str:
        """Return the prompt text."""
        return self.prompt


# ------------------------------------------------------------------ #
# Selection-In
# ------------------------------------------------------------------ #

class ModlySelectionInNode(ModlyNodeBase, bpy.types.Node):
    """
    Selection Input — at run time, exports the active Blender object to a
    temporary GLB file for use as mesh input to downstream nodes (e.g., Texture Mesh).

    No manual input needed: reads bpy.context.active_object when the graph runs.
    """

    bl_idname = "ModlySelectionInNode"
    bl_label = "Selection In"
    bl_icon = "RESTRICT_SELECT_OFF"
    bl_width_default = 180

    # Stored after export so downstream nodes can read the path
    exported_path: bpy.props.StringProperty(
        name="Exported GLB",
        description="Path to the exported temporary GLB (set at run time)",
        default="",
    )

    def init(self, context):
        self.outputs.new("ModlyMeshRefSocket", "Mesh")

    def draw_buttons(self, context, layout):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            layout.label(text=f"Active: {obj.name}", icon='OBJECT_DATA')
        else:
            layout.label(text="No mesh selected", icon='ERROR')

    def export_selection(self, context) -> str:
        """
        Export the active mesh object to a temporary GLB file.

        Returns the file path, or raises RuntimeError if nothing suitable
        is selected.
        """
        obj = context.active_object
        if obj is None:
            raise RuntimeError("No active object — select a mesh before running")
        if obj.type != 'MESH':
            raise RuntimeError(f"Active object '{obj.name}' is not a mesh (type: {obj.type})")

        # Create a temp file that persists until the job completes
        tmp_dir = os.path.join(tempfile.gettempdir(), "modly_blender")
        os.makedirs(tmp_dir, exist_ok=True)
        timestamp = int(time.time())
        filename = f"selection_{obj.name}_{timestamp}.glb"
        filepath = os.path.join(tmp_dir, filename)

        # Select only this object for export
        prev_selection = context.selected_objects[:]
        prev_active = context.view_layer.objects.active

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        try:
            bpy.ops.export_scene.gltf(
                filepath=filepath,
                use_selection=True,
                export_format='GLB',
            )
        finally:
            # Restore selection
            bpy.ops.object.select_all(action='DESELECT')
            for o in prev_selection:
                o.select_set(True)
            context.view_layer.objects.active = prev_active

        self.exported_path = filepath
        return filepath

    def get_value(self) -> str:
        """Return the exported GLB path (must call export_selection first)."""
        return self.exported_path


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    ModlyImageInputNode,
    ModlyTextPromptNode,
    ModlySelectionInNode,
)


def register():
    from ..utils import safe_register_class
    for cls in classes:
        safe_register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
