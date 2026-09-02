"""
Modly custom node tree — a native Blender node editor for AI mesh generation.

This creates a distinct editor type (like Shader Editor or Geometry Nodes)
that appears in Blender's editor-type dropdown.  Sockets carry job references
and configuration, not live geometry.
"""
from __future__ import annotations

import bpy


class ModlyNodeTree(bpy.types.NodeTree):
    """Modly AI Mesh Generation — orchestration graph for local AI inference."""

    bl_idname = "ModlyNodeTree"
    bl_label = "Modly"
    bl_icon = "MESH_MONKEY"

    def update(self):
        """Called when links or nodes change.  We don't auto-evaluate."""
        pass


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (ModlyNodeTree,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
