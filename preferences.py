"""
Addon preferences — user-configurable paths, port, and options.
"""
from __future__ import annotations

import os
from pathlib import Path

import bpy


def _default_modly_api_path() -> str:
    """Best-effort default for the Modly api/ directory."""
    # Check common locations
    candidates = [
        Path("C:/Modly"),
        Path.home() / "Modly",
        Path.home() / "Documents" / "Modly",
    ]
    for p in candidates:
        if (p / "api").is_dir():
            return str(p / "api")
        if (p / "main.py").is_file():
            return str(p)
    return str(Path("C:/Modly/api"))


def _default_modly_data_dir() -> str:
    """Default Modly data directory (models, workspace, extensions)."""
    return str(Path.home() / ".modly")


class ModlyAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__  # Must match the addon package name

    modly_api_path: bpy.props.StringProperty(
        name="Modly API Path",
        description=(
            "Path to the Modly api/ directory (contains main.py, routers/, services/). "
            "This is the backend that the extension launches as a subprocess"
        ),
        subtype='DIR_PATH',
        default=_default_modly_api_path(),
    )

    modly_data_dir: bpy.props.StringProperty(
        name="Modly Data Directory",
        description=(
            "Shared Modly data directory containing models/, workspace/, and extensions/. "
            "Default is ~/.modly/ — point this at wherever the real Modly app stores its data"
        ),
        subtype='DIR_PATH',
        default=_default_modly_data_dir(),
    )

    backend_port: bpy.props.IntProperty(
        name="Backend Port",
        description="Localhost port the Modly backend listens on",
        default=8765,
        min=1024,
        max=65535,
    )

    auto_start_backend: bpy.props.BoolProperty(
        name="Auto-Start Backend",
        description="Automatically start the Modly backend when the addon is enabled",
        default=False,
    )

    def draw(self, context):
        layout = self.layout

        # Attribution
        box = layout.box()
        box.label(text="Based on Modly by Lightning Pixel", icon='INFO')
        box.label(text="https://github.com/lightningpixel/modly")

        layout.separator()

        # Paths
        layout.prop(self, "modly_api_path")
        layout.prop(self, "modly_data_dir")

        layout.separator()

        # Backend settings
        row = layout.row()
        row.prop(self, "backend_port")
        row.prop(self, "auto_start_backend")

        # Validation hints
        api_path = Path(bpy.path.abspath(self.modly_api_path))
        if not api_path.is_dir():
            layout.label(text="⚠ API path does not exist", icon='ERROR')
        elif not (api_path / "main.py").is_file():
            layout.label(text="⚠ main.py not found in API path", icon='ERROR')
        else:
            layout.label(text="✓ API path looks valid", icon='CHECKMARK')

        data_path = Path(bpy.path.abspath(self.modly_data_dir))
        if not data_path.is_dir():
            layout.label(text="⚠ Data directory does not exist", icon='ERROR')
        else:
            models_dir = data_path / "models"
            ext_dir = data_path / "extensions"
            parts = []
            if models_dir.is_dir():
                parts.append("models/")
            if ext_dir.is_dir():
                parts.append("extensions/")
            if parts:
                layout.label(text=f"✓ Found: {', '.join(parts)}", icon='CHECKMARK')
            else:
                layout.label(text="⚠ No models/ or extensions/ subdirectory found", icon='ERROR')


def get_preferences() -> ModlyAddonPreferences:
    """Convenience accessor for the addon preferences."""
    return bpy.context.preferences.addons[__package__].preferences


def get_backend_url() -> str:
    """Return the base URL for the Modly backend."""
    prefs = get_preferences()
    return f"http://127.0.0.1:{prefs.backend_port}"


def get_api_path() -> Path:
    """Return the resolved Modly api/ directory path."""
    prefs = get_preferences()
    return Path(bpy.path.abspath(prefs.modly_api_path))


def get_data_dir() -> Path:
    """Return the resolved Modly data directory path."""
    prefs = get_preferences()
    return Path(bpy.path.abspath(prefs.modly_data_dir))


def get_models_dir() -> Path:
    return get_data_dir() / "models"


def get_workspace_dir() -> Path:
    return get_data_dir() / "workspace"


def get_extensions_dir() -> Path:
    return get_data_dir() / "extensions"
