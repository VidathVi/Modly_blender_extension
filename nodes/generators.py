"""
Generator nodes for the Modly node tree.

Each node maps to a Modly backend capability (extension + node from its manifest).
Generator nodes accept input sockets (image, text, mesh-ref) and output a
ModlyJobSocket carrying a run_id once submitted.

Includes:
- Generate Mesh  (Trellis2 GGUF — image → mesh)
- Texture Mesh   (Trellis2 GGUF — mesh + image → textured mesh)
- Trellis Text Base / Large / XL  (text → mesh, three separate node types)
"""
from __future__ import annotations

import bpy

from .inputs import ModlyNodeBase


# ------------------------------------------------------------------ #
# Generate Mesh (Trellis2 GGUF)
# ------------------------------------------------------------------ #

class ModlyGenerateMeshNode(ModlyNodeBase, bpy.types.Node):
    """
    Generate Mesh — submit an image to the Modly backend to produce a 3D mesh.

    Maps to the Trellis2 GGUF extension's 'generate' node
    (input: image, output: mesh GLB).
    """

    bl_idname = "ModlyGenerateMeshNode"
    bl_label = "Generate Mesh"
    bl_icon = "MESH_ICOSPHERE"
    bl_width_default = 220

    # --- Model parameters (from Trellis2 manifest params_schema) ---

    model_id: bpy.props.StringProperty(
        name="Model ID",
        description="Modly model identifier (extension_id:node_id)",
        default="trellis2:generate",
    )

    pipeline_type: bpy.props.EnumProperty(
        name="Quality",
        description="Resolution and cascade steps — higher = better detail, slower",
        items=[
            ("512", "Fast (512)", "Fast generation at 512 resolution"),
            ("1024", "Balanced (1024)", "Balanced quality at 1024 resolution"),
            ("1024_cascade", "High (1024 cascade)", "High quality with cascade steps"),
            ("1536_cascade", "Ultra (1536 cascade)", "Ultra quality — slowest"),
        ],
        default="1024_cascade",
    )

    seed: bpy.props.IntProperty(
        name="Seed",
        description="Random seed (0 = random)",
        default=0,
        min=0,
    )

    # --- Run state (display only, authoritative state in job_registry) ---

    run_id: bpy.props.StringProperty(name="Run ID", default="")
    status_text: bpy.props.StringProperty(name="Status", default="Idle")
    progress: bpy.props.IntProperty(name="Progress", default=0, min=0, max=100)

    def init(self, context):
        self.inputs.new("ModlyImageSocket", "Image")
        self.outputs.new("ModlyJobSocket", "Job")

    def draw_buttons(self, context, layout):
        layout.prop(self, "pipeline_type")
        layout.prop(self, "seed")

        # Status display
        if self.run_id:
            box = layout.box()
            row = box.row()
            row.label(text=self.status_text)
            if 0 < self.progress < 100:
                box.prop(self, "progress", text="Progress", slider=True)

    def get_params(self) -> dict:
        """Return the model parameters dict for the backend payload."""
        params = {"pipeline_type": self.pipeline_type}
        if self.seed > 0:
            params["seed"] = self.seed
        return params

    def get_model_id(self) -> str:
        """Return the model ID string for the workflow-run endpoint."""
        return self.model_id


# ------------------------------------------------------------------ #
# Texture Mesh (Trellis2 GGUF)
# ------------------------------------------------------------------ #

class ModlyTextureMeshNode(ModlyNodeBase, bpy.types.Node):
    """
    Texture Mesh — take an existing mesh (from Generate Mesh or Selection-In)
    plus an image/prompt and produce a textured mesh.

    Maps to the Trellis2 GGUF extension's texture capability
    (input: mesh + image, output: textured mesh GLB).
    """

    bl_idname = "ModlyTextureMeshNode"
    bl_label = "Texture Mesh"
    bl_icon = "MATERIAL"
    bl_width_default = 220

    model_id: bpy.props.StringProperty(
        name="Model ID",
        description="Modly model identifier",
        default="trellis2:texture",
    )

    seed: bpy.props.IntProperty(
        name="Seed",
        description="Random seed (0 = random)",
        default=0,
        min=0,
    )

    # Run state
    run_id: bpy.props.StringProperty(name="Run ID", default="")
    status_text: bpy.props.StringProperty(name="Status", default="Idle")
    progress: bpy.props.IntProperty(name="Progress", default=0, min=0, max=100)

    def init(self, context):
        # Accepts a job reference (from Generate Mesh) OR a mesh-ref (from Selection-In)
        self.inputs.new("ModlyJobSocket", "Mesh Job")
        self.inputs.new("ModlyMeshRefSocket", "Mesh File")
        self.inputs.new("ModlyImageSocket", "Image")
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
        return self.model_id


# ------------------------------------------------------------------ #
# Trellis Text nodes — three distinct types (Base / Large / XL)
# ------------------------------------------------------------------ #

class _TrellisTextNodeBase(ModlyNodeBase, bpy.types.Node):
    """
    Base class for TRELLIS Text nodes.

    These accept only a text prompt (the image input is a placeholder
    injected silently during serialization — see the plan's compatibility
    quirk note).  Each size is a separate node type, not a dropdown.
    """

    # Subclasses MUST set these
    bl_idname = ""
    bl_label = ""
    _capability_id = ""
    _hf_repo = ""

    bl_icon = "TEXT"
    bl_width_default = 250

    model_id: bpy.props.StringProperty(name="Model ID", default="")

    seed: bpy.props.IntProperty(
        name="Seed",
        description="Random seed (0 = random)",
        default=0,
        min=0,
    )

    # Run state
    run_id: bpy.props.StringProperty(name="Run ID", default="")
    status_text: bpy.props.StringProperty(name="Status", default="Idle")
    progress: bpy.props.IntProperty(name="Progress", default=0, min=0, max=100)

    def init(self, context):
        self.inputs.new("ModlyTextSocket", "Prompt")
        self.outputs.new("ModlyJobSocket", "Job")
        # Set the model_id from the class-level capability
        self.model_id = f"trellis-text:{self._capability_id}"

    def draw_buttons(self, context, layout):
        layout.prop(self, "seed")
        if self.run_id:
            box = layout.box()
            row = box.row()
            row.label(text=self.status_text)
            if 0 < self.progress < 100:
                box.prop(self, "progress", text="Progress", slider=True)

    def get_params(self) -> dict:
        """Return params including the prompt from the connected input."""
        params = {}
        if self.seed > 0:
            params["seed"] = self.seed
        # The prompt is pulled from the connected Text socket during serialization
        return params

    def get_model_id(self) -> str:
        return self.model_id

    @property
    def is_text_only(self) -> bool:
        """Flag used by the serializer to inject a dummy image."""
        return True


class ModlyTrellisTextBaseNode(_TrellisTextNodeBase):
    """Trellis Text Base — generate a textured mesh from a text prompt (Low VRAM)."""

    bl_idname = "ModlyTrellisTextBaseNode"
    bl_label = "Trellis Text: Base"
    _capability_id = "text-to-mesh-base"
    _hf_repo = "microsoft/TRELLIS-text-base"


class ModlyTrellisTextLargeNode(_TrellisTextNodeBase):
    """Trellis Text Large — generate a textured mesh from a text prompt (Medium VRAM)."""

    bl_idname = "ModlyTrellisTextLargeNode"
    bl_label = "Trellis Text: Large"
    _capability_id = "text-to-mesh-large"
    _hf_repo = "microsoft/TRELLIS-text-large"


class ModlyTrellisTextXLNode(_TrellisTextNodeBase):
    """Trellis Text XL — generate a textured mesh from a text prompt (High VRAM)."""

    bl_idname = "ModlyTrellisTextXLNode"
    bl_label = "Trellis Text: XL"
    _capability_id = "text-to-mesh-xl"
    _hf_repo = "microsoft/TRELLIS-text-xlarge"


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    ModlyGenerateMeshNode,
    ModlyTextureMeshNode,
    ModlyTrellisTextBaseNode,
    ModlyTrellisTextLargeNode,
    ModlyTrellisTextXLNode,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
