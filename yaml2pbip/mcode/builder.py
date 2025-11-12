"""M code partition builder with modular construction using builder pattern."""
import re
import ast
import textwrap
import logging
from typing import List, Tuple, Dict, Any

from ..spec import Partition, Table, Source, SourcesSpec, Navigation
from ..transforms import render_transform_template
from .utils import format_column_list, format_types_list, ensure_trailing_comma, remove_trailing_comma
from .source_resolver import generate_inline_source_mcode, parse_source_mcode, resolve_database_navigation

logger = logging.getLogger(__name__)


class MCodePartitionBuilder:
    """Builder pattern for constructing partition M code.
    
    This builder provides a fluent API for constructing Power Query M code
    for partitions in a step-by-step manner, making the code more maintainable
    and testable than a monolithic function.
    
    Example usage:
        builder = MCodePartitionBuilder(partition, table, sources)
        mcode = (builder
                 .add_source_connection()
                 .add_navigation()
                 .add_column_selection()
                 .add_type_transformation()
                 .add_custom_transforms(transforms)
                 .build())
    """
    
    def __init__(self, partition: Partition, table: Table, sources: SourcesSpec):
        """Initialize the builder.
        
        Args:
            partition: Partition specification
            table: Table specification containing columns and policies
            sources: SourcesSpec containing available data sources
        """
        self.partition = partition
        self.table = table
        self.sources = sources
        self.lines: List[str] = ["let"]
        self.seed_var: str | None = None
        self.declared_cols: List[Tuple[str, str]] = [
            (col.name, col.dataType) for col in table.columns
        ]
        
        # Resolve source
        self.source_key = self._resolve_source_key()
        self.source = self._get_source()
    
    def _resolve_source_key(self) -> str:
        """Determine source key from partition.use or table.source.use.
        
        Returns:
            Source key string
            
        Raises:
            ValueError: If no source key can be resolved
        """
        source_key = self.partition.use
        if not source_key and self.table.source and isinstance(self.table.source, dict):
            source_key = self.table.source.get("use")
        
        if not isinstance(source_key, str) or not source_key:
            raise ValueError(
                f"Partition {self.partition.name} in table {self.table.name} has no source specified"
            )
        
        return source_key
    
    def _get_source(self) -> Source:
        """Get source specification from sources.
        
        Returns:
            Source specification
            
        Raises:
            ValueError: If source not found
        """
        source = self.sources.sources.get(self.source_key)
        if not source:
            raise ValueError(f"Source {self.source_key} not found in sources")
        return source
    
    def add_source_connection(self) -> 'MCodePartitionBuilder':
        """Add source connection variables based on partition type.
        
        For navigation or nativeQuery partitions, adds database navigation.
        For simple source references (e.g., Excel), embeds the full source M code.
        
        Returns:
            Self for method chaining
        """
        if self.partition.navigation or self.partition.nativeQuery:
            # Add database navigation for structured sources
            self._add_database_navigation()
        else:
            # Embed full source M code for simple sources
            self._embed_simple_source()
        
        return self
    
    def _add_database_navigation(self) -> None:
        """Add database navigation lines for structured data sources."""
        nav = self.partition.navigation
        database = None
        
        # Determine database from navigation or source
        if nav and getattr(nav, "database", None):
            database = nav.database
        elif self.source.database:
            database = self.source.database
        elif self.partition.nativeQuery:
            # nativeQuery requires a database
            raise ValueError(
                f"Cannot run nativeQuery for partition '{self.partition.name}': "
                f"source '{self.source_key}' has no database and partition has no navigation.database"
            )
        
        if database:
            db_lines = resolve_database_navigation(self.source, self.source_key, database)
            self.lines.extend(db_lines)
    
    def _embed_simple_source(self) -> None:
        """Embed full source M code for simple sources like Excel."""
        # Generate source M code using template
        source_mcode = generate_inline_source_mcode(self.source, self.source_key, inline=False)
        
        # Parse and extract variable definitions
        definitions, final_var = parse_source_mcode(source_mcode)
        
        # Add definitions with proper comma handling
        for defn in definitions:
            if not defn.endswith(','):
                defn = defn + ','
            self.lines.append(f'  {defn}')
        
        # Set seed variable to the final variable from source
        self.seed_var = final_var
    
    def add_navigation(self) -> 'MCodePartitionBuilder':
        """Add navigation to schema and table.
        
        Should be called after add_source_connection() for navigation partitions.
        
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If partition has no navigation specified
        """
        if not self.partition.navigation:
            return self
        
        nav = self.partition.navigation
        
        # Navigate to schema and table
        self.lines.append(f'  SCH = DB{{[Name = "{nav.schema_}", Kind = "Schema"]}}[Data],')
        self.lines.append(f'  TBL = SCH{{[Name = "{nav.table}", Kind = "Table"]}}[Data],')
        
        self.seed_var = "TBL"
        return self
    
    def add_native_query(self) -> 'MCodePartitionBuilder':
        """Add native query execution.
        
        Should be called after add_source_connection() for nativeQuery partitions.
        
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If partition has no nativeQuery specified
        """
        if not self.partition.nativeQuery:
            return self
        
        # Escape SQL for M code
        sql = self.partition.nativeQuery.strip().replace('"', '\\"')
        
        self.lines.append(f'  Result = Value.NativeQuery(DB, "{sql}", null, [EnableFolding = true]),')
        self.seed_var = "Result"
        
        return self
    
    def add_column_selection(self) -> 'MCodePartitionBuilder':
        """Add column selection based on table column policy.
        
        If column_policy is 'select_only' and columns are declared, selects only
        those columns from the source.
        
        Returns:
            Self for method chaining
        """
        if self.table.column_policy == "select_only" and self.declared_cols:
            col_names = format_column_list(self.declared_cols)
            
            # Ensure previous line has comma
            if self.lines and not self.lines[-1].strip().endswith(','):
                self.lines[-1] = ensure_trailing_comma(self.lines[-1])
            
            self.lines.append(
                f"  Selected = Table.SelectColumns({self.seed_var}, {{{col_names}}}, MissingField.UseNull),"
            )
            self.seed_var = "Selected"
        
        return self
    
    def add_type_transformation(self) -> 'MCodePartitionBuilder':
        """Add column type transformations.
        
        Applies declared column types using Table.TransformColumnTypes.
        
        Returns:
            Self for method chaining
        """
        if not self.declared_cols:
            return self
        
        types_list = format_types_list(self.declared_cols)
        
        # Ensure previous line has comma
        if self.lines and not self.lines[-1].strip().endswith(','):
            self.lines[-1] = ensure_trailing_comma(self.lines[-1])
        
        self.lines.append(f'  Typed = Table.TransformColumnTypes({self.seed_var}, {{{types_list}}}),')
        self.seed_var = "Typed"
        
        return self
    
    def add_custom_transforms(self, transforms: Dict[str, str] | None = None) -> 'MCodePartitionBuilder':
        """Add custom transform steps sequentially.
        
        Supports flexible custom_steps formats:
          - ["name1", "name2"]                     # simple names
          - [{"name":"n","params": {...}}, ...]    # explicit params dict
          - [["name", params], ...]                # tuple/list shorthand
          - [{"name": value}, ...]                 # single-key dict shorthand (value is params)
        
        Params are passed to the transform template as 'params' in the Jinja context.
        
        Args:
            transforms: Dictionary of transform name -> M code
            
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If referenced transform not found or custom_steps malformed
        """
        if not self.partition.custom_steps:
            return self
        
        transforms_dict = transforms or {}
        
        # Normalize steps into list of {"name": str, "params": any}
        normalized_steps = []
        for step in self.partition.custom_steps:
            # Support string shorthand:
            # - "name"
            # - "name(123)"
            # - "name('a','b')"
            # - "name(a,b)" -> params becomes list
            if isinstance(step, str):
                # Support forms like:
                #  - name
                #  - name(123)
                #  - name('a','b')
                #  - name([1,2])   -> parse as actual list
                #  - name({"a":1}) -> parse as mapping
                m = re.match(r'^([A-Za-z0-9_]+)\s*\((.*)\)\s*$', step)
                if m:
                    name = m.group(1)
                    raw = m.group(2).strip()
                    if raw == "":
                        params = None
                    else:
                        # If the raw looks like a Python/JSON literal (list/dict/number/string),
                        # try to parse it safely with ast.literal_eval so arrays/maps are accepted.
                        parsed_literal = None
                        if (raw.startswith('[') and raw.endswith(']')) or (raw.startswith('{') and raw.endswith('}')) or \
                           (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')) or \
                           re.match(r'^\d+$', raw):
                            try:
                                parsed_literal = ast.literal_eval(raw)
                            except Exception:
                                parsed_literal = None
                        if parsed_literal is not None:
                            params = parsed_literal
                        else:
                            # Fallback: split on commas and parse simple scalars (ints or quoted strings)
                            parts = [p.strip() for p in re.split(r'\s*,\s*', raw)]
                            def _parse_part(p: str):
                                if re.match(r'^\d+$', p):
                                    return int(p)
                                if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                                    return p[1:-1]
                                return p
                            parsed = [_parse_part(p) for p in parts]
                            params = parsed[0] if len(parsed) == 1 else parsed
                    normalized_steps.append({"name": name, "params": params})
                else:
                    normalized_steps.append({"name": step, "params": None})
                continue

            # List/tuple shorthand: [name, params]
            if isinstance(step, (list, tuple)):
                if len(step) == 0:
                    raise ValueError(f"Empty custom_step entry in partition '{self.partition.name}'")
                name = step[0]
                params = step[1] if len(step) > 1 else None
                normalized_steps.append({"name": name, "params": params})
                continue

            # Dict formats:
            if isinstance(step, dict):
                # Explicit form: {"name": "...", "params": ...}
                if "name" in step:
                    normalized_steps.append({"name": step["name"], "params": step.get("params")})
                    continue
                # Shorthand single-key: {"limit_rows_in_desktop": 500}
                if len(step) == 1:
                    k = next(iter(step.keys()))
                    normalized_steps.append({"name": k, "params": step[k]})
                    continue
                raise ValueError(f"Invalid custom_step dict in partition '{self.partition.name}': {step}")

            raise ValueError(f"Unsupported custom_step type {type(step)} in partition '{self.partition.name}'")
        
        # Validate transforms exist
        missing = [s["name"] for s in normalized_steps if s["name"] not in transforms_dict]
        if missing:
            raise ValueError(
                f"Partition '{self.partition.name}' in table '{self.table.name}' "
                f"references unknown transforms: {missing}"
            )
        
        # Warn for DirectQuery partitions with transforms
        if self.partition.mode == "directquery":
            logger.warning(
                "Partition '%s' in table '%s' is DirectQuery and references transforms "
                "which may not fold: %s",
                self.partition.name,
                self.table.name,
                [s["name"] for s in normalized_steps]
            )
        
        # Apply transforms sequentially
        curr_var = self.seed_var
        for idx, step in enumerate(normalized_steps, start=1):
            step_name = step["name"]
            step_params = step.get("params")
            transform_code = transforms_dict[step_name].strip()
            
            # Render Jinja2 template with extended context (include params)
            context = {
                'input_var': curr_var,
                'table_name': self.table.name,
                'columns': self.declared_cols,
                'column_names': format_column_list(self.declared_cols),
                'params': step_params,
            }
            transform_code = render_transform_template(transform_code, context)
            
            # Extract body after lambda signature
            match = re.search(
                r'\(\s*\w+\s+as\s+table\s*\)\s+as\s+table\s*(?:=>)?\s*(.*)',
                transform_code,
                re.DOTALL
            )
            body = match.group(1).strip() if match else transform_code
            
            # Sanitize var name (replace non-ident chars with '_')
            safe_step = re.sub(r"[^A-Za-z0-9_]", "_", step_name)
            var_name = f"__{safe_step}_{idx}"
            is_last = (idx == len(normalized_steps))
            
            # Ensure previous line has comma
            if idx > 1 and not self.lines[-1].strip().endswith(','):
                self.lines[-1] = ensure_trailing_comma(self.lines[-1])
            
            # Re-indent body to 4-space indent relative to assignment
            dedented = textwrap.dedent(body)
            indented_lines = []
            for line in dedented.split('\n'):
                stripped = line.strip()
                if stripped:
                    indented_lines.append(f'    {stripped}')
                else:
                    indented_lines.append('')
            body_text = '\n'.join(indented_lines)
            
            # Emit transform (with comma if not last)
            if is_last:
                self.lines.append(f'  {var_name} =\n{body_text}')
            else:
                self.lines.append(f'  {var_name} =\n{body_text},')
            
            curr_var = var_name
        
        self.seed_var = curr_var
        return self
    
    def build(self) -> str:
        """Build and return the final M code string.
        
        Finalizes the M code by removing trailing comma from last line
        and adding the 'in' clause with final variable.
        
        Returns:
            Complete M code string
            
        Raises:
            ValueError: If no seed variable was set (no data source)
        """
        if not self.seed_var:
            raise ValueError(f"No data source configured for partition {self.partition.name}")
        
        # Remove trailing comma from last line
        if self.lines and self.lines[-1].strip().endswith(','):
            self.lines[-1] = remove_trailing_comma(self.lines[-1])
        
        # Add 'in' clause
        self.lines.append("in")
        self.lines.append(f"  {self.seed_var}")
        
        return "\n".join(self.lines)