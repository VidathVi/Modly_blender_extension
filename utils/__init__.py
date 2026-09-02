# Modly utility modules package

import bpy


def safe_register_class(cls):
    """Register a Blender class, handling reload by unregistering first."""
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        pass
    bpy.utils.register_class(cls)
