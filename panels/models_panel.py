"""
Models panel — read-only view of installed Modly extensions and models.

Scans the shared Modly data directory (Path A) for installed extensions
and shows their available nodes, VRAM requirements, and download status.
Includes a Refresh button and a hint to open the real Modly app for
model installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import bpy

from ..preferences import get_extensions_dir, get_models_dir


# Cached extension data (refreshed on button click)
_cached_extensions: List[Dict] = []
_cache_valid = False


def _scan_extensions() -> List[Dict]:
    """
    Scan the shared Modly extensions directory for installed extensions.

    Each extension is a folder with a manifest.json file.
    Returns a list of parsed manifest dicts.
    """
    extensions = []

    ext_dir = get_extensions_dir()
    if not ext_dir.is_dir():
        return extensions

    for entry in sorted(ext_dir.iterdir()):
        if not entry.is_dir():
            continue

        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["_dir"] = str(entry)
            manifest["_dir_name"] = entry.name
            extensions.append(manifest)
        except (json.JSONDecodeError, OSError):
            extensions.append({
                "id": entry.name,
                "name": entry.name,
                "_error": "Failed to parse manifest.json",
                "_dir": str(entry),
                "_dir_name": entry.name,
            })

    return extensions


def _check_model_downloaded(ext: Dict) -> Dict[str, bool]:
    """
    Check which model variants of an extension are downloaded.

    Returns {node_id: is_downloaded} based on the download_check file.
    """
    result = {}
    models_dir = get_models_dir()
    ext_id = ext.get("id", "")

    for node in ext.get("nodes", []):
        node_id = node.get("id", "")
        # Models are stored at <models_dir>/<ext_id>/<node_id>/
        check_file = node.get("download_check", "pipeline.json")
        node_model_dir = models_dir / ext_id / node_id

        # Also check <models_dir>/<ext_id>/ directly
        alt_dir = models_dir / ext_id

        downloaded = (
            (node_model_dir / check_file).is_file()
            or (alt_dir / check_file).is_file()
        )
        result[node_id] = downloaded

    return result


def refresh_cache():
    """Force a re-scan of the extensions directory."""
    global _cached_extensions, _cache_valid
    _cached_extensions = _scan_extensions()
    _cache_valid = True


# ------------------------------------------------------------------ #
# Panel
# ------------------------------------------------------------------ #

class MODLY_PT_models(bpy.types.Panel):
    """Modly Models & Extensions — installed extensions and model availability."""

    bl_idname = "MODLY_PT_models"
    bl_label = "Models & Extensions"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Modly"
    bl_options = {'DEFAULT_CLOSED'}

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

        # Refresh button
        layout.operator("modly.refresh_models", text="Refresh", icon='FILE_REFRESH')

        global _cached_extensions, _cache_valid
        if not _cache_valid:
            refresh_cache()

        if not _cached_extensions:
            box = layout.box()
            box.label(text="No extensions found", icon='INFO')
            box.label(text="Install extensions via the Modly app,")
            box.label(text="then click Refresh.")

            from ..preferences import get_extensions_dir
            ext_dir = get_extensions_dir()
            box.label(text=f"Path: {ext_dir}")
            return

        # List extensions
        for ext in _cached_extensions:
            box = layout.box()

            # Header
            name = ext.get("name", ext.get("id", "Unknown"))
            version = ext.get("version", "")
            header = f"{name}"
            if version:
                header += f" v{version}"
            box.label(text=header, icon='PACKAGE')

            # Error?
            if "_error" in ext:
                box.label(text=ext["_error"], icon='ERROR')
                continue

            # Description
            desc = ext.get("description", "")
            if desc:
                # Wrap long descriptions
                words = desc.split()
                line = ""
                for word in words:
                    if len(line) + len(word) > 50:
                        box.label(text=line)
                        line = word
                    else:
                        line = f"{line} {word}" if line else word
                if line:
                    box.label(text=line)

            # VRAM
            vram = ext.get("vram_gb")
            if vram:
                box.label(text=f"VRAM: ~{vram} GB", icon='MEMORY')

            # Tags
            tags = ext.get("tags", [])
            if tags:
                box.label(text=f"Tags: {', '.join(tags)}")

            # Nodes
            nodes = ext.get("nodes", [])
            download_status = _check_model_downloaded(ext)

            if nodes:
                col = box.column(align=True)
                for node in nodes:
                    node_id = node.get("id", "")
                    node_name = node.get("name", node_id)
                    is_downloaded = download_status.get(node_id, False)

                    row = col.row()
                    if is_downloaded:
                        row.label(text=f"  ✓ {node_name}", icon='CHECKMARK')
                    else:
                        row.label(text=f"  ✗ {node_name} (not downloaded)", icon='IMPORT')

            # Author
            author = ext.get("author", "")
            if author:
                box.label(text=f"Author: {author}")

        # Help text
        layout.separator()
        box = layout.box()
        box.label(text="To install new models:", icon='HELP')
        box.label(text="Open the Modly desktop app →")
        box.label(text="Models page → Install/Download")


class MODLY_PT_models_viewport(bpy.types.Panel):
    """Modly Models & Extensions in the 3D Viewport sidebar."""

    bl_idname = "MODLY_PT_models_viewport"
    bl_label = "Modly Models"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Modly"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("modly.refresh_models", text="Refresh", icon='FILE_REFRESH')

        global _cached_extensions, _cache_valid
        if not _cache_valid:
            refresh_cache()

        if not _cached_extensions:
            layout.label(text="No extensions found — click Refresh")
            return

        for ext in _cached_extensions:
            name = ext.get("name", ext.get("id", "Unknown"))
            row = layout.row()
            if "_error" not in ext:
                row.label(text=f"✓ {name}", icon='CHECKMARK')
            else:
                row.label(text=f"✗ {name}", icon='ERROR')


# ------------------------------------------------------------------ #
# Refresh operator
# ------------------------------------------------------------------ #

class MODLY_OT_refresh_models(bpy.types.Operator):
    """Refresh the list of installed Modly extensions and models"""

    bl_idname = "modly.refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Re-scan the Modly data directory for extensions and models"

    def execute(self, context):
        refresh_cache()
        count = len(_cached_extensions)
        self.report({'INFO'}, f"Found {count} extension(s)")

        # Force UI redraw
        for area in context.screen.areas:
            area.tag_redraw()

        return {'FINISHED'}


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    MODLY_PT_models,
    MODLY_PT_models_viewport,
    MODLY_OT_refresh_models,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
