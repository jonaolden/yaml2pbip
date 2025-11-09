import re
from pathlib import Path
from typing import Dict, List

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SIG = re.compile(r"^\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s+as\s+table\s*\)\s+as\s+table\s*=>", re.IGNORECASE | re.DOTALL)


def canonical_name(p: Path) -> str:
    # file stem as identifier. replace invalid chars with underscore.
    name = p.stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not IDENT.match(safe):
        safe = "_" + safe
    return safe


def validate_signature(text: str, src: Path) -> None:
    """Require a function with explicit table->table signature.

    After normalization, the transform must start with:
        (t as table) as table =>
    The parameter name may vary, but it must be a valid identifier.
    """
    if not SIG.search(text):
        raise ValueError(f"{src}: transform must start with '(t as table) as table >='")


def _normalize_transform(text: str) -> str:
    """Normalize transform text to ensure it's an anonymous function usable inline.

    Handles variants where a transform file uses a signature followed by a 'let'
    block but omits the '=>' token. In that case we insert the '=>' after the
    signature line so the text becomes a valid anonymous function expression.
    """
    if '=>' in text:
        return text
    if '\n' not in text:
        return text
    first_line, rest = text.split('\n', 1)
    if first_line.strip().startswith('(') and 'let' in rest:
        return first_line + ' =>\n' + rest
    return text


def load_transforms(dirs: List[Path], logger) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    origin: Dict[str, Path] = {}
    for d in dirs:
        for p in d.rglob("*.m"):
            name = canonical_name(p)
            text = p.read_text(encoding="utf-8")
            text = text.lstrip('\ufeff')
            text = _normalize_transform(text)
            validate_signature(text, p)
            if name in merged:
                logger.info(f"transform '{name}' overridden by {p} (was {origin[name]})")
            merged[name] = text
            origin[name] = p
    return merged
