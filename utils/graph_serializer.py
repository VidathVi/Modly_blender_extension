"""
Graph serializer — converts a ModlyNodeTree into the backend's
workflow-run payload and determines execution order.

The graph is an orchestration graph: nodes describe *what* to submit
and in *what order*, not a per-frame compute graph.
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import bpy


@dataclass
class NodeTask:
    """A single task derived from a graph node, ready for submission."""

    node_name: str
    node_bl_idname: str
    model_id: str = ""
    image_path: str = ""            # Resolved input image path
    mesh_path: str = ""             # Resolved input mesh path (for Texture Mesh)
    prompt: str = ""                # Text prompt (for text-based generators)
    params: Dict = field(default_factory=dict)
    is_text_only: bool = False      # Trellis Text nodes need dummy image injection
    is_terminal: bool = False       # Add to Scene node
    import_mode: str = "ADD"        # ADD or REPLACE
    source_object_name: str = ""    # For REPLACE mode
    depends_on: Optional[str] = None  # node_name of upstream generator (for chaining)


def topological_sort(tree: bpy.types.NodeTree) -> List[bpy.types.Node]:
    """
    Return the nodes of *tree* in topological order (inputs first, outputs last).

    Nodes with no inputs come first; nodes whose inputs depend on other nodes'
    outputs come after their dependencies.
    """
    # Build adjacency: for each node, which nodes feed into it?
    in_degree: Dict[str, int] = {}
    dependents: Dict[str, List[str]] = {}  # node_name -> [downstream node names]

    for node in tree.nodes:
        in_degree[node.name] = 0
        dependents.setdefault(node.name, [])

    for link in tree.links:
        if not link.is_valid:
            continue
        from_name = link.from_node.name
        to_name = link.to_node.name
        in_degree[to_name] = in_degree.get(to_name, 0) + 1
        dependents.setdefault(from_name, []).append(to_name)

    # Kahn's algorithm
    queue = [name for name, deg in in_degree.items() if deg == 0]
    sorted_names: List[str] = []

    while queue:
        name = queue.pop(0)
        sorted_names.append(name)
        for dep in dependents.get(name, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Map back to node objects
    node_map = {node.name: node for node in tree.nodes}
    return [node_map[name] for name in sorted_names if name in node_map]


def _get_connected_node(node: bpy.types.Node, input_name: str) -> Optional[bpy.types.Node]:
    """Return the node connected to *input_name* on *node*, or None."""
    socket = node.inputs.get(input_name)
    if socket is None or not socket.is_linked:
        return None
    # Follow the first link
    link = socket.links[0]
    return link.from_node


def _resolve_image_path(node: bpy.types.Node) -> str:
    """
    Walk upstream from *node* to find an image path.

    Checks the node's own "Image" input socket, then follows links
    to find an Image Input node.
    """
    # Direct socket value
    img_socket = node.inputs.get("Image")
    if img_socket:
        if img_socket.is_linked:
            source_node = img_socket.links[0].from_node
            if hasattr(source_node, "get_value"):
                path = source_node.get_value()
                if path and os.path.isfile(path):
                    return path
        elif hasattr(img_socket, "default_value") and img_socket.default_value:
            path = bpy.path.abspath(img_socket.default_value)
            if os.path.isfile(path):
                return path
    return ""


def _resolve_text_prompt(node: bpy.types.Node) -> str:
    """Walk upstream to find a text prompt value."""
    prompt_socket = node.inputs.get("Prompt")
    if prompt_socket:
        if prompt_socket.is_linked:
            source_node = prompt_socket.links[0].from_node
            if hasattr(source_node, "get_value"):
                return source_node.get_value()
        elif hasattr(prompt_socket, "default_value") and prompt_socket.default_value:
            return prompt_socket.default_value
    return ""


def _resolve_mesh_path(node: bpy.types.Node) -> str:
    """Walk upstream to find a mesh file path (from Selection-In)."""
    mesh_socket = node.inputs.get("Mesh File")
    if mesh_socket and mesh_socket.is_linked:
        source_node = mesh_socket.links[0].from_node
        if hasattr(source_node, "get_value"):
            return source_node.get_value()
    return ""


def _create_dummy_image() -> str:
    """
    Create a minimal 1x1 white PNG for Trellis Text nodes.

    The TRELLIS Text extension's manifest declares image → mesh even though
    the image input is ignored.  This placeholder satisfies the backend schema.
    """
    tmp_dir = os.path.join(tempfile.gettempdir(), "modly_blender")
    os.makedirs(tmp_dir, exist_ok=True)
    dummy_path = os.path.join(tmp_dir, "dummy_placeholder.png")

    if not os.path.exists(dummy_path):
        # Minimal valid PNG: 1x1 white pixel
        # Generated via struct, no PIL needed
        import struct
        import zlib

        def _create_minimal_png():
            signature = b'\x89PNG\r\n\x1a\n'

            # IHDR
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc & 0xffffffff)

            # IDAT (1x1 RGB white pixel)
            raw_data = b'\x00\xff\xff\xff'  # filter byte + RGB
            compressed = zlib.compress(raw_data)
            idat_crc = zlib.crc32(b'IDAT' + compressed)
            idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc & 0xffffffff)

            # IEND
            iend_crc = zlib.crc32(b'IEND')
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc & 0xffffffff)

            return signature + ihdr + idat + iend

        with open(dummy_path, "wb") as f:
            f.write(_create_minimal_png())

    return dummy_path


def serialize_graph(
    tree: bpy.types.NodeTree,
    context: bpy.types.Context,
) -> List[NodeTask]:
    """
    Convert a ModlyNodeTree into an ordered list of NodeTasks.

    Each generator node becomes a task.  Input nodes are resolved into
    file paths / text values.  The Add to Scene node is marked as terminal.

    For Trellis Text nodes, a dummy image is injected automatically
    (the backend requires an image field even though the extension ignores it).

    Args:
        tree: The ModlyNodeTree to serialize.
        context: Current Blender context (needed for Selection-In export).

    Returns:
        Ordered list of NodeTask objects ready for sequential submission.
    """
    sorted_nodes = topological_sort(tree)
    tasks: List[NodeTask] = []

    for node in sorted_nodes:
        bl_idname = node.bl_idname

        # --- Input nodes: handle during generator resolution ---
        if bl_idname in ("ModlyImageInputNode", "ModlyTextPromptNode", "ModlySelectionInNode"):
            # Selection-In needs to export at this point
            if bl_idname == "ModlySelectionInNode":
                node.export_selection(context)
            continue

        # --- Generator nodes ---
        if bl_idname in (
            "ModlyGenerateMeshNode",
            "ModlyTextureMeshNode",
            "ModlyTrellisTextBaseNode",
            "ModlyTrellisTextLargeNode",
            "ModlyTrellisTextXLNode",
        ):
            task = NodeTask(
                node_name=node.name,
                node_bl_idname=bl_idname,
                model_id=node.get_model_id(),
                params=node.get_params(),
                is_text_only=getattr(node, "is_text_only", False),
            )

            # Resolve image input
            task.image_path = _resolve_image_path(node)

            # Resolve text prompt
            task.prompt = _resolve_text_prompt(node)
            if task.prompt:
                task.params["prompt"] = task.prompt

            # Resolve mesh input (Texture Mesh)
            task.mesh_path = _resolve_mesh_path(node)

            # Check for upstream generator dependency (Job socket)
            job_socket = node.inputs.get("Mesh Job") or node.inputs.get("Job")
            if job_socket and job_socket.is_linked:
                upstream = job_socket.links[0].from_node
                task.depends_on = upstream.name

            # Trellis Text: inject dummy image if no real image provided
            if task.is_text_only and not task.image_path:
                task.image_path = _create_dummy_image()

            tasks.append(task)

        # --- Terminal (output) nodes ---
        elif bl_idname == "ModlyAddToSceneNode":
            task = NodeTask(
                node_name=node.name,
                node_bl_idname=bl_idname,
                is_terminal=True,
                import_mode=node.import_mode,
            )

            # Find which generator feeds into this
            job_socket = node.inputs.get("Job")
            if job_socket and job_socket.is_linked:
                upstream = job_socket.links[0].from_node
                task.depends_on = upstream.name

            # For Replace mode: find the source object from Selection-In
            if node.import_mode == "REPLACE":
                # Walk upstream to find a Selection-In node
                task.source_object_name = _find_source_object_name(tree, node)

            tasks.append(task)

    return tasks


def _find_source_object_name(tree: bpy.types.NodeTree, terminal_node: bpy.types.Node) -> str:
    """
    Walk upstream from a terminal node to find a Selection-In node
    and return the name of the active object it exported.
    """
    visited = set()
    queue = [terminal_node]

    while queue:
        node = queue.pop(0)
        if node.name in visited:
            continue
        visited.add(node.name)

        if node.bl_idname == "ModlySelectionInNode":
            # The Selection-In node was run during serialization;
            # we can try to get the object name from context
            try:
                return bpy.context.active_object.name if bpy.context.active_object else ""
            except Exception:
                return ""

        # Follow input links upstream
        for inp in node.inputs:
            for link in inp.links:
                if link.is_valid:
                    queue.append(link.from_node)

    return ""
