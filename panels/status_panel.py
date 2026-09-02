"""
Status panel — backend status, start/stop controls, active job display.

Shown in the Node Editor sidebar when a ModlyNodeTree is active,
and also in the 3D Viewport sidebar.
"""
from __future__ import annotations

import bpy

from ..backend import process_manager
from .. import job_registry


# ------------------------------------------------------------------ #
# Node Editor sidebar panel
# ------------------------------------------------------------------ #

class MODLY_PT_status_node_editor(bpy.types.Panel):
    """Modly backend status and controls in the Node Editor sidebar."""

    bl_idname = "MODLY_PT_status_node_editor"
    bl_label = "Modly"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Modly"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and hasattr(space, 'tree_type')
            and space.tree_type == 'ModlyNodeTree'
        )

    def draw(self, context):
        layout = self.layout
        _draw_status(layout, context)


# ------------------------------------------------------------------ #
# 3D Viewport sidebar panel
# ------------------------------------------------------------------ #

class MODLY_PT_status_viewport(bpy.types.Panel):
    """Modly backend status and controls in the 3D Viewport sidebar."""

    bl_idname = "MODLY_PT_status_viewport"
    bl_label = "Modly"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Modly"

    def draw(self, context):
        layout = self.layout
        _draw_status(layout, context)


# ------------------------------------------------------------------ #
# Shared draw function
# ------------------------------------------------------------------ #

def _draw_status(layout: bpy.types.UILayout, context: bpy.types.Context):
    """Draw the status panel contents (shared between editors)."""

    # --- Backend status ---
    box = layout.box()
    box.label(text="Backend", icon='PREFERENCES')

    status = process_manager.get_status()
    msg = process_manager.get_status_message()

    row = box.row(align=True)
    if status == "running":
        row.label(text="Running ✓", icon='CHECKMARK')
    elif status == "starting":
        row.label(text="Starting…", icon='SORTTIME')
    elif status == "failed":
        row.label(text="Failed ✗", icon='ERROR')
    else:
        row.label(text="Stopped", icon='CANCEL')

    if msg:
        box.label(text=msg)

    # Control buttons
    row = box.row(align=True)
    if status in ("stopped", "failed"):
        row.operator("modly.start_backend", text="Start", icon='PLAY')
    else:
        row.operator("modly.stop_backend", text="Stop", icon='PAUSE')
    row.operator("modly.restart_backend", text="Restart", icon='FILE_REFRESH')
    
    row = box.row()
    row.operator("modly.sync_extensions", text="Sync Extensions", icon='FILE_REFRESH')

    # Log file link
    log_path = process_manager.get_log_path()
    if log_path and log_path.is_file():
        box.label(text=f"Log: {log_path.name}")

    layout.separator()

    # --- Run Graph button (only in node editor) ---
    if hasattr(context.space_data, 'tree_type') and getattr(context.space_data, 'tree_type', '') == 'ModlyNodeTree':
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("modly.run_graph", text="Run Graph", icon='PLAY')
        row.operator("modly.cancel_job", text="", icon='CANCEL')

        layout.separator()

    # --- Active jobs ---
    active = job_registry.active_jobs()
    if active:
        box = layout.box()
        box.label(text=f"Active Jobs ({len(active)})", icon='RENDER_ANIMATION')
        for run_id, job in active.items():
            row = box.row()
            row.label(text=f"{job.node_name}: {job.step or job.status}")
            if job.progress > 0:
                row.label(text=f"{job.progress}%")

    # --- Recent completed jobs ---
    all_jobs = job_registry.all_jobs()
    completed = {rid: j for rid, j in all_jobs.items() if j.status == "completed"}
    failed = {rid: j for rid, j in all_jobs.items() if j.status == "failed"}

    if completed or failed:
        box = layout.box()
        box.label(text="Recent", icon='TIME')

        for run_id, job in list(completed.items())[-3:]:
            row = box.row()
            row.label(text=f"✓ {job.node_name}", icon='CHECKMARK')

        for run_id, job in list(failed.items())[-3:]:
            row = box.row()
            row.label(text=f"✗ {job.node_name}: {job.error or 'Failed'}", icon='ERROR')


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    MODLY_PT_status_node_editor,
    MODLY_PT_status_viewport,
)


def register():
    from ..utils import safe_register_class
    for cls in classes:
        safe_register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
