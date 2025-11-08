from pathlib import Path
import os
import sys
from typing import List


def default_global_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "yaml2pbip" / "transforms"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "yaml2pbip" / "transforms"
    # linux and others
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "yaml2pbip" / "transforms"


def expand_env_paths(var: str) -> List[Path]:
    raw = os.environ.get(var, "")
    if not raw:
        return []
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]


def resolve_transform_dirs(project_root: Path, cli_dirs: List[str]) -> List[Path]:
    dirs: List[Path] = []
    # 1) System/global transforms (OS specific)
    dirs.append(default_global_dir())
    # 2) Paths from environment variable (colon/semicolon separated)
    dirs.extend(expand_env_paths("YAML2PBIP_TRANSFORMS_PATH"))
    # 3) CLI-provided directories (highest precedence among non-project dirs)
    dirs.extend([Path(d).expanduser() for d in cli_dirs])

    # 4) Repository-root transforms (repo-level/global to this codebase)
    #    This allows a repository to supply common transforms that apply to
    #    all projects under the repo. Project-local transforms (below) still
    #    override these because they are appended later.
    try:
        repo_root = Path.cwd()
        repo_transforms = repo_root / "transforms"
        if repo_transforms.exists():
            # Avoid duplicating the same path if project_root is the repo root
            if repo_transforms != (project_root / "transforms"):
                dirs.append(repo_transforms)
    except Exception:
        # Be conservative on failures when computing repo root
        pass

    # 5) Project-local transforms (project-specific, highest precedence)
    local = project_root / "transforms"
    if local.exists():
        dirs.append(local)

    # keep order. later overrides earlier
    return [d for d in dirs if d.exists()]
