"""
Custom socket types for the Modly node tree.

Sockets carry *job references and configuration*, not live geometry.
The graph is an orchestration graph (what to submit and in what order),
not a per-frame compute graph.
"""
from __future__ import annotations

import bpy


class ModlyImageSocket(bpy.types.NodeSocket):
    """Socket carrying an image file path."""

    bl_idname = "ModlyImageSocket"
    bl_label = "Image"

    default_value: bpy.props.StringProperty(
        name="Image Path",
        description="Path to an image file",
        subtype='FILE_PATH',
        default="",
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.8, 0.5, 0.2, 1.0)  # Orange


class ModlyTextSocket(bpy.types.NodeSocket):
    """Socket carrying a text prompt string."""

    bl_idname = "ModlyTextSocket"
    bl_label = "Text"

    default_value: bpy.props.StringProperty(
        name="Prompt",
        description="Text prompt for generation",
        default="",
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.4, 0.7, 1.0, 1.0)  # Light blue


class ModlyMeshRefSocket(bpy.types.NodeSocket):
    """Socket carrying a mesh file path reference (e.g., exported GLB)."""

    bl_idname = "ModlyMeshRefSocket"
    bl_label = "Mesh Ref"

    default_value: bpy.props.StringProperty(
        name="Mesh Path",
        description="Path to a mesh file (GLB)",
        default="",
    )

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.2, 0.9, 0.4, 1.0)  # Green


class ModlyJobSocket(bpy.types.NodeSocket):
    """
    Socket carrying a job reference (run_id + status).

    This is the primary data-flow type between generator nodes and the
    Add to Scene terminal node.  The actual mesh doesn't exist as Blender
    data until the job completes and gets imported.
    """

    bl_idname = "ModlyJobSocket"
    bl_label = "Job"

    # The run_id is stored here for display; the authoritative state
    # lives in job_registry to survive undo.
    default_value: bpy.props.StringProperty(
        name="Run ID",
        description="Backend job run identifier",
        default="",
    )

    def draw(self, context, layout, node, text):
        if self.default_value:
            layout.label(text=f"{text}: {self.default_value[:8]}…")
        else:
            layout.label(text=text)

    def draw_color(self, context, node):
        return (1.0, 0.9, 0.2, 1.0)  # Yellow


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    ModlyImageSocket,
    ModlyTextSocket,
    ModlyMeshRefSocket,
    ModlyJobSocket,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
