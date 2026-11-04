"""PostToolUse hook: format the file Claude just edited.

backend/ and scripts/ *.py -> ruff (import sort + format), frontend/ files -> prettier.
Uses the project's own tools (backend/.venv, frontend/node_modules) and stays silent:
a missing tool or a formatter error never blocks the edit; lint and CI still catch it.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIN = os.name == "nt"
PRETTIER_EXT = {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".md", ".html"}


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def ruff_cmd() -> list[str] | None:
    venv = ROOT / "backend" / ".venv" / ("Scripts/ruff.exe" if WIN else "bin/ruff")
    if venv.exists():
        return [str(venv)]
    if shutil.which("uv"):
        return ["uv", "run", "--project", str(ROOT / "backend"), "ruff"]
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        path = Path(payload["tool_input"]["file_path"]).resolve()
        rel = path.relative_to(ROOT).as_posix()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return
    if not path.is_file():
        return

    if path.suffix == ".py" and rel.startswith(("backend/", "scripts/")):
        ruff = ruff_cmd()
        if ruff:
            run([*ruff, "check", "--fix", "--select", "I", str(path)], ROOT / "backend")
            run([*ruff, "format", str(path)], ROOT / "backend")
    elif path.suffix in PRETTIER_EXT and rel.startswith("frontend/"):
        bin_dir = ROOT / "frontend" / "node_modules" / ".bin"
        prettier = bin_dir / ("prettier.cmd" if WIN else "prettier")
        if prettier.exists():
            run([str(prettier), "--write", "--ignore-unknown", str(path)], ROOT / "frontend")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a formatter must never break the session
        pass
