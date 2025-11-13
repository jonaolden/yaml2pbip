"""Utilities for M code generation."""
from typing import List, Tuple


def map_datatype_to_m(datatype: str) -> str:
    """Map Pydantic DataType to M type.
    
    Args:
        datatype: DataType string from spec (e.g., 'int64', 'string', 'dateTime')
        
    Returns:
        M type string (e.g., 'Int64.Type', 'Text.Type', 'DateTime.Type')
    """
    mapping = {
        "int64": "Int64.Type",
        "decimal": "Number.Type",
        "double": "Number.Type",
        "boolean": "Logical.Type",
        "string": "Text.Type",
        "date": "Date.Type",
        "dateTime": "DateTime.Type",
        "time": "Time.Type",
        "currency": "Currency.Type",
        "variant": "Any.Type"
    }
    return mapping.get(datatype, "Any.Type")


def format_column_list(columns: List[Tuple[str, str]]) -> str:
    """Format column names for M code (e.g., for Table.SelectColumns).
    
    Args:
        columns: List of (column_name, datatype) tuples
        
    Returns:
        Formatted string like '"Col1", "Col2", "Col3"'
    """
    if not columns:
        return ""
    return ", ".join(f'"{col[0]}"' for col in columns)


def format_types_list(columns: List[Tuple[str, str]]) -> str:
    """Format column types for Table.TransformColumnTypes.
    
    Args:
        columns: List of (column_name, datatype) tuples
        
    Returns:
        Formatted string like '{"Col1", Int64.Type}, {"Col2", Text.Type}'
    """
    if not columns:
        return ""
    return ", ".join(f'{{"{name}", {map_datatype_to_m(dtype)}}}' for name, dtype in columns)


def normalize_indentation(lines: List[str], indent_level: int = 2) -> List[str]:
    """Normalize indentation of M code lines.
    
    Args:
        lines: List of code lines
        indent_level: Number of spaces for base indentation
        
    Returns:
        List of lines with normalized indentation
    """
    normalized = []
    indent = " " * indent_level
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Replace tabs with spaces and apply consistent indentation
            normalized.append(f"{indent}{stripped}")
        else:
            normalized.append("")
    
    return normalized


def ensure_trailing_comma(line: str) -> str:
    """Ensure a line ends with a comma if it doesn't already.
    
    Args:
        line: M code line
        
    Returns:
        Line with trailing comma
    """
    stripped = line.rstrip()
    if not stripped.endswith(','):
        return stripped + ','
    return line


def remove_trailing_comma(line: str) -> str:
    """Remove trailing comma from a line if present.
    
    Args:
        line: M code line
        
    Returns:
        Line without trailing comma
    """
    stripped = line.rstrip()
    if stripped.endswith(','):
        return stripped[:-1]
    return line