"""TMDL emission functions for yaml2pbip."""
from pathlib import Path
from typing import Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json
import uuid

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

    This function robustly handles the four permutations of where the database
    comes from:
      - source.database present, partition.navigation.database present (same)
      - source.database present, partition.navigation.database present (different)
      - source.database present, partition.navigation.database absent
      - source.database absent, partition.navigation.database present

    If the source defines a `database` but the partition requests a different
    database, the function will inline a `Snowflake.Databases(...)` call so we
    can navigate to the requested database. If the source has no database and
    the partition does not specify one, we raise an error because the target
    database would be ambiguous.
    """
    source_key = partition.use or (table.source and table.source.get("use"))
    if not source_key:
        raise ValueError(f"Partition {partition.name} in table {table.name} has no source specified")

    source = sources.sources.get(source_key)
    if not source:
        raise ValueError(f"Source {source_key} not found in sources")

    declared_cols = [(col.name, col.dataType) for col in table.columns]

    def _build_snowflake_call(src: Source) -> str:
        """Build an inline Snowflake.Databases(...) M expression for a Source."""
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

    # Helper to append selection logic given a source table variable name
    def _append_type_steps(source_table_var: str):
        # For now, do not emit type transformation steps. If column_policy is
        # select_only we still select the declared columns, otherwise return the
        # original table/result as-is.
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns({source_table_var}, {{{col_names}}}, MissingField.UseNull),")
            lines.append(f"  Final = Selected()")
        else:
            lines.append(f"  Final = {source_table_var}")

    # Generate for navigation-based partitions
    if partition.navigation:
        nav = partition.navigation

        # If source has no database and partition also does not specify a database,
        # we cannot resolve which database to navigate to.
        if not source.database and not (nav and nav.database):
            raise ValueError(
                f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
            )

        # Case: partition requests a specific database
        if nav and nav.database:
            # If source.database is present and matches requested database, reuse expression
            if source.database and nav.database == source.database:
                lines.append(f'  DB = {source_key},')
            else:
                # Either source.database is None (expression returns Source collection),
                # or source.database is present but different. In both cases inline the
                # Snowflake.Databases call so we can index into the collection.
                sf_call = _build_snowflake_call(source)
                lines.append(f'  SourceColl = {sf_call},')
                lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')

        else:
            # No partition-level database requested. Use the source expression only
            # if it already returns a Database (i.e., source.database is present).
            if source.database:
                lines.append(f'  DB = {source_key},')
            else:
                raise ValueError(
                    f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
                )

        # Navigate to schema and table
        lines.append(f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],')
        lines.append(f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],')

        # Append column policy/type steps operating on TBL
        _append_type_steps("TBL")

        lines.append("in")
        lines.append("  Final")

    elif partition.nativeQuery:
        sql = partition.nativeQuery.strip().replace('"', '\\"')

        # Determine DB target for Value.NativeQuery
        # If partition.navigation with database provided, prefer that
        nav = partition.navigation
        if nav and nav.database:
            # If source.database matches, we can reuse expression
            if source.database and nav.database == source.database:
                lines.append(f'  DB = {source_key},')
                db_var = "DB"
            else:
                # Inline Snowflake.Databases -> pick the requested DB
                sf_call = _build_snowflake_call(source)
                lines.append(f'  SourceColl = {sf_call},')
                lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')
                db_var = "DB"
        else:
            # No partition.navigation.database provided: use the source expression if it returns a Database
            if source.database:
                lines.append(f'  DB = {source_key},')
                db_var = "DB"
            else:
                raise ValueError(
                    f"Cannot run nativeQuery for partition '{partition.name}': source '{source_key}' has no database and partition has no navigation.database"
                )

        # Call native query against resolved DB
        lines.append(f'  Result = Value.NativeQuery(DB, "{sql}", null, [EnableFolding = true]),')

        _append_type_steps("Result")

        lines.append("in")
        lines.append("  Types")

    else:
        raise ValueError(f"Partition {partition.name} has neither navigation nor nativeQuery")

    return "\n".join(lines)


def _generate_lineage_tag() -> str:
    """Generate a UUID for Power BI lineage tracking.
    
    Returns:
        UUID string in format like '6bfd7976-09ca-7046-4a83-0c3085609e3c'
    """
    return str(uuid.uuid4())


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
    
    # Generate M code only for M partitions (not entity partitions)
    partition_mcode = ""
    if table.partitions:
        first_partition = table.partitions[0]
        if first_partition.mode != "directLake":
            partition_mcode = generate_partition_mcode(first_partition, table, sources)
    
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