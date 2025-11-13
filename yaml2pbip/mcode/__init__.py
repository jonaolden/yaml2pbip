"""M code generation module for yaml2pbip.

This module provides utilities and builders for generating Power Query M code
for partitions in a source-agnostic manner.

Modules:
    utils: Type mapping and utility functions
    source_resolver: Source connection resolution and M code generation
    builder: MCodePartitionBuilder for constructing partition M code
"""

from .utils import map_datatype_to_m, format_column_list, format_types_list
from .source_resolver import generate_inline_source_mcode, parse_source_mcode
from .builder import MCodePartitionBuilder

__all__ = [
    'map_datatype_to_m',
    'format_column_list',
    'format_types_list',
    'generate_inline_source_mcode',
    'parse_source_mcode',
    'MCodePartitionBuilder',
]