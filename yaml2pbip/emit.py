"""TMDL emission functions for yaml2pbip."""
from pathlib import Path
from typing import Dict, List
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json
import uuid
import logging

from .spec import ModelBody, Table, Partition, SourcesSpec, Source
from .mcode import MCodePartitionBuilder
from .mcode.source_resolver import generate_inline_source_mcode

logger = logging.getLogger(__name__)


def _generate_lineage_tag() -> str:
    """Generate a UUID for Power BI lineage tracking.
    
    Returns:
        UUID string in format like '6bfd7976-09ca-7046-4a83-0c3085609e3c'
    """
    return str(uuid.uuid4())


def _get_jinja_env() -> Environment:
    """Create and configure Jinja2 environment for template rendering.
    
    Searches all subdirectories under templates/ to allow organizing templates
    into subfolders (e.g., templates/sources/snowflake.j2).
    
    Returns:
        Configured Jinja2 Environment with templates loaded from yaml2pbip/templates/
    """
    template_dir = Path(__file__).parent / "templates"
    
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
    # Add custom function for generating lineage tags
    env.globals['generate_lineage_tag'] = _generate_lineage_tag
    return env



def emit_pbism(sm_dir: Path) -> None:
    """Create definition.pbism to mark directory as TMDL project.
    
    Args:
        sm_dir: Path to SemanticModel directory
    """
    sm_dir.mkdir(parents=True, exist_ok=True)
    pbism_content = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2",
        "settings": {}
    }
    (sm_dir / "definition.pbism").write_text(json.dumps(pbism_content, indent=2))


def emit_model_tmdl(def_dir: Path, model: ModelBody) -> None:
    """Render and write model.tmdl with model-level properties.
    
    Args:
        def_dir: Path to definition directory
        model: ModelBody containing model properties
    """
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("model.tmdl.j2")
    content = template.render(model=model)
    (def_dir / "model.tmdl").write_text(content)


def emit_database_tmdl(def_dir: Path) -> None:
    """Render and write database.tmdl with compatibility level.
    
    Args:
        def_dir: Path to definition directory
    """
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("database.tmdl.j2")
    content = template.render()
    (def_dir / "database.tmdl").write_text(content)


def emit_culture_tmdl(def_dir: Path, culture: str) -> None:
    """Render and write culture info TMDL file.
    
    Args:
        def_dir: Path to definition directory
        culture: Culture code (e.g., 'en-US')
    """
    cultures_dir = def_dir / "cultures"
    cultures_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("culture.tmdl.j2")
    content = template.render(culture=culture)
    (cultures_dir / f"{culture}.tmdl").write_text(content)


def emit_expressions_tmdl(def_dir: Path, sources: SourcesSpec, transforms: dict | None = None) -> None:
    """Render and write expressions.tmdl with M source functions.

    Transforms are NOT emitted here - they are inlined directly into partition M code.
    """
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("expressions.tmdl.j2")
    # Do NOT emit transforms - they're inlined into partitions
    content = template.render(sources=sources.sources, transforms={})
    (def_dir / "expressions.tmdl").write_text(content)


def generate_source_mcode(source: Source, source_key: str) -> str:
    """Generate M code for a source connection using the appropriate template.
    
    This is a backward-compatible wrapper around the new source_resolver module.
    
    Args:
        source: Source specification
        source_key: Key name for the source
        
    Returns:
        M code string for the source
    """
    return generate_inline_source_mcode(source, source_key, inline=False)


def generate_partition_mcode(partition: Partition, table: Table, sources: SourcesSpec, transforms: dict | None = None) -> str:
    """Generate Power Query M code for a partition using the builder pattern.

    This function uses the MCodePartitionBuilder to construct M code in a modular,
    maintainable way. All source-specific logic is handled through Jinja2 templates.

    Args:
        partition: Partition specification
        table: Table specification containing columns and policies
        sources: SourcesSpec containing available data sources
        transforms: Optional dict of transform name -> M code

    Returns:
        Complete M code string for the partition

    Raises:
        ValueError: If partition configuration is invalid or transforms are missing
    """
    builder = MCodePartitionBuilder(partition, table, sources)
    
    # Build M code based on partition type
    if partition.navigation:
        # Navigation-based partition (database -> schema -> table)
        return (builder
                .add_source_connection()
                .add_navigation()
                .add_column_selection()
                .add_type_transformation()
                .add_custom_transforms(transforms)
                .build())
    
    elif partition.nativeQuery:
        # Native query partition (SQL executed on database)
        return (builder
                .add_source_connection()
                .add_native_query()
                .add_column_selection()
                .add_type_transformation()
                .add_custom_transforms(transforms)
                .build())
    
    else:
        # Simple source partition (e.g., Excel, CSV)
        return (builder
                .add_source_connection()
                .add_column_selection()
                .add_type_transformation()
                .add_custom_transforms(transforms)
                .build())


def emit_table_tmdl(tbl_dir: Path, table: Table, sources: SourcesSpec, transforms: dict | None = None, dax_templates: dict | None = None) -> None:
    """Render and write individual table TMDL with M code generation.
    
    Args:
        tbl_dir: Path to tables directory
        table: Table definition
        sources: SourcesSpec for partition M code generation
        transforms: optional dict of named transforms to validate and pass through
        dax_templates: optional dict of DAX template names to DAX expressions
    """
    tbl_dir.mkdir(parents=True, exist_ok=True)
    
    # Note: DAX template resolution happens in compile.py before this function is called
    # to ensure the expression is available for column property inference
    
    env = _get_jinja_env()
    template = env.get_template("table.tmdl.j2")
    
    # Generate M code only for M partitions (not entity partitions)
    partition_mcode = ""
    if table.partitions:
        first_partition = table.partitions[0]
        if first_partition.mode != "directLake":
            partition_mcode = generate_partition_mcode(first_partition, table, sources, transforms)
    
    content = template.render(
        table=table,
        partition_mcode=partition_mcode
    )
    (tbl_dir / f"{table.name}.tmdl").write_text(content)


def emit_relationships_tmdl(def_dir: Path, model: ModelBody) -> None:
    """Render and write relationships.tmdl with all model relationships.
    
    Args:
        def_dir: Path to definition directory
        model: ModelBody containing relationships
    """
    if not model.relationships:
        return  # Skip if no relationships
        
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("relationships.tmdl.j2")
    content = template.render(relationships=model.relationships)
    (def_dir / "relationships.tmdl").write_text(content)


def emit_report_by_path(rpt_dir: Path, rel_model_path: str) -> None:
    """Create stub report definition.
    
    Args:
        rpt_dir: Path to Report directory
        rel_model_path: Relative path to semantic model (e.g., "../ModelName.SemanticModel")
    """
    rpt_dir.mkdir(parents=True, exist_ok=True)
    
    pbir_content = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {
            "byPath": {
                "path": rel_model_path
            }
        }
    }
    
    (rpt_dir / "definition.pbir").write_text(json.dumps(pbir_content, indent=2))
