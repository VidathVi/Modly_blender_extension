"""
Modly — AI Mesh Generation for Blender

A Blender extension that vendors Modly's local AI mesh/texture-generation
backend, auto-manages it as a background process, and exposes model
capabilities through a native Blender node graph.

Based on Modly by Lightning Pixel
https://github.com/lightningpixel/modly
MIT License
"""
from __future__ import annotations

import bpy

# Sub-modules are imported inside register()/unregister() to avoid
# issues with Blender's import order and allow clean reload.


def _register_submodules():
    """Import and register all submodule classes."""
    from . import preferences
    from .nodes import tree, sockets, categories, inputs, builtin, dynamic, outputs
    from .operators import backend_ops, run_graph
    from .panels import status_panel, models_panel

    # Registration order matters: sockets before nodes, nodes before categories
    from .utils import safe_register_class
    safe_register_class(preferences.ModlyAddonPreferences)

    tree.register()
    sockets.register()
    inputs.register()
    builtin.register()
    dynamic.register()
    outputs.register()

    backend_ops.register()
    run_graph.register()

    status_panel.register()
    models_panel.register()


def _unregister_submodules():
    """Unregister all submodule classes in reverse order."""
    from . import preferences
    from .nodes import tree, sockets, categories, inputs, builtin, dynamic, outputs
    from .operators import backend_ops, run_graph
    from .panels import status_panel, models_panel

    models_panel.unregister()
    status_panel.unregister()

    run_graph.unregister()
    backend_ops.unregister()


    outputs.unregister()
    dynamic.unregister()
    builtin.unregister()
    inputs.unregister()
    sockets.unregister()
    tree.unregister()

    bpy.utils.unregister_class(preferences.ModlyAddonPreferences)


def register():
    """Addon entry point — called when the extension is enabled."""
    _register_submodules()

    # Auto-start backend if preference is set
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        if prefs.auto_start_backend:
            # Defer to avoid issues during Blender startup
            bpy.app.timers.register(_deferred_auto_start, first_interval=2.0)
    except Exception:
        pass

    print("[Modly] Extension registered")


def unregister():
    """Addon teardown — called when the extension is disabled or Blender quits."""
    # Stop the backend subprocess — don't leave orphan processes
    try:
        from .backend import process_manager
        process_manager.stop()
    except Exception:
        pass

    _unregister_submodules()

    print("[Modly] Extension unregistered")


def _deferred_auto_start():
    """Timer callback to auto-start the backend after Blender finishes loading."""
    try:
        from .backend import process_manager
        if not process_manager.is_running():
            process_manager.start()
            # Start health check polling
            bpy.ops.modly.check_backend_health('INVOKE_DEFAULT')
    except Exception as exc:
        print(f"[Modly] Auto-start failed: {exc}")
    return None  # Don't repeat the timer
