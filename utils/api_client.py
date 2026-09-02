"""
HTTP client for communicating with the Modly backend.

Uses only urllib (available in Blender's bundled Python) — no external deps.
All calls target localhost.
"""
from __future__ import annotations

import json
import mimetypes
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


def _base_url() -> str:
    """Get the backend base URL from addon preferences."""
    try:
        from ..preferences import get_backend_url
        return get_backend_url()
    except Exception:
        return "http://127.0.0.1:8765"


# ------------------------------------------------------------------ #
# Health
# ------------------------------------------------------------------ #

def health_check() -> bool:
    """Ping the backend.  Returns True if responsive."""
    try:
        url = f"{_base_url()}/docs"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Workflow runs
# ------------------------------------------------------------------ #

def post_workflow_run_from_image(
    image_path: str,
    model_id: str = "trellis2",
    params: Optional[Dict[str, Any]] = None,
    collection: str = "Default",
) -> Dict[str, Any]:
    """
    Submit a workflow run via the /workflow-runs/from-image endpoint.

    This is a multipart/form-data POST with an image file upload.

    Args:
        image_path: Local path to the input image.
        model_id: Modly model identifier (e.g., "trellis2").
        params: Optional model parameters dict.
        collection: Output collection/folder name.

    Returns:
        Response JSON dict containing at minimum {'run_id': '...', 'status': '...'}.

    Raises:
        RuntimeError on HTTP or connection errors.
    """
    url = f"{_base_url()}/workflow-runs/from-image"

    if params is None:
        params = {}

    # Build multipart form data manually (no requests library available)
    boundary = uuid.uuid4().hex
    content_type = f"multipart/form-data; boundary={boundary}"

    parts = []

    # Image file part
    image_filename = os.path.basename(image_path)
    mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        image_data = f.read()

    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{image_filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    )
    parts.append(image_data)
    parts.append(b"\r\n")

    # model_id field
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model_id"\r\n\r\n'
        f"{model_id}\r\n"
    )

    # collection field
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="collection"\r\n\r\n'
        f"{collection}\r\n"
    )

    # params field (JSON string)
    params_json = json.dumps(params)
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="params"\r\n\r\n'
        f"{params_json}\r\n"
    )

    # Final boundary
    parts.append(f"--{boundary}--\r\n")

    # Assemble body
    body = b""
    for part in parts:
        if isinstance(part, str):
            body += part.encode("utf-8")
        else:
            body += part

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = resp.read().decode("utf-8")
            return json.loads(response_data)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(
            f"Backend returned HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot connect to backend at {url}: {exc.reason}"
        ) from exc


# ------------------------------------------------------------------ #
# Job status polling
# ------------------------------------------------------------------ #

def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Poll the status of a generation job.

    Returns a dict with keys: status, progress, step, output_url, error, etc.
    """
    url = f"{_base_url()}/generate/status/{job_id}"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "unknown", "error": f"Job {job_id} not found"}
        error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {"status": "error", "error": f"HTTP {exc.code}: {error_body}"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------ #
# Cancellation
# ------------------------------------------------------------------ #

def cancel_job(job_id: str) -> bool:
    """
    Cancel an in-flight generation job.

    Returns True if the cancel request was accepted.
    """
    url = f"{_base_url()}/generate/cancel/{job_id}"

    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Extension / model listing
# ------------------------------------------------------------------ #

def list_extensions() -> list:
    """
    Fetch the list of installed extensions from the backend.

    Returns a list of extension info dicts, or an empty list on error.
    """
    url = f"{_base_url()}/extensions"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
            # Some backends wrap in {"extensions": [...]}
            return data.get("extensions", [])
    except Exception:
        return []


def list_models() -> list:
    """
    Fetch the list of available models from the backend.

    Returns a list of model info dicts, or an empty list on error.
    """
    url = f"{_base_url()}/models"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
            return data.get("models", [])
    except Exception:
        return []
