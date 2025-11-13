"""Source connection resolution and M code generation using templates."""
from pathlib import Path
from typing import Tuple, List
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..spec import Source


def _get_jinja_env() -> Environment:
    """Create and configure Jinja2 environment for template rendering.
    
    Searches all subdirectories under templates/ to allow organizing templates
    into subfolders (e.g., templates/sources/snowflake.j2).
    
    Returns:
        Configured Jinja2 Environment with templates loaded from yaml2pbip/templates/
    """
    template_dir = Path(__file__).parent.parent / "templates"
    
    # Collect all directories under templates (root + subdirs)
    search_paths = [str(template_dir)]
    for p in template_dir.rglob("*"):
        if p.is_dir():
            search_paths.append(str(p))
    
    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True
    )
    return env


def generate_inline_source_mcode(source: Source, source_key: str, inline: bool = True) -> str:
    """Generate M code for a source connection using the appropriate template.
    
    When inline=True, uses inline templates (e.g., snowflake_inline.j2) that generate
    just the connection function call without let...in wrapper. This is used for
    embedding source connections directly into partition M code.
    
    When inline=False, uses standard templates that include variable assignments.
    
    Args:
        source: Source specification
        source_key: Key name for the source
        inline: If True, generate inline connection code; if False, use standard template
        
    Returns:
        M code string for the source connection
    """
    env = _get_jinja_env()
    
    # Try inline template first if requested
    if inline:
        inline_template_name = f"sources/{source.kind}_inline.j2"
        try:
            template = env.get_template(inline_template_name)
            return template.render(src=source, source_key=source_key).strip()
        except Exception:
            # Fall back to standard template and extract inline code
            pass
    
    # Use standard template
    template_name = f"sources/{source.kind}.j2"
    template = env.get_template(template_name)
    mcode = template.render(src=source, source_key=source_key)
    
    if inline:
        # Extract just the connection call from standard template
        return _extract_inline_from_standard(mcode, source)
    
    return mcode


def _extract_inline_from_standard(mcode: str, source: Source) -> str:
    """Extract inline connection call from standard template M code.
    
    Standard templates have structure:
        let
            Source = Connection.Call(...),
            Database = ...
        in
            Database/Source
    
    This extracts just the Connection.Call(...) part for inline use.
    
    Args:
        mcode: Full M code from standard template
        source: Source specification
        
    Returns:
        Just the connection function call
    """
    lines = mcode.strip().split('\n')
    
    # Find the Source = ... line
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('Source ='):
            # Extract everything after 'Source = ' and before any trailing comma
            call = stripped[len('Source ='):].strip()
            if call.endswith(','):
                call = call[:-1]
            return call
    
    # If we can't parse it, return the whole thing (fallback)
    return mcode


def parse_source_mcode(mcode: str) -> Tuple[List[str], str]:
    """Parse source M code into variable definitions and final variable name.
    
    Standard source templates generate code like:
        let
            Source = Excel.Workbook(...),
            Sheet = Source{[Item="sheet1",Kind="Table"]}[Data]
        in
            Sheet
    
    This function extracts:
        - Variable definition lines (between 'let' and 'in')
        - Final variable name (after 'in')
    
    Args:
        mcode: M code string from source template
        
    Returns:
        Tuple of (variable_definition_lines, final_variable_name)
        
    Example:
        >>> mcode = 'let\\n  Source = Excel.Workbook(...),\\n  Sheet = ...\\nin\\n  Sheet'
        >>> parse_source_mcode(mcode)
        (['Source = Excel.Workbook(...),', 'Sheet = ...'], 'Sheet')
    """
    lines = mcode.strip().split('\n')
    definitions = []
    final_var = None
    in_definitions = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped == 'let':
            in_definitions = True
            continue
        elif stripped.startswith('in'):
            in_definitions = False
            continue
        elif not in_definitions and final_var is None and stripped:
            # This is the final variable returned by the source
            final_var = stripped
        elif in_definitions and stripped:
            # Variable definition - normalize indentation and ensure comma
            normalized = line.replace('\t', '  ').strip()
            definitions.append(normalized)
    
    # Default final var if not found
    if final_var is None:
        final_var = "Source"
    
    return definitions, final_var


def resolve_database_navigation(source: Source, source_key: str, database: str | None) -> List[str]:
    """Generate M code lines for database navigation.
    
    Creates lines like:
        SourceColl = Snowflake.Databases(...),
        DB = SourceColl{[Name = "DATABASE", Kind = "Database"]}[Data],
    
    Args:
        source: Source specification
        source_key: Source key name
        database: Database name to navigate to (from source or partition navigation)
        
    Returns:
        List of M code lines for database navigation
    """
    if not database:
        return []
    
    lines = []
    
    # Generate inline source connection call
    connection_call = generate_inline_source_mcode(source, source_key, inline=True)
    
    lines.append(f'  SourceColl = {connection_call},')
    lines.append(f'  DB = SourceColl{{[Name = "{database}", Kind = "Database"]}}[Data],')
    
    return lines