"""
Graph execution operators — Run Graph, Poll Jobs, Cancel Job.

Run Graph:
  1. Topologically sorts the active ModlyNodeTree
  2. Serializes each node into the backend payload
  3. Submits tasks sequentially (respecting dependencies)
  4. Starts a modal timer for non-blocking status polling

Poll Jobs:
  Modal timer operator that checks job status every 500ms,
  updates node visuals, and triggers imports on completion.

Cancel Job:
  Cancels an in-flight generation run.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import bpy

from .. import job_registry
from ..utils import api_client
from ..utils.graph_serializer import NodeTask, serialize_graph

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Run Graph
# ------------------------------------------------------------------ #

class MODLY_OT_run_graph(bpy.types.Operator):
    """Run the active Modly node graph — submits jobs to the backend"""

    bl_idname = "modly.run_graph"
    bl_label = "Run Graph"
    bl_description = "Submit the active Modly node graph for AI generation"

    @classmethod
    def poll(cls, context):
        # Must have an active Modly node tree
        space = context.space_data
        if not space or not hasattr(space, 'edit_tree'):
            return False
        tree = space.edit_tree
        return tree is not None and tree.bl_idname == "ModlyNodeTree"

    def execute(self, context):
        from ..backend import process_manager

        # Check backend is running
        if not process_manager.is_running():
            self.report({'ERROR'}, "Backend is not running — start it first")
            return {'CANCELLED'}

        if not process_manager.health_check():
            self.report({'ERROR'}, "Backend is not responding — check status")
            return {'CANCELLED'}

        tree = context.space_data.edit_tree

        # Serialize the graph
        try:
            tasks = serialize_graph(tree, context)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if not tasks:
            self.report({'WARNING'}, "No generator nodes found in the graph")
            return {'CANCELLED'}

        # Filter to generator tasks (not terminal nodes)
        gen_tasks = [t for t in tasks if not t.is_terminal]
        if not gen_tasks:
            self.report({'WARNING'}, "No generator nodes to run")
            return {'CANCELLED'}

        # Submit the first task (or all independent tasks)
        # For now, submit tasks sequentially — the poller handles chaining
        first_task = gen_tasks[0]

        try:
            self._submit_task(first_task, tree)
        except RuntimeError as exc:
            self.report({'ERROR'}, f"Submission failed: {exc}")
            return {'CANCELLED'}

        # Store all tasks for the poller to process
        context.window_manager["modly_pending_tasks"] = _serialize_tasks(tasks)
        context.window_manager["modly_active_tree"] = tree.name

        # Start the poller
        bpy.ops.modly.poll_jobs('INVOKE_DEFAULT')

        self.report({'INFO'}, f"Job submitted: {first_task.node_name}")
        return {'FINISHED'}

    def _submit_task(self, task: NodeTask, tree: bpy.types.NodeTree) -> str:
        """Submit a single task to the backend.  Returns the run_id."""

        if not task.image_path:
            raise RuntimeError(
                f"Node '{task.node_name}' has no image input. "
                "Connect an Image Input or Text Prompt node."
            )

        # Extract model_id parts: "extension_id:node_id" -> just extension_id for the API
        model_id = task.model_id.split(":")[0] if ":" in task.model_id else task.model_id

        response = api_client.post_workflow_run_from_image(
            image_path=task.image_path,
            model_id=model_id,
            params=task.params,
        )

        run_id = response.get("run_id") or response.get("job_id", "")
        if not run_id:
            raise RuntimeError(f"Backend did not return a run_id: {response}")

        # Register in our undo-safe registry
        job_registry.create_job(
            run_id=run_id,
            node_name=task.node_name,
            tree_name=tree.name,
        )

        # Update the node's display properties
        node = tree.nodes.get(task.node_name)
        if node:
            node.run_id = run_id
            node.status_text = "Submitted"
            node.progress = 0
            if hasattr(node, 'update_status_color'):
                node.update_status_color("running")

        return run_id


# ------------------------------------------------------------------ #
# Poll Jobs (Modal Timer)
# ------------------------------------------------------------------ #

class MODLY_OT_poll_jobs(bpy.types.Operator):
    """
    Non-blocking modal timer that polls active job statuses.

    Uses wm.event_timer_add() to check every 500ms without freezing the UI.
    """

    bl_idname = "modly.poll_jobs"
    bl_label = "Poll Jobs"
    bl_options = {'INTERNAL'}

    _timer = None

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        active = job_registry.active_jobs()

        if not active:
            # All jobs done — clean up
            self._cleanup(context)
            return {'FINISHED'}

        tree_name = context.window_manager.get("modly_active_tree", "")
        tree = bpy.data.node_groups.get(tree_name)

        for run_id, job in list(active.items()):
            # Poll the backend
            status_data = api_client.get_job_status(run_id)

            backend_status = status_data.get("status", "unknown")
            progress = status_data.get("progress", 0)
            step = status_data.get("step", "")
            output_url = status_data.get("output_url", "")
            error = status_data.get("error", "")

            # Map backend status to our status
            if backend_status in ("completed", "complete", "done"):
                job_registry.update_job(
                    run_id,
                    status="completed",
                    progress=100,
                    output_url=output_url,
                    step="Complete",
                )
                self._on_job_complete(context, tree, job, output_url)

            elif backend_status in ("failed", "error"):
                job_registry.update_job(
                    run_id,
                    status="failed",
                    error=error or "Unknown error",
                    step="Failed",
                )
                self._update_node_display(tree, job.node_name, "failed", error or "Failed")

            elif backend_status == "cancelled":
                job_registry.update_job(run_id, status="cancelled", step="Cancelled")
                self._update_node_display(tree, job.node_name, "cancelled", "Cancelled")

            else:
                # Still running
                job_registry.update_job(
                    run_id,
                    status="running",
                    progress=progress,
                    step=step or f"Running ({progress}%)",
                )
                self._update_node_display(
                    tree, job.node_name, "running",
                    step or f"Running ({progress}%)",
                    progress,
                )

        # Force redraw of node editor areas
        for area in context.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()

        return {'RUNNING_MODAL'}

    def execute(self, context):
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._cleanup(context)

    def _cleanup(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def _update_node_display(
        self,
        tree: Optional[bpy.types.NodeTree],
        node_name: str,
        status: str,
        text: str,
        progress: int = 0,
    ):
        """Update a node's visual status in the graph."""
        if tree is None:
            return
        node = tree.nodes.get(node_name)
        if node is None:
            return

        node.status_text = text
        if hasattr(node, 'progress'):
            node.progress = progress
        if hasattr(node, 'update_status_color'):
            node.update_status_color(status)

    def _on_job_complete(
        self,
        context: bpy.types.Context,
        tree: Optional[bpy.types.NodeTree],
        job: job_registry.JobState,
        output_url: str,
    ):
        """Handle a completed job — trigger downstream imports."""
        self._update_node_display(tree, job.node_name, "completed", "Complete ✓", 100)

        if tree is None:
            return

        # Find Add to Scene nodes connected to this generator
        gen_node = tree.nodes.get(job.node_name)
        if gen_node is None:
            return

        # Check if we need to submit a chained task
        # (e.g., Generate Mesh -> Texture Mesh chain)
        pending_raw = context.window_manager.get("modly_pending_tasks")
        if pending_raw:
            pending_tasks = _deserialize_tasks(pending_raw)
            for task in pending_tasks:
                if task.depends_on == job.node_name and not task.is_terminal:
                    # This task depends on the completed job — submit it
                    # The output of the previous job becomes the mesh input
                    if output_url:
                        task.mesh_path = output_url
                        # For chained image-based tasks, use the output as input
                        if not task.image_path:
                            task.image_path = output_url
                    try:
                        run_op = MODLY_OT_run_graph()
                        run_op._submit_task(task, tree)
                    except Exception as exc:
                        log.error(f"Failed to submit chained task: {exc}")

        # Find downstream Add to Scene nodes and trigger import
        for output in gen_node.outputs:
            for link in output.links:
                downstream = link.to_node
                if downstream.bl_idname == "ModlyAddToSceneNode" and output_url:
                    if downstream.auto_import:
                        # Resolve the output file path
                        file_path = self._resolve_output_path(output_url)
                        if file_path:
                            source_obj_name = ""
                            if downstream.import_mode == "REPLACE":
                                # Try to find the source object name
                                source_obj_name = _find_upstream_selection_object(tree, downstream)
                            downstream.import_result(context, file_path, source_obj_name)
                    else:
                        downstream.output_path = output_url
                        downstream.status_text = "Ready to import — click Import"

    @staticmethod
    def _resolve_output_path(output_url: str) -> str:
        """
        Resolve an output_url from the backend to a local file path.

        The backend may return a relative URL path — resolve it against
        the workspace directory.
        """
        import os
        from ..preferences import get_workspace_dir

        if os.path.isfile(output_url):
            return output_url

        # Try as a path relative to workspace
        workspace = get_workspace_dir()
        candidate = workspace / output_url.lstrip("/")
        if candidate.is_file():
            return str(candidate)

        # Try stripping a /files/ prefix the backend sometimes uses
        if output_url.startswith("/files/"):
            candidate = workspace / output_url[7:]
            if candidate.is_file():
                return str(candidate)

        return output_url  # Return as-is, import_result will handle the error


def _find_upstream_selection_object(tree: bpy.types.NodeTree, node: bpy.types.Node) -> str:
    """Walk upstream to find a Selection-In node's source object name."""
    visited = set()
    queue = [node]
    while queue:
        current = queue.pop(0)
        if current.name in visited:
            continue
        visited.add(current.name)
        if current.bl_idname == "ModlySelectionInNode":
            try:
                return bpy.context.active_object.name if bpy.context.active_object else ""
            except Exception:
                return ""
        for inp in current.inputs:
            for link in inp.links:
                if link.is_valid:
                    queue.append(link.from_node)
    return ""


# ------------------------------------------------------------------ #
# Cancel Job
# ------------------------------------------------------------------ #

class MODLY_OT_cancel_job(bpy.types.Operator):
    """Cancel an in-flight generation job"""

    bl_idname = "modly.cancel_job"
    bl_label = "Cancel Job"
    bl_description = "Cancel the currently running AI generation"

    run_id: bpy.props.StringProperty(name="Run ID", default="")

    def execute(self, context):
        if not self.run_id:
            # Cancel all active jobs
            active = job_registry.active_jobs()
            if not active:
                self.report({'INFO'}, "No active jobs to cancel")
                return {'CANCELLED'}
            for rid in active:
                api_client.cancel_job(rid)
                job_registry.update_job(rid, status="cancelled")
            self.report({'INFO'}, f"Cancelled {len(active)} job(s)")
        else:
            ok = api_client.cancel_job(self.run_id)
            if ok:
                job_registry.update_job(self.run_id, status="cancelled")
                self.report({'INFO'}, f"Job {self.run_id[:8]}… cancelled")
            else:
                self.report({'WARNING'}, f"Could not cancel job {self.run_id[:8]}…")

        return {'FINISHED'}


# ------------------------------------------------------------------ #
# Task serialization helpers (for passing between operators via WM props)
# ------------------------------------------------------------------ #

def _serialize_tasks(tasks: List[NodeTask]) -> str:
    """Serialize tasks to a JSON string for storage in window_manager."""
    import json
    return json.dumps([
        {
            "node_name": t.node_name,
            "node_bl_idname": t.node_bl_idname,
            "model_id": t.model_id,
            "image_path": t.image_path,
            "mesh_path": t.mesh_path,
            "prompt": t.prompt,
            "params": t.params,
            "is_text_only": t.is_text_only,
            "is_terminal": t.is_terminal,
            "import_mode": t.import_mode,
            "source_object_name": t.source_object_name,
            "depends_on": t.depends_on or "",
        }
        for t in tasks
    ])


def _deserialize_tasks(raw: str) -> List[NodeTask]:
    """Deserialize tasks from a JSON string."""
    import json
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    tasks = []
    for d in data:
        tasks.append(NodeTask(
            node_name=d.get("node_name", ""),
            node_bl_idname=d.get("node_bl_idname", ""),
            model_id=d.get("model_id", ""),
            image_path=d.get("image_path", ""),
            mesh_path=d.get("mesh_path", ""),
            prompt=d.get("prompt", ""),
            params=d.get("params", {}),
            is_text_only=d.get("is_text_only", False),
            is_terminal=d.get("is_terminal", False),
            import_mode=d.get("import_mode", "ADD"),
            source_object_name=d.get("source_object_name", ""),
            depends_on=d.get("depends_on") or None,
        ))
    return tasks


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

classes = (
    MODLY_OT_run_graph,
    MODLY_OT_poll_jobs,
    MODLY_OT_cancel_job,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
