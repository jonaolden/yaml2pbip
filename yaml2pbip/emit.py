"""TMDL emission functions for yaml2pbip."""
from pathlib import Path
from typing import Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json
import uuid
import logging

from .spec import ModelBody, Table, Partition, SourcesSpec, Source

logger = logging.getLogger(__name__)


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
    # Add custom function for generating lineage tags
    env.globals['generate_lineage_tag'] = _generate_lineage_tag
    return env


def _generate_lineage_tag() -> str:
    """Generate a UUID for Power BI lineage tracking.
    
    Returns:
        UUID string in format like '6bfd7976-09ca-7046-4a83-0c3085609e3c'
    """
    return str(uuid.uuid4())



def emit_pbism(sm_dir: Path) -> None:
    """Create definition.pbism to mark directory as TMDL project.
    
    Args:
        sm_dir: Path to SemanticModel directory
    """
    sm_dir.mkdir(parents=True, exist_ok=True)
    pbism_content = {
        "version": "1.0"
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


def emit_expressions_tmdl(def_dir: Path, sources: SourcesSpec, transforms: dict | None = None) -> None:
    """Render and write expressions.tmdl with M source functions only.

    Transforms are intentionally NOT emitted as named expressions anymore —
    transforms are inlined directly into partition M code so they do not
    appear as separate expression definitions.
    """
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("expressions.tmdl.j2")
    # Do not render transforms as separate expressions; pass empty transforms
    content = template.render(sources=sources.sources, transforms={})
    (def_dir / "expressions.tmdl").write_text(content)


def generate_partition_mcode(partition: Partition, table: Table, sources: SourcesSpec, transforms: dict | None = None) -> str:
    """Generate Power Query M code for a partition with column policy logic.

    This version inlines transform function bodies directly into the partition
    M code instead of emitting them as separate expressions.
    """
    source_key = partition.use or (table.source and table.source.get("use"))
    if not source_key:
        raise ValueError(f"Partition {partition.name} in table {table.name} has no source specified")

    source = sources.sources.get(source_key)
    if not source:
        raise ValueError(f"Source {source_key} not found in sources")

    declared_cols = [(col.name, col.dataType) for col in table.columns]

    def _build_snowflake_call(src: Source) -> str:
        parts = []
        if src.warehouse:
            parts.append(f'Warehouse = "{src.warehouse}"')
        if src.role:
            parts.append(f'Role = "{src.role}"')
        if src.options and src.options.queryTag:
            parts.append(f'QueryTag = "{src.options.queryTag}"')
        if parts:
            inner = ", ".join(parts)
            return f'Snowflake.Databases("{src.server}", [{inner}])'
        else:
            return f'Snowflake.Databases("{src.server}")'

    lines = ["let"]

    def _append_type_steps(source_table_var: str):
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns({source_table_var}, {{{col_names}}}, MissingField.UseNull),")
            lines.append(f"  Final = Selected()")
        else:
            lines.append(f"  Final = {source_table_var}")

    def _extract_func_body(func_text: str) -> str:
        # crude extraction: take everything after the first '=>'
        idx = func_text.find('=>')
        if idx == -1:
            raise ValueError("Transform function missing '=>' token")
        return func_text[idx + 2 :].strip()

    def _inline_transforms(prev_var: str) -> str:
        # Inline each transform sequentially, returning the final variable name
        prev = prev_var
        for i, name in enumerate(partition.custom_steps):
            body = transforms[name]
            func_body = _extract_func_body(body)
            cur = f"__t_{i}"
            # ensure previous line ends with a comma so we can append assignments
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            # emit the inline anonymous function application
            lines.append(f"  {cur} = ((t) =>")
            for ln in func_body.splitlines():
                lines.append("    " + ln)
            # close the lambda and call it with the previous var
            # add trailing comma except for the last transform; final returned var will be used
            comma = ',' if i < len(partition.custom_steps) - 1 else ''
            lines.append(f"  )({prev}){comma}")
            prev = cur
        return prev

    # Validate custom transforms referenced by partition
    if partition.custom_steps:
        missing = [name for name in partition.custom_steps if name not in (transforms or {})]
        if missing:
            raise ValueError(
                f"Partition '{partition.name}' in table '{table.name}' references unknown transforms: {missing}"
            )
        if partition.mode == "directquery":
            logger.warning(
                "Partition '%s' in table '%s' is DirectQuery and references transforms which may not fold: %s",
                partition.name, table.name, partition.custom_steps
            )

    # Generate for navigation-based partitions
    if partition.navigation:
        nav = partition.navigation

        if not source.database and not (nav and nav.database):
            raise ValueError(
                f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
            )

        if nav and nav.database:
            if source.database and nav.database == source.database:
                lines.append(f'  DB = {source_key},')
            else:
                sf_call = _build_snowflake_call(source)
                lines.append(f'  SourceColl = {sf_call},')
                lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')
        else:
            if source.database:
                lines.append(f'  DB = {source_key},')
            else:
                raise ValueError(
                    f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
                )

        lines.append(f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],')
        lines.append(f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],')

        _append_type_steps("TBL")

        final_return = "Final"
        if partition.custom_steps:
            final_return = _inline_transforms("Final")

        lines.append("in")
        lines.append(f"  {final_return}")

    elif partition.nativeQuery:
        sql = partition.nativeQuery.strip().replace('"', '\\"')

        nav = partition.navigation
        if nav and nav.database:
            if source.database and nav.database == source.database:
                lines.append(f'  DB = {source_key},')
                db_var = "DB"
            else:
                sf_call = _build_snowflake_call(source)
                lines.append(f'  SourceColl = {sf_call},')
                lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')
                db_var = "DB"
        else:
            if source.database:
                lines.append(f'  DB = {source_key},')
                db_var = "DB"
            else:
                raise ValueError(
                    f"Cannot run nativeQuery for partition '{partition.name}': source '{source_key}' has no database and partition has no navigation.database"
                )

        lines.append(f'  Result = Value.NativeQuery(DB, "{sql}", null, [EnableFolding = true]),')

        _append_type_steps("Result")

        final_return = "Final"
        if partition.custom_steps:
            final_return = _inline_transforms("Final")

        lines.append("in")
        lines.append(f"  {final_return}")

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
        "boolean": "Logical.Type",
        "string": "Text.Type",
        "date": "Date.Type",
        "dateTime": "DateTime.Type",
        "time": "Time.Type",
        "currency": "Currency.Type",
        "variant": "Any.Type"
    }
    return mapping.get(datatype, "Any.Type")


def emit_table_tmdl(tbl_dir: Path, table: Table, sources: SourcesSpec, transforms: dict | None = None) -> None:
    """Render and write individual table TMDL with M code generation.
    
    Args:
        tbl_dir: Path to tables directory
        table: Table definition
        sources: SourcesSpec for partition M code generation
        transforms: optional dict of named transforms to validate and pass through
    """
    tbl_dir.mkdir(parents=True, exist_ok=True)
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
        "version": "1.0",
        "datasetReference": {
            "byPath": {
                "path": rel_model_path
            }
        }
    }
    
    (rpt_dir / "definition.pbir").write_text(json.dumps(pbir_content, indent=2))
