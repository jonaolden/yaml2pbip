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
        # Build Snowflake.Databases call with the warehouse as the second positional
        # argument when provided. Only emit the options record (third argument)
        # when there are named options like Role or QueryTag.
        opts = []
        if src.role:
            opts.append(f'Role = "{src.role}"')
        if src.options and getattr(src.options, 'queryTag', None):
            opts.append(f'QueryTag = "{src.options.queryTag}"')

        # If warehouse present, use it as second positional argument
        if src.warehouse:
            if opts:
                inner = ", ".join(opts)
                return f'Snowflake.Databases("{src.server}", "{src.warehouse}", [{inner}])'
            else:
                return f'Snowflake.Databases("{src.server}", "{src.warehouse}")'
        else:
            # No warehouse; if we have opts, pass an options record as second arg
            if opts:
                inner = ", ".join(opts)
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

    def _extract_transform_body(transform_code: str, param_name: str) -> tuple[list[str], str]:
        """Extract variable definitions and final variable from transform's let...in block.
        
        Parses transform like:
            (Sheet as table) as table =>
            let
                PromotedHeaders = Table.PromoteHeaders(Sheet, ...),
                CleanedColumns = Table.TransformColumnNames(PromotedHeaders, ...)
            in
                CleanedColumns
        
        Returns:
            (variable_definitions, final_variable) where variable_definitions is a list of 
            M code lines like "PromotedHeaders = Table.PromoteHeaders(Sheet, ...)" and 
            final_variable is the name returned (e.g., "CleanedColumns")
        """
        import re
        
        # Find the body after the parameter declaration
        pattern = rf'\(\s*{param_name}\s+as\s+[^)]+\)\s+as\s+\w+\s*(?:=>)?\s*(.*)'
        match = re.search(pattern, transform_code, re.DOTALL)
        if not match:
            # Fallback - return empty list and the whole code
            return ([], transform_code)
        
        body = match.group(1).strip()
        
        # Now parse the let...in structure more carefully
        # We need to find 'let' and 'in' keywords, but only at the right level
        # Strategy: find the outermost 'let' and its matching 'in'
        
        # Find 'let' keyword (case insensitive, whole word)
        let_match = re.search(r'\blet\b', body, re.IGNORECASE)
        if not let_match:
            # Not a let...in structure, return as-is
            return ([], body)
        
        # Now find the matching 'in' keyword
        # We need to be careful because 'in' can appear inside strings, comments, and expressions
        # The safest approach is to find the last 'in' before the end of the body
        # that appears at the start of a line or after whitespace
        in_matches = list(re.finditer(r'\n\s*\bin\b', body, re.IGNORECASE))
        if not in_matches:
            # Try matching 'in' at any position as fallback
            in_matches = list(re.finditer(r'\bin\b', body, re.IGNORECASE))
        
        if not in_matches:
            # No 'in' found, malformed structure
            return ([], body)
        
        # Use the last 'in' match (most likely to be the closing one)
        in_match = in_matches[-1]
        
        # Extract the variable definitions between 'let' and 'in'
        defs_section = body[let_match.end():in_match.start()].strip()
        
        # Extract the final variable after 'in'
        final_section = body[in_match.end():].strip()
        
        # Parse variable definitions tracking brace/paren nesting
        # Definitions are separated by commas, but only at nesting level 0
        lines = defs_section.split('\n')
        
        variable_defs = []
        current_def = []
        in_definition = False
        nesting_level = 0  # Track {} () [] nesting
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines entirely
            if not stripped:
                continue
            
            # Comments are part of the current definition if we're in one
            if stripped.startswith('//'):
                if in_definition:
                    current_def.append(line)
                continue
            
            # Check if this line starts a new definition: has '=' before any comma
            # and we're not currently in a definition
            if '=' in stripped and not in_definition:
                # This starts a new definition
                in_definition = True
                current_def.append(line)
                # Count braces/parens/brackets in this line
                nesting_level += stripped.count('(') + stripped.count('{') + stripped.count('[')
                nesting_level -= stripped.count(')') + stripped.count('}') + stripped.count(']')
            elif in_definition:
                # Continuation of current definition
                current_def.append(line)
                # Update nesting level
                nesting_level += stripped.count('(') + stripped.count('{') + stripped.count('[')
                nesting_level -= stripped.count(')') + stripped.count('}') + stripped.count(']')
            
            # Check if this line ends the current definition
            # Only ends if we have a comma at nesting level 0
            if in_definition and nesting_level == 0 and stripped.endswith(','):
                # Definition complete
                variable_defs.append('\n'.join(current_def))
                current_def = []
                in_definition = False
        
        # Add any remaining definition (last one typically won't have comma)
        if current_def:
            variable_defs.append('\n'.join(current_def))
        
        return (variable_defs, final_section)
    
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

        Instead of referencing shared expressions, this always generates inline Snowflake.Databases calls
        to avoid composite model errors. Raises ValueError when neither source nor nav provide a database.
        """
        db_lines: list[str] = []
        if nav and getattr(nav, "database", None):
            # Always generate inline Snowflake.Databases call
            sf_call = _build_snowflake_call(source)
            db_lines.append(f'  SourceColl = {sf_call},')
            db_lines.append(f'  DB = SourceColl{{[Name = "{nav.database}", Kind = "Database"]}}[Data],')
        else:
            if source.database:
                # Generate inline Snowflake.Databases call instead of referencing source_key
                sf_call = _build_snowflake_call(source)
                db_lines.append(f'  SourceColl = {sf_call},')
                db_lines.append(f'  DB = SourceColl{{[Name = "{source.database}", Kind = "Database"]}}[Data],')
            elif require_nav_db:
                raise ValueError(
                    f"Source '{source_key}' does not define a database; partition '{partition.name}' must specify navigation.database"
                )
        return db_lines

    def _emit_sequential_steps(seed_var: str) -> str:
        """Emit sequential transform bindings with flattened variable definitions.
        
        Transform bodies are extracted from lambda functions like "(t as table) as table => body"
        The let...in structure is flattened, extracting internal variable definitions and
        inlining them at the same level as other partition variables.
        
        The last variable should NOT have a trailing comma since it's the
        final step before the 'in' clause.
        
        Args:
            seed_var: The base variable to apply first transform to (e.g., "Typed", "dim")
            
        Returns:
            Name of the final variable after all transforms are applied
        """
        if not partition.custom_steps:
            return seed_var
        
        import re
        import textwrap
        
        curr_var = seed_var
        for idx, step_name in enumerate(partition.custom_steps, start=1):
            # Get the transform body from transforms_dict
            if step_name not in transforms_dict:
                raise ValueError(f"Transform '{step_name}' not found in transforms")
            
            transform_code = transforms_dict[step_name].strip()
            
            # Extract parameter name from lambda function
            param_name = _extract_param_name(transform_code)
            
            # Extract variable definitions and final variable from the let...in block
            var_defs, final_var = _extract_transform_body(transform_code, param_name)
            
            # Ensure previous line ends with comma
            if not lines[-1].strip().endswith(','):
                lines[-1] = lines[-1] + ','
            
            # If no variable definitions found (inline expression), create a single variable
            if not var_defs:
                # Create a variable name from the step name
                var_name = f"__{step_name}_{idx}"
                # Replace parameter with current variable in the final expression
                expression = _replace_param_in_body(final_var, param_name, curr_var)
                is_last = (idx == len(partition.custom_steps))
                if is_last:
                    lines.append(f'  {var_name} = {expression}')
                else:
                    lines.append(f'  {var_name} = {expression},')
                curr_var = var_name
                continue
            
            # Inject each variable definition, replacing parameter name with current variable
            for def_idx, var_def in enumerate(var_defs):
                # Replace parameter name with current variable name using word boundaries
                injected_def = _replace_param_in_body(var_def, param_name, curr_var)
                
                # Dedent to remove original indentation, then re-indent consistently
                dedented = textwrap.dedent(injected_def)
                # Split into lines and re-indent each line
                def_lines = dedented.split('\n')
                reindented_lines = []
                for i, line in enumerate(def_lines):
                    if i == 0:
                        # First line gets 2-space indent
                        reindented_lines.append(f'  {line}')
                    else:
                        # Continuation lines get 4-space indent
                        reindented_lines.append(f'    {line}')
                injected_def = '\n'.join(reindented_lines)
                
                # Remove trailing comma if present (we'll add it back consistently)
                injected_def = injected_def.rstrip().rstrip(',')
                
                # Check if this is the last definition in the last transform
                is_last_def = (def_idx == len(var_defs) - 1)
                is_last_transform = (idx == len(partition.custom_steps))
                
                if is_last_def and is_last_transform:
                    # Last definition of last transform - no comma
                    lines.append(injected_def)
                else:
                    # Add comma
                    lines.append(f'{injected_def},')
                
                # Update curr_var if this is the last definition
                if is_last_def:
                    # Extract variable name from this definition
                    # Pattern: VarName = ...
                    var_match = re.match(r'\s*(\w+)\s*=', injected_def)
                    if var_match:
                        curr_var = var_match.group(1)
        
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
        # Simple source reference (e.g., Excel, flat files)
        # Inline the actual M code to avoid composite model errors
        source_mcode = generate_source_mcode(source, s_key)
        
        # Parse the source M code to extract variable definitions and final variable
        # The template generates: let\n  Source = ...,\n  Sheet = ...\nin\n  Sheet
        # We need to extract the variable definitions and integrate them
        source_lines = source_mcode.strip().split('\n')
        
        # Find lines between 'let' and 'in' - these are the variable definitions
        in_definitions = False
        source_final_var = None
        
        for line in source_lines:
            stripped = line.strip()
            if stripped == 'let':
                in_definitions = True
                continue
            elif stripped.startswith('in'):
                in_definitions = False
                # Next line should contain the final variable name
                continue
            elif not in_definitions and source_final_var is None and stripped:
                # This is the final variable returned by the source
                source_final_var = stripped
            elif in_definitions and stripped:
                # Add the variable definition with proper comma handling and normalized indentation
                # Replace tabs with spaces and normalize to 2-space indent
                normalized_line = line.replace('\t', '  ').strip()
                if not normalized_line.endswith(','):
                    lines.append(f'  {normalized_line},')
                else:
                    lines.append(f'  {normalized_line}')
        
        # Use the source's final variable as the seed for subsequent transformations
        seed_var = source_final_var if source_final_var else "Sheet"

        # Apply column selection if needed
        if table.column_policy == "select_only" and declared_cols:
            col_names = ", ".join(f'"{col[0]}"' for col in declared_cols)
            lines.append(f"  Selected = Table.SelectColumns({seed_var}, {{{col_names}}}, MissingField.UseNull),")
            seed_var = "Selected"

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
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {
            "byPath": {
                "path": rel_model_path
            }
        }
    }
    
    (rpt_dir / "definition.pbir").write_text(json.dumps(pbir_content, indent=2))
