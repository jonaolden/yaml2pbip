import re
from pathlib import Path
from typing import Dict, List

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def canonical_name(p: Path) -> str:
    # file stem as identifier. replace invalid chars with underscore.
    name = p.stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not IDENT.match(safe):
        safe = "_" + safe
    return safe


def validate_signature(text: str) -> None:
    # cheap check. require a function taking a table and returning a table
    lower = text.lower()
    if "as table" not in lower:
        raise ValueError("Transform must be a function with signature '(t as table) as table =>' or contain 'as table'")


def load_transforms(dirs: List[Path], logger) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    origin: Dict[str, Path] = {}
    for d in dirs:
        for p in d.rglob("*.m"):
            name = canonical_name(p)
            text = p.read_text(encoding="utf-8")
            validate_signature(text)
            if name in merged:
                logger.info(f"transform '{name}' overridden by {p} (was {origin[name]})")
            merged[name] = text
            origin[name] = p
    return merged
