"""
Shared subprocess-resolution helpers for the video render pipeline. Kept in their
own tiny module so render.py and codegen.py (and Phase 2's Lambda backend) can each
import from here without importing each other.
"""

from __future__ import annotations

import shutil


def npx_executable() -> str:
    """Resolve the `npx` executable's full path via PATH/PATHEXT. Windows'
    CreateProcess (unlike a shell) does not search PATHEXT for a bare "npx" when
    npx is actually npx.cmd, so `shutil.which` (which does the PATHEXT search) must
    resolve it before handing the path to `create_subprocess_exec`."""
    return shutil.which("npx") or "npx"


def node_executable() -> str:
    """Resolve `node` the same way as `npx_executable`, for the Lambda trigger
    scripts (workflow/video/lambda_render.py), which invoke plain Node scripts
    rather than an npx-resolved CLI package."""
    return shutil.which("node") or "node"
