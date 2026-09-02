"""
Non-undo-tracked job state storage.

Blender's undo system can revert node properties mid-flight, so critical
run state is stored here (at module level) rather than solely in mutable
node custom properties.  Keyed by run_id.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class JobState:
    """Tracks the lifecycle of a single backend generation job."""

    run_id: str
    node_name: str = ""          # Name of the Blender node that owns this job
    tree_name: str = ""          # Name of the owning ModlyNodeTree
    status: str = "pending"      # pending | running | completed | failed | cancelled
    progress: int = 0            # 0–100
    step: str = ""               # Human-readable current step description
    output_url: Optional[str] = None   # Local path to result GLB on completion
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = time.monotonic()


# ------------------------------------------------------------------ #
# Global registry — survives undo, lives for the Blender session
# ------------------------------------------------------------------ #

_jobs: Dict[str, JobState] = {}


def create_job(run_id: str, node_name: str = "", tree_name: str = "") -> JobState:
    """Register a new job and return its state object."""
    job = JobState(run_id=run_id, node_name=node_name, tree_name=tree_name)
    _jobs[run_id] = job
    return job


def get_job(run_id: str) -> Optional[JobState]:
    """Look up a job by run_id.  Returns None if not found."""
    return _jobs.get(run_id)


def update_job(run_id: str, **kwargs) -> Optional[JobState]:
    """Update fields on an existing job.  Returns the job or None."""
    job = _jobs.get(run_id)
    if job is not None:
        job.update(**kwargs)
    return job


def remove_job(run_id: str) -> None:
    """Remove a job from the registry."""
    _jobs.pop(run_id, None)


def all_jobs() -> Dict[str, JobState]:
    """Return the full jobs dict (read-only intent)."""
    return _jobs


def active_jobs() -> Dict[str, JobState]:
    """Return only non-terminal jobs."""
    return {rid: j for rid, j in _jobs.items() if not j.is_terminal}


def purge_old(max_age_seconds: float = 1800.0) -> int:
    """Remove terminal jobs older than *max_age_seconds*.  Returns count purged."""
    cutoff = time.monotonic() - max_age_seconds
    stale = [rid for rid, j in _jobs.items() if j.is_terminal and j.updated_at < cutoff]
    for rid in stale:
        del _jobs[rid]
    return len(stale)
