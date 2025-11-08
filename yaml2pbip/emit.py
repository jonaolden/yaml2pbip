"""TMDL emission functions for yaml2pbip."""
from pathlib import Path
from typing import Dict, List
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json
import uuid
import logging

from .spec import ModelBody, Table, Partition, SourcesSpec, Source, Navigation

logger = logging.getLogger(__name__)


def _generate_lineage_tag() -> str:
    """Generate a UUID for Power BI lineage tracking.
    
    Returns:
        UUID string in format like '6bfd7976-09ca-7046-4a83-0c3085609e3c'
    """
    return str(uuid.uuid4())


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
    # Determine source key explicitly from partition.use or table.source.use
    source_key = partition.use
    if not source_key and table.source and isinstance(table.source, dict):
        source_key = table.source.get("use")

    if not isinstance(source_key, str) or not source_key:
        raise ValueError(f"Partition {partition.name} in table {table.name} has no source specified")

    # Localize source_key as string for static checkers
    s_key: str = source_key

    source = sources.sources.get(s_key)
    if not source:
        raise ValueError(f"Source {s_key} not found in sources")

    declared_cols = [(col.name, col.dataType) for col in table.columns]
    # Normalize transforms to an empty dict when None to satisfy static checkers
    transforms: dict = transforms or {}
    assert isinstance(transforms, dict)

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

    def _extract_func_body(func_text: str) -> str:
        # crude extraction: take everything after the first '=>'
        idx = func_text.find('=>')
        if idx == -1:
            raise ValueError("Transform function missing '=>' token")
        return func_text[idx + 2 :].strip()

    def _inline_transforms(prev_var: str) -> str:
        # Emit named transform functions and a steps list, then use List.Accumulate
        # to apply them sequentially. Returns the name of the final resulting variable.
        # prev_var is the base table variable (e.g., Final)
        for name in partition.custom_steps:
            body = transforms[name].strip()
            # Ensure previous line ends with a comma
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            lines.append(f'  {name} = {body},')
        # Emit __steps list
        steps_list = ", ".join(partition.custom_steps)
        lines.append(f'  __steps = {{{steps_list}}},')
        # Emit accumulated application, producing a new variable Final_transformed
        final_var = "Final_transformed"
        lines.append(f'  {final_var} = List.Accumulate(__steps, {prev_var}, (state, f) => f(state))')
        return final_var

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

    def _resolve_db(source: Source, source_key: str, nav: Navigation | None, require_nav_db: bool = False) -> list:
        """Return lines needed to ensure a DB variable exists for the partition.

        If nav is provided and specifies a database different from the source's declared database,
        this emits a Snowflake.Databases call and DB resolution; otherwise it binds DB to the
        source symbol. Raises ValueError when neither source nor nav provide a database.
        """
        db_lines: list[str] = []
        if nav and getattr(nav, "database", None):
            if source.database and nav.database == source.database:
                db_lines.append(f'  DB = {source_key},')
            else:
                sf_call = _build_snowflake_call(source)
                db_lines.append(f'  SourceColl = {sf_call},')
                db_lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')
        else:
            if source.database:
                db_lines.append(f'  DB = {source_key},')
            elif require_nav_db:
                raise ValueError(
                    f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
                )
        return db_lines

    # Generate for navigation-based partitions
    if partition.navigation:
        nav = partition.navigation

        # Use helper to resolve DB lines (will raise if impossible)
        lines.extend(_resolve_db(source, source_key, nav, require_nav_db=True))

        lines.append(f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],')
        lines.append(f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],')

        # Inline type-step logic here to reduce indirection
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(TBL, {{{col_names}}}, MissingField.UseNull),")
            lines.append(f"  Final = Selected")
        else:
            lines.append(f"  Final = TBL")

        final_return = "Final"
        if partition.custom_steps:
            final_return = _inline_transforms("Final")

        lines.append("in")
        lines.append(f"  {final_return}")

    elif partition.nativeQuery:
        sql = partition.nativeQuery.strip().replace('"', '\\"')

        nav = partition.navigation
        # Resolve DB for nativeQuery; if nav.database provided or source has database it will work
        lines.extend(_resolve_db(source, source_key, nav, require_nav_db=False))

        # If no DB lines resolved, then neither nav nor source provided database - error
        if not any(l.strip().startswith('DB =') for l in lines):
            raise ValueError(
                f"Cannot run nativeQuery for partition '{partition.name}': source '{source_key}' has no database and partition has no navigation.database"
            )

        lines.append(f'  Result = Value.NativeQuery(DB, "{sql}", null, [EnableFolding = true]),')

        # Inline type-step logic here as well
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(Result, {{{col_names}}}, MissingField.UseNull),")
            lines.append(f"  Final = Selected")
        else:
            lines.append(f"  Final = Result")

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
