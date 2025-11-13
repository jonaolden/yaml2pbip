import re
from pathlib import Path
from typing import Dict, List

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Match either:
# 1. (t as table) as table => OR (t as table) as table followed by newline/whitespace (simple transform)
# 2. (param as type) as function => (higher-order function that returns a transform)
SIG = re.compile(r"^\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s+as\s+(table|number|text|list|record|any)\s*\)\s+as\s+(table|function)\s*(=>|\s)", re.IGNORECASE | re.DOTALL)


def canonical_name(p: Path) -> str:
    """
    Derive a canonical transform name from a file path.

    Strips the '.m' extension so names like 'proper_casting.m' become 'proper_casting'.
    """
    name = p.name
    # Strip the .m extension
    if name.endswith('.m'):
        name = name[: -len('.m')]

    # Replace any remaining invalid chars with underscore
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not IDENT.match(safe):
        safe = "_" + safe
    return safe


def validate_signature(text: str, src: Path) -> None:
    """Require a function with explicit signature.

    The transform must be either:
    1. Simple transform: (t as table) as table =>
    2. Higher-order function: (param as type) as function =>
    
    Higher-order functions should return a function that accepts a table and returns a table.
    The parameter name may vary, but it must be a valid identifier.
    """
    if not SIG.search(text):
        raise ValueError(
            f"{src}: transform must start with:\n"
            "  - '(t as table) as table =>' for simple transforms, or\n"
            "  - '(param as type) as function =>' for higher-order functions (parameterized transforms)"
        )


def validate_pure_mcode(text: str, src: Path) -> None:
    """Validate that transform contains only pure M-code (no Jinja2 syntax).
    
    Args:
        text: Transform file content
        src: Source file path for error messages
        
    Raises:
        ValueError: If Jinja2 syntax is detected
    """
    if '{{' in text or '{%' in text:
        raise ValueError(
            f"{src}: Transforms must be pure M-code. "
            "Jinja2 syntax ({{, }}, {%, %}) is no longer supported. "
            "See migration guide in docs/TRANSFORM_REFACTOR_PLAN.md"
        )


def _normalize_transform(text: str) -> str:
    """Normalize transform text to ensure it's an anonymous function usable inline.

    Handles variants where a transform file uses a signature followed by a 'let'
    block but omits the '=>' token. In that case we insert the '=>' after the
    signature line so the text becomes a valid anonymous function expression.
    """
    if '\n' not in text:
        return text
    
    # Split at first newline to check signature line
    first_line, rest = text.split('\n', 1)
    
    # Check if first line is a signature without '=>' and rest has 'let'
    if first_line.strip().startswith('(') and '=>' not in first_line and 'let' in rest:
        return first_line + ' =>\n' + rest
    
    return text




def load_transforms(dirs: List[Path], logger) -> Dict[str, str]:
    """Load transform files from directories.

    File naming conventions:
    *.m - Pure M-code functions (no Jinja2 templating)

    Later directories in the provided list take precedence over earlier ones.
    This allows model-specific transforms (e.g. models/NAME/transforms) to
    override built-in or global transforms when they share the same canonical name.
    """
    merged: Dict[str, str] = {}
    origin: Dict[str, Path] = {}

    # Iterate directories in reverse so that later entries override earlier ones.
    # Example: if dirs == [global_transforms, model_transforms], model_transforms
    # will be loaded first and kept when a name collision occurs.
    for d in reversed(dirs):
        # Load .m files (pure M-code)
        for pattern in ["*.m"]:
            for p in d.rglob(pattern):
                name = canonical_name(p)
                text = p.read_text(encoding="utf-8")
                text = text.lstrip('\ufeff')
                text = _normalize_transform(text)
                
                # Validate pure M-code (no Jinja2)
                validate_pure_mcode(text, p)
                validate_signature(text, p)

                # If we've already loaded this name from a higher-precedence dir,
                # skip the current file.
                if name in merged:
                    logger.debug(f"Transformation '{name}' overwritten by {origin[name]}")
                    continue

                merged[name] = text
                origin[name] = p
    return merged
