"""
Output nodes for the Modly node tree.

Add to Scene — terminal node that imports a completed job's GLB result
into the Blender scene, with options for adding as new vs. replacing in place.
"""
from __future__ import annotations

import os
import time

import bpy

from .inputs import ModlyNodeBase


class ModlyAddToSceneNode(ModlyNodeBase, bpy.types.Node):
    """
    Add to Scene — imports the completed generation result into the Blender scene.

    Terminal node: takes a ModlyJobSocket input.  When the upstream job
    completes, the resulting GLB is imported automatically.
    """

    bl_idname = "ModlyAddToSceneNode"
    bl_label = "Add to Scene"
    bl_icon = "IMPORT"
    bl_width_default = 220

    import_mode: bpy.props.EnumProperty(
        name="Mode",
        description="How to handle the imported mesh",
        items=[
            ("ADD", "Add as New Object", "Import as a new object in the scene"),
            ("REPLACE", "Replace Source Object", "Replace the source object's mesh/materials in place"),
        ],
        default="ADD",
    )

    auto_import: bpy.props.BoolProperty(
        name="Auto Import",
        description="Automatically import when the job completes (no second click needed)",
        default=True,
    )

    # Run state (mirrors job_registry for display)
    run_id: bpy.props.StringProperty(name="Run ID", default="")
    status_text: bpy.props.StringProperty(name="Status", default="Waiting")
    output_path: bpy.props.StringProperty(name="Output Path", default="")

    def init(self, context):
        self.inputs.new("ModlyJobSocket", "Job")

    def draw_buttons(self, context, layout):
        layout.prop(self, "import_mode")
        layout.prop(self, "auto_import")

        if self.status_text:
            box = layout.box()
            box.label(text=self.status_text)

    def import_result(self, context, glb_path: str, source_object_name: str = "") -> bool:
        """
        Import a GLB file into the scene.

        Args:
            context: Blender context
            glb_path: Path to the .glb file to import
            source_object_name: Name of the source object (for replace mode)

        Returns:
            True if import succeeded.
        """
        if not os.path.isfile(glb_path):
            self.status_text = f"Error: file not found: {glb_path}"
            self.update_status_color("failed")
            return False

        # Remember what objects exist before import
        existing_objects = set(bpy.data.objects.keys())

        try:
            bpy.ops.import_scene.gltf(filepath=glb_path)
        except Exception as exc:
            self.status_text = f"Import error: {exc}"
            self.update_status_color("failed")
            return False

        # Find the newly imported objects
        new_objects = [
            bpy.data.objects[name]
            for name in bpy.data.objects.keys()
            if name not in existing_objects
        ]

        if not new_objects:
            self.status_text = "Warning: no objects imported"
            return False

        timestamp = time.strftime("%H%M%S")

        if self.import_mode == "REPLACE" and source_object_name:
            # Replace mode: swap the source object's mesh data
            source_obj = bpy.data.objects.get(source_object_name)
            if source_obj and source_obj.type == 'MESH' and new_objects:
                imported = new_objects[0]
                if imported.type == 'MESH':
                    # Replace mesh data
                    old_mesh = source_obj.data
                    source_obj.data = imported.data
                    # Copy materials
                    source_obj.data.materials.clear()
                    for mat in imported.data.materials:
                        source_obj.data.materials.append(mat)
                    # Remove the imported object shell (keep its mesh data, now on source)
                    bpy.data.objects.remove(imported, do_unlink=True)
                    # Clean up old mesh if orphaned
                    if old_mesh.users == 0:
                        bpy.data.meshes.remove(old_mesh)

                    self.status_text = f"Replaced: {source_obj.name}"
                    self.update_status_color("completed")
                    return True

        # Add mode (default): rename imported objects sensibly
        for obj in new_objects:
            # Try to derive a name from the prompt or source
            obj.name = f"Modly_{timestamp}_{obj.name}"

        self.status_text = f"Imported {len(new_objects)} object(s)"
        self.update_status_color("completed")
        return True


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (ModlyAddToSceneNode,)


def register():
    from ..utils import safe_register_class
    for cls in classes:
        safe_register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
