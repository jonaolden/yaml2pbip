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
    
    Args:
        source: Source specification
        source_key: Key name for the source
        
    Returns:
        M code string for the source
    """
    env = _get_jinja_env()
    template_name = f"sources/{source.kind}.j2"
    template = env.get_template(template_name)
    return template.render(src=source)


def generate_partition_mcode(partition: Partition, table: Table, sources: SourcesSpec, transforms: dict | None = None) -> str:
    """Generate Power Query M code for a partition with column policy logic.

    Transform bodies are inlined directly into the partition M code as:
    __t1 = (transform_body)(seed), __t2 = (transform_body)(__t1), etc.
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
    transforms_dict: dict = transforms or {}
    assert isinstance(transforms_dict, dict)

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

    def _extract_param_name(transform_code: str) -> str:
        """Extract parameter name from lambda function like '(t as table) as table => ...'"""
        import re
        # Match pattern: (param_name as type) as type
        match = re.match(r'\s*\(\s*(\w+)\s+as\s+', transform_code)
        if match:
            return match.group(1)
        return 't'  # Default fallback

    def _extract_transform_body(transform_code: str, param_name: str) -> str:
        """Extract body from lambda function, removing the parameter declaration."""
        import re
        # Pattern: (param as type) as type => body OR (param as type) as type \n body
        # Find the body after the parameter declaration
        pattern = rf'\(\s*{param_name}\s+as\s+[^)]+\)\s+as\s+\w+\s*(?:=>)?\s*(.*)'
        match = re.search(pattern, transform_code, re.DOTALL)
        if match:
            body = match.group(1).strip()
            return body
        # If no match, return the whole code as fallback
        return transform_code
    
    def _replace_param_in_body(body: str, param_name: str, replacement: str) -> str:
        """Replace parameter name with actual variable, using word boundaries."""
        import re
        # Use word boundaries to avoid replacing partial matches
        # Match param_name as a whole word (not part of another identifier)
        pattern = rf'\b{re.escape(param_name)}\b'
        return re.sub(pattern, replacement, body)

    lines = ["let"]

    # Validate custom transforms referenced by partition
    if partition.custom_steps:
        missing = [name for name in partition.custom_steps if name not in transforms_dict]
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

    def _emit_sequential_steps(seed_var: str) -> str:
        """Emit sequential transform bindings with injected transform bodies.
        
        Transform bodies are extracted from lambda functions like "(t as table) as table => body"
        and the parameter name is replaced with the actual input variable.
        
        The last transform step should NOT have a trailing comma since it's the
        final step before the 'in' clause.
        
        Args:
            seed_var: The base variable to apply first transform to (e.g., "Typed", "dim")
            
        Returns:
            Name of the final variable after all transforms are applied
        """
        if not partition.custom_steps:
            return seed_var
        
        curr_var = seed_var
        for idx, step_name in enumerate(partition.custom_steps, start=1):
            # Get the transform body from transforms_dict
            if step_name not in transforms_dict:
                raise ValueError(f"Transform '{step_name}' not found in transforms")
            
            transform_code = transforms_dict[step_name].strip()
            
            # Extract parameter name and body from lambda function
            # Pattern: (param as type) as type => body OR (param as type) as type \n body
            # We need to extract the parameter name (e.g., "t") and the body
            param_name = _extract_param_name(transform_code)
            transform_body = _extract_transform_body(transform_code, param_name)
            
            # Replace parameter name with current variable name using word boundaries
            injected_body = _replace_param_in_body(transform_body, param_name, curr_var)
            
            # Ensure previous line ends with comma
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            
            # Last transform step should NOT have trailing comma
            is_last = (idx == len(partition.custom_steps))
            
            # Generate step variable name
            step_var = f'__{step_name}_{idx}' if step_name else f'__t{idx}'
            
            # Inject the transform body directly
            if is_last:
                lines.append(f'  {step_var} = {injected_body}')
            else:
                lines.append(f'  {step_var} = {injected_body},')
            
            curr_var = step_var
        
        return curr_var

    # Generate for navigation-based partitions
    if partition.navigation:
        nav = partition.navigation

        # Use helper to resolve DB lines (will raise if impossible)
        lines.extend(_resolve_db(source, source_key, nav, require_nav_db=True))

        lines.append(f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],')
        lines.append(f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],')

        # Apply column selection if needed
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(TBL, {{{col_names}}}, MissingField.UseNull),")
            seed_var = "Selected"
        else:
            seed_var = "TBL"

        # Apply declared column types as a literal list to avoid runtime warnings
        if declared_cols:
            types_list = ", ".join(f'{{"{n}", {_map_datatype_to_m(t)}}}' for n, t in declared_cols)
            # Ensure previous line ends with a comma
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            lines.append(f'  Typed = Table.TransformColumnTypes({seed_var}, {{{types_list}}}),')
            seed_var = "Typed"

        # Apply custom transform steps sequentially
        final_var = _emit_sequential_steps(seed_var)

        # If there are no transforms, ensure the last line doesn't have a trailing comma
        if not partition.custom_steps and lines[-1].strip().endswith(','):
            lines[-1] = lines[-1].rstrip(',')

        lines.append("in")
        lines.append(f"  {final_var}")

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

        # Apply column selection if needed
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns(Result, {{{col_names}}}, MissingField.UseNull),")
            seed_var = "Selected"
        else:
            seed_var = "Result"

        # Apply declared column types
        if declared_cols:
            types_list = ", ".join(f'{{"{n}", {_map_datatype_to_m(t)}}}' for n, t in declared_cols)
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            lines.append(f'  Typed = Table.TransformColumnTypes({seed_var}, {{{types_list}}}),')
            seed_var = "Typed"

        # Apply custom transform steps sequentially
        final_var = _emit_sequential_steps(seed_var)

        # If there are no transforms, ensure the last line doesn't have a trailing comma
        if not partition.custom_steps and lines[-1].strip().endswith(','):
            lines[-1] = lines[-1].rstrip(',')

        lines.append("in")
        lines.append(f"  {final_var}")

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
