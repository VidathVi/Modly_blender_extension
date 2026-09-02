"""
Backend control operators — start, stop, restart the Modly subprocess.
"""
from __future__ import annotations

import bpy

from ..backend import process_manager


class MODLY_OT_start_backend(bpy.types.Operator):
    """Start the Modly backend subprocess"""

    bl_idname = "modly.start_backend"
    bl_label = "Start Backend"
    bl_description = "Launch the Modly AI backend process"

    def execute(self, context):
        if process_manager.is_running():
            self.report({'INFO'}, "Backend is already running")
            return {'CANCELLED'}

        ok = process_manager.start()
        if ok:
            self.report({'INFO'}, "Backend starting...")
            # Start a health-check timer
            bpy.ops.modly.check_backend_health('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            msg = process_manager.get_status_message()
            self.report({'ERROR'}, f"Failed to start backend: {msg}")
            return {'CANCELLED'}


class MODLY_OT_stop_backend(bpy.types.Operator):
    """Stop the Modly backend subprocess"""

    bl_idname = "modly.stop_backend"
    bl_label = "Stop Backend"
    bl_description = "Terminate the Modly AI backend process"

    def execute(self, context):
        process_manager.stop()
        self.report({'INFO'}, "Backend stopped")

        # Force UI redraw
        for area in context.screen.areas:
            area.tag_redraw()

        return {'FINISHED'}


class MODLY_OT_restart_backend(bpy.types.Operator):
    """Restart the Modly backend subprocess"""

    bl_idname = "modly.restart_backend"
    bl_label = "Restart Backend"
    bl_description = "Stop and restart the Modly AI backend process"

    def execute(self, context):
        ok = process_manager.restart()
        if ok:
            self.report({'INFO'}, "Backend restarting...")
            bpy.ops.modly.check_backend_health('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            msg = process_manager.get_status_message()
            self.report({'ERROR'}, f"Failed to restart backend: {msg}")
            return {'CANCELLED'}


class MODLY_OT_check_backend_health(bpy.types.Operator):
    """
    Modal timer operator that polls the backend health endpoint
    until it responds or times out.
    """

    bl_idname = "modly.check_backend_health"
    bl_label = "Check Backend Health"
    bl_options = {'INTERNAL'}

    _timer = None
    _attempts = 0
    _max_attempts = 30  # 30 * 1s = 30 second timeout

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        self._attempts += 1

        if process_manager.health_check():
            self.report({'INFO'}, "Backend is running ✓")
            self._cleanup(context)
            # Force UI redraw
            for area in context.screen.areas:
                area.tag_redraw()
            return {'FINISHED'}

        if self._attempts >= self._max_attempts:
            msg = process_manager.get_status_message()
            self.report({'WARNING'}, f"Backend health check timed out: {msg}")
            self._cleanup(context)
            return {'CANCELLED'}

        if not process_manager.is_running():
            msg = process_manager.get_status_message()
            self.report({'ERROR'}, f"Backend process died: {msg}")
            self._cleanup(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        self._attempts = 0
        self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


class MODLY_OT_sync_extensions(bpy.types.Operator):
    """Sync nodes from backend extensions"""
    
    bl_idname = "modly.sync_extensions"
    bl_label = "Sync Extensions"
    bl_description = "Fetch installed extensions from the backend and generate nodes"
    
    def execute(self, context):
        from ..nodes.dynamic import sync_extensions
        try:
            sync_extensions()
            self.report({'INFO'}, "Successfully synced Modly extensions")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to sync extensions: {e}")
            return {'CANCELLED'}
            
        for area in context.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()
                
        return {'FINISHED'}


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    MODLY_OT_start_backend,
    MODLY_OT_stop_backend,
    MODLY_OT_restart_backend,
    MODLY_OT_check_backend_health,
    MODLY_OT_sync_extensions,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
