import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

REMOTION_ROOT = Path(__file__).parent.parent

# On Windows npx lives as npx.cmd — shutil.which resolves it via PATHEXT
_NPX = shutil.which("npx") or "npx"
OUT_DIR = REMOTION_ROOT / "out"

# The TypeScript entry that calls registerRoot().
# The Remotion CLI only accepts an HTTP serve-URL or a TS/JS source entry —
# it cannot take a pre-built build/index.html as a file path.
_ENTRY = str(REMOTION_ROOT / "src" / "index.ts")


def render_video(props: dict, job_id: str | None = None) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    filename = f"{job_id or uuid.uuid4()}.mp4"
    output_path = OUT_DIR / filename

    # Write props to a temp file to avoid shell-quoting issues
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(props, f, ensure_ascii=False)
        props_path = f.name

    cmd = [
        _NPX, "remotion", "render",
        _ENTRY, "MyComp", str(output_path),
        f"--props={props_path}",
        "--log=error",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=REMOTION_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        Path(props_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"Remotion render failed (exit {result.returncode}):\n{result.stderr}"
        )

    return output_path
