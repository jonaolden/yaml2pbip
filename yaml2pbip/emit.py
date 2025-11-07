"""TMDL emission functions for yaml2pbip."""
from pathlib import Path
from typing import Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json

from .spec import ModelBody, Table, Partition, SourcesSpec, Source


def _get_jinja_env() -> Environment:
    """Create and configure Jinja2 environment for template rendering.
    
    Returns:
        Configured Jinja2 Environment with templates loaded from yaml2pbip/templates/
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True
    )
    return env


def emit_pbism(sm_dir: Path) -> None:
    """Create definition.pbism to mark directory as TMDL project.
    
    Args:
        sm_dir: Path to SemanticModel directory
    """
    sm_dir.mkdir(parents=True, exist_ok=True)
    pbism_content = {
        "version": "1.0",
        "type": "pbi-semantic-model"
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


def emit_expressions_tmdl(def_dir: Path, sources: SourcesSpec) -> None:
    """Render and write expressions.tmdl with M source functions.
    
    Args:
        def_dir: Path to definition directory
        sources: SourcesSpec containing all source definitions
    """
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("expressions.tmdl.j2")
    content = template.render(sources=sources.sources)
    (def_dir / "expressions.tmdl").write_text(content)


def generate_partition_mcode(partition: Partition, table: Table, sources: SourcesSpec) -> str:
    """Generate Power Query M code for a partition with column policy logic.
    
    Args:
        partition: Partition definition
        table: Table containing the partition
        sources: SourcesSpec for source resolution
        
    Returns:
        M code string for the partition
    """
    source_key = partition.use or (table.source and table.source.get("use"))
    if not source_key:
        raise ValueError(f"Partition {partition.name} in table {table.name} has no source specified")
    
    source = sources.sources.get(source_key)
    if not source:
        raise ValueError(f"Source {source_key} not found in sources")
    
    # Build column list for type transformation
    declared_cols = [(col.name, col.dataType) for col in table.columns]
    
    # Generate M code based on partition type
    if partition.navigation:
        nav = partition.navigation
        database = nav.database or (source.database if source.database else "null")
        
        # Start with navigation M code
        lines = [
            "let",
            f'  DB = Source.{source_key}("{database}"),',
            f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],',
            f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],'
        ]
        
        # Apply column policy
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(TBL, {{{col_names}}}, MissingField.UseNull),")
            
            # Add type transformations
            type_specs = ", ".join(f'{{"{col[0]}", type {_map_datatype_to_m(col[1])}}}' for col in declared_cols)
            lines.append(f"  Types = Table.TransformColumnTypes(Selected, {{{type_specs}}})")
        elif declared_cols:
            # keep_all or hide_extras (MVP treats hide_extras as keep_all)
            type_specs = ", ".join(f'{{"{col[0]}", type {_map_datatype_to_m(col[1])}}}' for col in declared_cols)
            lines.append(f"  Types = Table.TransformColumnTypes(TBL, {{{type_specs}}})")
        else:
            lines.append("  Types = TBL")
        
        lines.append("in")
        lines.append("  Types")
        
    elif partition.nativeQuery:
        sql = partition.nativeQuery.strip()
        
        # Start with native query M code
        lines = [
            "let",
            f'  DB = Source.{source_key}(null),',
            f'  Result = Value.NativeQuery(DB, "{sql}", null, [EnableFolding = true]),'
        ]
        
        # Apply column policy
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(Result, {{{col_names}}}, MissingField.UseNull),")
            
            # Add type transformations
            type_specs = ", ".join(f'{{"{col[0]}", type {_map_datatype_to_m(col[1])}}}' for col in declared_cols)
            lines.append(f"  Types = Table.TransformColumnTypes(Selected, {{{type_specs}}})")
        elif declared_cols:
            # keep_all or hide_extras
            type_specs = ", ".join(f'{{"{col[0]}", type {_map_datatype_to_m(col[1])}}}' for col in declared_cols)
            lines.append(f"  Types = Table.TransformColumnTypes(Result, {{{type_specs}}})")
        else:
            lines.append("  Types = Result")
        
        lines.append("in")
        lines.append("  Types")
    else:
        raise ValueError(f"Partition {partition.name} has neither navigation nor nativeQuery")
    
    return "\n".join(lines)


def _map_datatype_to_m(datatype: str) -> str:
    """Map Pydantic DataType to M type.
    
    Args:
        datatype: DataType string from spec
        
    Returns:
        M type string
    """
    mapping = {
        "int64": "Int64.Type",
        "decimal": "Number.Type",
        "double": "Number.Type",
        "bool": "Logical.Type",
        "string": "Text.Type",
        "date": "Date.Type",
        "datetime": "DateTime.Type",
        "time": "Time.Type",
        "currency": "Currency.Type",
        "variant": "Any.Type"
    }
    return mapping.get(datatype, "Any.Type")


def emit_table_tmdl(tbl_dir: Path, table: Table, sources: SourcesSpec) -> None:
    """Render and write individual table TMDL with M code generation.
    
    Args:
        tbl_dir: Path to tables directory
        table: Table definition
        sources: SourcesSpec for partition M code generation
    """
    tbl_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("table.tmdl.j2")
    
    # Generate M code for each partition
    partition_mcodes = {}
    for partition in table.partitions:
        partition_mcodes[partition.name] = generate_partition_mcode(partition, table, sources)
    
    # Render table with first partition's M code (if any)
    partition_mcode = partition_mcodes.get(table.partitions[0].name, "") if table.partitions else ""
    
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
        "version": "1.0",
        "datasetReference": {
            "byPath": {
                "path": rel_model_path
            }
        }
    }
    
    (rpt_dir / "definition.pbir").write_text(json.dumps(pbir_content, indent=2))