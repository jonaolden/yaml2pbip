import re
from pathlib import Path
from typing import Dict, List
from jinja2 import Environment

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Match either: (t as table) as table => OR (t as table) as table followed by newline/whitespace
SIG = re.compile(r"^\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s+as\s+table\s*\)\s+as\s+table\s*(=>|\s)", re.IGNORECASE | re.DOTALL)


def canonical_name(p: Path) -> str:
    # file stem as identifier. replace invalid chars with underscore.
    name = p.stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not IDENT.match(safe):
        safe = "_" + safe
    return safe


def validate_signature(text: str, src: Path) -> None:
    """Require a function with explicit table->table signature.

    The transform must start with:
        (t as table) as table =>
    or
        (t as table) as table
        body...
    
    The parameter name may vary, but it must be a valid identifier.
    """
    if not SIG.search(text):
        raise ValueError(f"{src}: transform must start with '(t as table) as table =>' or '(t as table) as table' followed by newline")


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


def render_transform_template(transform_text: str, context: Dict = None) -> str:
    """Render Jinja2 variable substitution in transform M-code.
    
    Transform .m files use Jinja2 for dynamic variable substitution only.
    To avoid conflicts with Power Query M syntax (which uses {{ }} in some contexts),
    transforms should wrap all non-templated M code in {% raw %} … {% endraw %} blocks.
    
    Example transform:
        (t as table) as table =>
        {% raw %}
        let
            x = Table.FromRecords({[a=1, b=2]})
        in
            Table.AddColumn({{ input_var }}, "new", (row) => row[a] * 2)
        {% endraw %}
    
    This approach:
    - Protects M syntax from accidental Jinja2 interpretation
    - Makes intent clear: what IS vs what ISN'T templated
    - Follows Jinja2 best practices for embedded code
    
    Args:
        transform_text: M code with optional {{ }} placeholders and {% raw %} blocks
        context: Dictionary with rendering context (input_var, table_name, columns, column_names)
    
    Returns:
        M code with Jinja2 variables substituted, or original text if rendering fails
    """
    if not context:
        return transform_text
    
    try:
        env = Environment()
        template = env.from_string(transform_text)
        return template.render(**context)
    except Exception:
        # Fallback: return original text if rendering fails (backward compatible)
        return transform_text


def load_transforms(dirs: List[Path], logger) -> Dict[str, str]:
    """Load transform files from directories.
    
    File naming conventions (in preference order):
    1. *.m.j2 - M code with Jinja2 templating (preferred)
    2. *.j2 - Jinja2 template (for non-M code)
    3. *.m - Legacy M code without Jinja2 support (backward compatible)
    
    Prefers .m.j2 over .j2 over .m for same transform name.
    """
    merged: Dict[str, str] = {}
    origin: Dict[str, Path] = {}
    for d in dirs:
        # Load in preference order: .m.j2 > .j2 > .m
        for pattern in ["*.m.j2", "*.j2", "*.m"]:
            for p in d.rglob(pattern):
                name = canonical_name(p)
                text = p.read_text(encoding="utf-8")
                text = text.lstrip('\ufeff')
                text = _normalize_transform(text)
                validate_signature(text, p)
                
                # Skip if already loaded (prefer higher-precedence formats)
                if name in merged:
                    logger.debug(f"skipping {p}: transform '{name}' already loaded from {origin[name]}")
                    continue
                
                merged[name] = text
                origin[name] = p
    return merged
