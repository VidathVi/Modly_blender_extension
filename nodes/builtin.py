"""
Built-in mesh operation nodes — native Blender modifier nodes for
post-import processing.

These nodes do NOT route through the Modly backend.  Instead, they
flag themselves as local Blender tasks.  After the upstream AI
generator completes and the mesh is imported, run_graph.py calls
each node's ``apply_modifier()`` method to apply the corresponding
Blender modifier directly to the imported object(s).

Nodes:
  - Optimize Mesh  → Decimate modifier
  - Smooth Mesh    → Subdivision Surface modifier
  - Remesh         → Remesh modifier (Voxel / Smooth / Sharp / Blocks)
  - Solidify       → Solidify modifier
"""
from __future__ import annotations

import logging

import bpy

from .inputs import ModlyNodeBase

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Base mixin — NOT registered with Blender, no bpy.props here
# ------------------------------------------------------------------ #

class ModlyBuiltinNodeBase(ModlyNodeBase):
    """
    Pure Python mixin for built-in mesh-operation nodes.

    Provides the sentinel flag, shared socket setup, and the
    _finalise() helper.  bpy.props are defined on each concrete
    subclass so Blender's metaclass can register them properly.
    """

    # Sentinel detected by graph_serializer and run_graph
    is_builtin_modifier = True

    # ----- sockets -----

    def init(self, context):
        self.inputs.new("ModlyMeshRefSocket", "Mesh")
        self.outputs.new("ModlyMeshRefSocket", "Mesh")

    # ----- modifier application -----

    def apply_modifier(self, obj: bpy.types.Object) -> None:
        """
        Add the appropriate Blender modifier to *obj*.
        Subclasses must override this.
        """
        raise NotImplementedError

    def _finalise(self, obj: bpy.types.Object, modifier) -> None:
        """Permanently apply the modifier if the node property says so."""
        if self.apply_permanently:
            try:
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except Exception as exc:
                log.warning(
                    "Could not permanently apply modifier '%s' on '%s': %s",
                    modifier.name, obj.name, exc,
                )


# ------------------------------------------------------------------ #
# Optimize Mesh  (Decimate)
# ------------------------------------------------------------------ #

class ModlyOptimizeMeshNode(ModlyBuiltinNodeBase, bpy.types.Node):
    """Reduce polygon count using a Decimate modifier."""

    bl_idname = "ModlyOptimizeMeshNode"
    bl_label = "Optimize Mesh"
    bl_icon = "MOD_DECIM"
    bl_width_default = 200

    ratio: bpy.props.FloatProperty(
        name="Ratio",
        description="Target ratio of faces to keep (1.0 = no reduction)",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    decimate_type: bpy.props.EnumProperty(
        name="Type",
        description="Decimation algorithm",
        items=[
            ("COLLAPSE", "Collapse", "Merge vertices to reduce face count"),
            ("UNSUBDIV", "Un-Subdivide", "Reverse subdivision"),
            ("DISSOLVE", "Planar", "Dissolve planar faces"),
        ],
        default="COLLAPSE",
    )

    apply_permanently: bpy.props.BoolProperty(
        name="Apply Permanently",
        description=(
            "Permanently apply the modifier (destructive). "
            "When off, the modifier stays live on the modifier stack"
        ),
        default=False,
    )

    def draw_buttons(self, context, layout):
        layout.prop(self, "decimate_type")
        layout.prop(self, "ratio", slider=True)
        layout.prop(self, "apply_permanently")

    def apply_modifier(self, obj: bpy.types.Object) -> None:
        mod = obj.modifiers.new(name="Modly Optimize", type='DECIMATE')
        mod.decimate_type = self.decimate_type
        mod.ratio = self.ratio
        log.info("Applied Decimate (ratio=%.2f) to '%s'", self.ratio, obj.name)
        self._finalise(obj, mod)


# ------------------------------------------------------------------ #
# Smooth Mesh  (Subdivision Surface)
# ------------------------------------------------------------------ #

class ModlySmoothMeshNode(ModlyBuiltinNodeBase, bpy.types.Node):
    """Smooth a mesh using a Subdivision Surface modifier."""

    bl_idname = "ModlySmoothMeshNode"
    bl_label = "Smooth Mesh"
    bl_icon = "MOD_SUBSURF"
    bl_width_default = 200

    levels: bpy.props.IntProperty(
        name="Viewport Levels",
        description="Number of subdivision levels shown in the viewport",
        default=2,
        min=1,
        max=6,
    )

    render_levels: bpy.props.IntProperty(
        name="Render Levels",
        description="Number of subdivision levels used during rendering",
        default=2,
        min=1,
        max=6,
    )

    subdivision_type: bpy.props.EnumProperty(
        name="Type",
        description="Subdivision algorithm",
        items=[
            ("CATMULL_CLARK", "Catmull-Clark", "Smooth subdivision"),
            ("SIMPLE", "Simple", "Keep flat surfaces — just add geometry"),
        ],
        default="CATMULL_CLARK",
    )

    apply_permanently: bpy.props.BoolProperty(
        name="Apply Permanently",
        description=(
            "Permanently apply the modifier (destructive). "
            "When off, the modifier stays live on the modifier stack"
        ),
        default=False,
    )

    def draw_buttons(self, context, layout):
        layout.prop(self, "subdivision_type")
        layout.prop(self, "levels")
        layout.prop(self, "render_levels")
        layout.prop(self, "apply_permanently")

    def apply_modifier(self, obj: bpy.types.Object) -> None:
        mod = obj.modifiers.new(name="Modly Smooth", type='SUBSURF')
        mod.subdivision_type = self.subdivision_type
        mod.levels = self.levels
        mod.render_levels = self.render_levels
        log.info(
            "Applied Subdivision Surface (levels=%d) to '%s'",
            self.levels, obj.name,
        )
        self._finalise(obj, mod)


# ------------------------------------------------------------------ #
# Remesh
# ------------------------------------------------------------------ #

class ModlyRemeshNode(ModlyBuiltinNodeBase, bpy.types.Node):
    """Re-topology a mesh using a Remesh modifier."""

    bl_idname = "ModlyRemeshNode"
    bl_label = "Remesh"
    bl_icon = "MOD_REMESH"
    bl_width_default = 200

    mode: bpy.props.EnumProperty(
        name="Mode",
        description="Remeshing algorithm",
        items=[
            ("VOXEL", "Voxel", "Even quad-based remesh using voxel size"),
            ("SMOOTH", "Smooth", "Smooth output — slower but higher quality"),
            ("SHARP", "Sharp", "Preserve sharp edges"),
            ("BLOCKS", "Blocks", "Blocky / voxel-art style"),
        ],
        default="VOXEL",
    )

    voxel_size: bpy.props.FloatProperty(
        name="Voxel Size",
        description="Size of each voxel (smaller = more detail, more polygons)",
        default=0.05,
        min=0.001,
        max=1.0,
        precision=3,
    )

    octree_depth: bpy.props.IntProperty(
        name="Octree Depth",
        description="Resolution for non-Voxel modes (higher = more detail)",
        default=4,
        min=1,
        max=12,
    )

    smooth_normals: bpy.props.BoolProperty(
        name="Smooth Normals",
        description="Apply smooth shading after remesh",
        default=True,
    )

    apply_permanently: bpy.props.BoolProperty(
        name="Apply Permanently",
        description=(
            "Permanently apply the modifier (destructive). "
            "When off, the modifier stays live on the modifier stack"
        ),
        default=False,
    )

    def draw_buttons(self, context, layout):
        layout.prop(self, "mode")
        if self.mode == "VOXEL":
            layout.prop(self, "voxel_size")
        else:
            layout.prop(self, "octree_depth")
        layout.prop(self, "smooth_normals")
        layout.prop(self, "apply_permanently")

    def apply_modifier(self, obj: bpy.types.Object) -> None:
        mod = obj.modifiers.new(name="Modly Remesh", type='REMESH')
        mod.mode = self.mode

        if self.mode == "VOXEL":
            mod.voxel_size = self.voxel_size
        else:
            mod.octree_depth = self.octree_depth

        mod.use_smooth_shade = self.smooth_normals
        log.info("Applied Remesh (mode=%s) to '%s'", self.mode, obj.name)
        self._finalise(obj, mod)


# ------------------------------------------------------------------ #
# Solidify
# ------------------------------------------------------------------ #

class ModlySolidifyNode(ModlyBuiltinNodeBase, bpy.types.Node):
    """Give thickness to flat surfaces using a Solidify modifier."""

    bl_idname = "ModlySolidifyNode"
    bl_label = "Solidify"
    bl_icon = "MOD_SOLIDIFY"
    bl_width_default = 200

    thickness: bpy.props.FloatProperty(
        name="Thickness",
        description="Thickness of the shell added to the mesh",
        default=0.1,
        min=0.001,
        max=10.0,
    )

    offset: bpy.props.FloatProperty(
        name="Offset",
        description=(
            "Offset direction (-1 = inward, 0 = centered, 1 = outward)"
        ),
        default=-1.0,
        min=-1.0,
        max=1.0,
    )

    even_thickness: bpy.props.BoolProperty(
        name="Even Thickness",
        description="Maintain even thickness around sharp edges",
        default=True,
    )

    apply_permanently: bpy.props.BoolProperty(
        name="Apply Permanently",
        description=(
            "Permanently apply the modifier (destructive). "
            "When off, the modifier stays live on the modifier stack"
        ),
        default=False,
    )

    def draw_buttons(self, context, layout):
        layout.prop(self, "thickness")
        layout.prop(self, "offset", slider=True)
        layout.prop(self, "even_thickness")
        layout.prop(self, "apply_permanently")

    def apply_modifier(self, obj: bpy.types.Object) -> None:
        mod = obj.modifiers.new(name="Modly Solidify", type='SOLIDIFY')
        mod.thickness = self.thickness
        mod.offset = self.offset
        mod.use_even_offset = self.even_thickness
        log.info(
            "Applied Solidify (thickness=%.3f) to '%s'",
            self.thickness, obj.name,
        )
        self._finalise(obj, mod)


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    ModlyOptimizeMeshNode,
    ModlySmoothMeshNode,
    ModlyRemeshNode,
    ModlySolidifyNode,
)


def register():
    from ..utils import safe_register_class
    for cls in classes:
        safe_register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
