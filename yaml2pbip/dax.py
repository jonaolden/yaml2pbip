"""DAX template loading for calculated tables."""
import re
from pathlib import Path
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def canonical_name(p: Path) -> str:
    """Derive a canonical DAX template name from a file path.
    
    Strips the .dax extension to get the template name.
    For example, 'metadata_table.dax' becomes 'metadata_table'.
    
    Args:
        p: Path to the DAX file
        
    Returns:
        Canonical template name (e.g., 'metadata_table')
    """
    name = p.name
    
    # Strip .dax extension
    if name.endswith('.dax'):
        name = name[:-4]
    
    # Replace any invalid chars with underscore
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not IDENT.match(safe):
        safe = "_" + safe
    return safe


def load_dax_templates(dirs: List[Path], logger_instance=None) -> Dict[str, str]:
    """Load DAX template files from directories.
    
    File naming convention:
    *.dax - DAX expression files for calculated tables
    
    Later directories in the provided list take precedence over earlier ones.
    This allows model-specific DAX templates (e.g., models/NAME/dax) to
    override built-in or global templates when they share the same canonical name.
    
    Args:
        dirs: List of directories to search for DAX templates
        logger_instance: Optional logger instance for debug output
        
    Returns:
        Dictionary mapping template names to DAX expressions
        
    Example:
        Given a file 'metadata_table.dax' containing:
            INFO.VIEWTABLES()
        
        Returns:
            {'metadata_table': 'INFO.VIEWTABLES()'}
    """
    if logger_instance is None:
        logger_instance = logger
        
    merged: Dict[str, str] = {}
    origin: Dict[str, Path] = {}
    
    # Iterate directories in reverse so that later entries override earlier ones
    for d in reversed(dirs):
        if not d.exists():
            continue
            
        for p in d.rglob("*.dax"):
            name = canonical_name(p)
            text = p.read_text(encoding="utf-8")
            # Strip BOM if present
            text = text.lstrip('\ufeff')
            # Strip leading/trailing whitespace
            text = text.strip()
            
            # If we've already loaded this name from a higher-precedence dir, skip
            if name in merged:
                logger_instance.debug(f"DAX template '{name}' overridden by {origin[name]}")
                continue
            
            merged[name] = text
            origin[name] = p
            logger_instance.debug(f"Loaded DAX template '{name}' from {p}")
    
    return merged