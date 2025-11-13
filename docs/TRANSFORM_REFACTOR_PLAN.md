# Transform Refactor: Native M-code Expression Functions

## Overview

Replace Jinja2-templated inline transform code with native Power Query M expression functions, following the pattern shown in the reference `FxApplyDynamicTypes` implementation.

## Current Architecture (To Be Replaced)

### Current Flow
1. Transform files (`.m.j2`) contain M-code with Jinja2 templating:
   - Use `{% raw %}` blocks to protect M syntax from Jinja2
   - Use `{{ input_var }}` for dynamic variable substitution
2. Transforms loaded from filesystem into dict: `{name: m_code_string}`
3. During partition M-code generation (in [`builder.py`](../yaml2pbip/mcode/builder.py)):
   - Jinja2 renders template with context (`input_var`, `table_name`, `columns`, etc.)
   - Lambda signature extracted: `(t as table) as table =>`
   - Body extracted and re-indented
   - Inlined as let-variable: `__transform_name_1 = <body>`
   - Sequential chaining: output of step N → input of step N+1

### Current Example
```m
# Transform file: proper_casting.m.j2
(t as table) as table =>
{% raw %}
let
  renamer = (name as text) as text =>
    if Text.EndsWith(name, "_ID") then name
    else Text.Proper(Text.Replace(name, "_", " "))
in
  Table.TransformColumnNames(
{% endraw %}
{{ input_var }}
{% raw %}
, renamer)
{% endraw %}
```

**Generated in partition:**
```m
let
  Source = ...,
  TBL = ...,
  __proper_casting_1 =
    let
      renamer = (name as text) as text =>
        if Text.EndsWith(name, "_ID") then name
        else Text.Proper(Text.Replace(name, "_", " "))
    in
      Table.TransformColumnNames(TBL, renamer)
in
  __proper_casting_1
```

### Problems with Current Approach
1. **Jinja2 complexity**: Requires `{% raw %}` blocks, error-prone syntax mixing
2. **Not native M-code**: Uses templating instead of standard Power Query patterns
3. **Verbose**: Each transform inlined as multi-line let-block in partition
4. **Non-standard**: Power BI users expect reusable M functions, not inline code
5. **Hard to debug**: Generated M-code is harder to read/maintain

## New Architecture (Expression Functions)

### New Flow
1. Transform files (`.m`) contain **pure M-code functions** (no Jinja2):
   - Standard M function signature: `(t as table) as table =>`
   - No templating, no `{% raw %}` blocks
   - Self-contained, reusable function
2. Transforms loaded and emitted to [`expressions.tmdl`](../yaml2pbip/templates/expressions.tmdl.j2)
3. Partition M-code **calls** the function by name:
   - Simple function invocation: `Cast = FxProperCasting(TBL)`
   - Clean, readable, native M-code
   - Standard Power Query pattern

### New Example

**Transform file: `proper_casting.m`**
```m
(t as table) as table =>
let
  renamer = (name as text) as text =>
    if Text.EndsWith(name, "_ID") then name
    else Text.Proper(Text.Replace(name, "_", " "))
in
  Table.TransformColumnNames(t, renamer)
```

**Generated in expressions.tmdl:**
```
expression FxProperCasting = ```
	(t as table) as table =>
	let
	  renamer = (name as text) as text =>
	    if Text.EndsWith(name, "_ID") then name
	    else Text.Proper(Text.Replace(name, "_", " "))
	in
	  Table.TransformColumnNames(t, renamer)
	```
	lineageTag: <uuid>
	
	annotation PBI_ResultType = Function
```

**Generated in partition:**
```m
let
  Source = ...,
  TBL = ...,
  Cast = FxProperCasting(TBL)
in
  Cast
```

### Benefits
1. ✅ **Native M-code**: Standard Power Query patterns, no templating
2. ✅ **Simpler**: No Jinja2, no `{% raw %}` blocks, pure M-code
3. ✅ **Readable**: Clean function calls in partitions
4. ✅ **Reusable**: Functions in expressions.tmdl can be used across tables
5. ✅ **Debuggable**: Standard M-code, easier to understand and troubleshoot
6. ✅ **Maintainable**: Follows Power BI/Power Query best practices

## Implementation Plan

### Phase 1: Core Architecture Changes

#### 1. Update [`transforms.py`](../yaml2pbip/transforms.py)
- **Remove**: Jinja2 rendering logic (`render_transform_template()`)
- **Keep**: File loading, validation, canonical naming
- **Change**: Validate pure M-code (no Jinja2 syntax allowed)
- **Change**: Load from `.m` files (deprecate `.m.j2`)

**Key Changes:**
```python
# OLD: Support Jinja2 templating
def render_transform_template(transform_text: str, context: Dict = None) -> str:
    # Jinja2 rendering logic...

# NEW: No rendering needed - just validate pure M-code
def validate_transform_function(text: str, src: Path) -> None:
    """Validate that transform is pure M-code function."""
    # Check for Jinja2 syntax (should not exist)
    if '{{' in text or '{%' in text:
        raise ValueError(f"{src}: Transforms must be pure M-code (no Jinja2)")
    # Check function signature
    if not SIG.search(text):
        raise ValueError(f"{src}: Must start with '(t as table) as table =>'")
```

#### 2. Update [`emit.py`](../yaml2pbip/emit.py)
- **Change**: [`emit_expressions_tmdl()`](../yaml2pbip/emit.py:111) to emit transforms as expression functions
- **Keep**: Source emission logic unchanged

**Key Changes:**
```python
def emit_expressions_tmdl(def_dir: Path, sources: SourcesSpec, transforms: dict | None = None) -> None:
    """Render and write expressions.tmdl with M source functions AND transform functions."""
    def_dir.mkdir(parents=True, exist_ok=True)
    env = _get_jinja_env()
    template = env.get_template("expressions.tmdl.j2")
    
    # Generate function name mapping: transform_name -> FxTransformName
    transform_functions = {}
    if transforms:
        for name, body in transforms.items():
            # Convert "proper_casting" -> "FxProperCasting"
            func_name = "Fx" + "".join(word.capitalize() for word in name.split("_"))
            transform_functions[func_name] = body.strip()
    
    content = template.render(
        sources=sources.sources,
        transforms=transform_functions  # Now emitted as expression functions
    )
    (def_dir / "expressions.tmdl").write_text(content)
```

#### 3. Update [`builder.py`](../yaml2pbip/mcode/builder.py)
- **Remove**: Transform body extraction, re-indentation logic
- **Remove**: Jinja2 template rendering call
- **Change**: [`add_custom_transforms()`](../yaml2pbip/mcode/builder.py:235) to generate function calls

**Key Changes:**
```python
def add_custom_transforms(self, transforms: Dict[str, str] | None = None) -> 'MCodePartitionBuilder':
    """Add custom transform function calls.
    
    Generates simple function calls instead of inlining code:
      Cast = FxProperCasting(TBL)
    """
    if not self.partition.custom_steps:
        return self
    
    transforms_dict = transforms or {}
    
    # Normalize steps (keep existing param parsing logic)
    normalized_steps = [...]  # Same as current
    
    # Validate transforms exist
    missing = [s["name"] for s in normalized_steps if s["name"] not in transforms_dict]
    if missing:
        raise ValueError(f"Unknown transforms: {missing}")
    
    # Apply transforms as function calls
    curr_var = self.seed_var
    for idx, step in enumerate(normalized_steps, start=1):
        step_name = step["name"]
        step_params = step.get("params")
        
        # Convert transform name to function name
        func_name = "Fx" + "".join(word.capitalize() for word in step_name.split("_"))
        
        # Generate variable name
        safe_step = re.sub(r"[^A-Za-z0-9_]", "_", step_name)
        var_name = f"__{safe_step}_{idx}"
        is_last = (idx == len(normalized_steps))
        
        # Simple function call
        comma = "" if is_last else ","
        self.lines.append(f'  {var_name} = {func_name}({curr_var}){comma}')
        
        curr_var = var_name
    
    self.seed_var = curr_var
    return self
```

#### 4. Update [`expressions.tmdl.j2`](../yaml2pbip/templates/expressions.tmdl.j2)
- **Keep**: Source expression emission
- **Change**: Transform emission to use proper expression function format

**Key Changes:**
```jinja
{# Sources - unchanged #}
{% for key, src in sources.items() %}
expression {{ key }} = ```
{% if src.kind == 'snowflake' %}
{% include 'sources/snowflake.j2' %}
...
{% endif %}
			```
	lineageTag: {{ generate_lineage_tag() }}
	annotation PBI_IncludeFutureArtifacts = False
{% endfor %}

{# NEW: Transform functions as proper expressions #}
{% if transforms %}
{% for func_name, body in transforms.items() %}

expression {{ func_name }} = ```
	{{ body }}
	```
	lineageTag: {{ generate_lineage_tag() }}
	
	annotation PBI_ResultType = Function

{% endfor %}
{% endif %}
```

### Phase 2: Migration Support

#### 5. Update Transform Files
- **Rename**: `.m.j2` → `.m`
- **Remove**: All `{% raw %}` and `{% endraw %}` blocks
- **Remove**: All `{{ variable }}` substitutions
- **Change**: Use parameter name directly (e.g., `t` instead of `{{ input_var }}`)

**Migration Example:**

**Before (`proper_casting.m.j2`):**
```m
(t as table) as table =>
{% raw %}
let
  renamer = (name as text) as text =>
    if Text.EndsWith(name, "_ID") then name
    else Text.Proper(Text.Replace(name, "_", " "))
in
  Table.TransformColumnNames(
{% endraw %}
{{ input_var }}
{% raw %}
, renamer)
{% endraw %}
```

**After (`proper_casting.m`):**
```m
(t as table) as table =>
let
  renamer = (name as text) as text =>
    if Text.EndsWith(name, "_ID") then name
    else Text.Proper(Text.Replace(name, "_", " "))
in
  Table.TransformColumnNames(t, renamer)
```

#### 6. Handle Parameters
Current transforms support params via Jinja2 context. For parameterized transforms:

**Option A: Higher-order functions (recommended)**
```m
// Transform: limit_rows.m
(maxRows as number) as function =>
  (t as table) as table =>
    Table.FirstN(t, maxRows)
```

**YAML usage:**
```yaml
custom_steps:
  - name: limit_rows
    params: 1000
```

**Generated:**
```m
Limit = FxLimitRows(1000)(TBL)
```

**Option B: Record parameters**
```m
// Transform: select_columns.m
(config as record) as table =>
  let
    t = config[table],
    cols = config[columns]
  in
    Table.SelectColumns(t, cols)
```

### Phase 3: Testing & Validation

#### 7. Update Tests
- **Update**: [`test_emit.py`](../testing/test_emit.py) assertions
- **Change**: Expect function calls instead of inline code
- **Add**: Tests for expression function generation

**Test Changes:**
```python
# OLD assertions
assert "__proper_naming_1 =" in mcode
assert "Table.RenameColumns(t," in mcode

# NEW assertions
assert "__proper_naming_1 = FxProperNaming(TBL)" in mcode
assert "expression FxProperNaming" in expressions_content
```

#### 8. Update Examples
- **Migrate**: All example transform files from `.m.j2` to `.m`
- **Remove**: Jinja2 syntax from examples
- **Update**: Documentation and READMEs

### Phase 4: Cleanup & Documentation

#### 9. Remove Deprecated Code
- **Remove**: Jinja2 rendering from [`transforms.py`](../yaml2pbip/transforms.py)
- **Remove**: `.m.j2` file support completely (no backward compatibility)
- **Clean**: Unused imports, helper functions

#### 10. Update Documentation
- **Update**: [`ARCHITECTURE.md`](../docs/ARCHITECTURE.md) with new pattern
- **Create**: Migration guide for existing users
- **Update**: Transform documentation
- **Add**: Examples of parameterized transforms

## Function Naming Convention

Transform names are converted to PascalCase with "Fx" prefix:
- `proper_casting` → `FxProperCasting`
- `limit_rows_in_desktop` → `FxLimitRowsInDesktop`
- `clean_headers` → `FxCleanHeaders`

This follows Power Query conventions where:
- `Fx` prefix indicates a custom function
- PascalCase matches built-in M functions (e.g., `Table.SelectColumns`)

## Breaking Change - No Backward Compatibility

This refactor introduces a **breaking change** with no backward compatibility:
- `.m.j2` files are **no longer supported**
- All transforms must be migrated to pure `.m` files
- Jinja2 templating syntax will cause validation errors

### Migration Required

Users must convert existing `.m.j2` files to `.m` format:

**Conversion script:**
```python
def migrate_transform(old_file: Path) -> str:
    """Convert .m.j2 to pure .m by removing Jinja2 syntax."""
    content = old_file.read_text()
    
    # Remove {% raw %} and {% endraw %}
    content = re.sub(r'{%\s*raw\s*%}', '', content)
    content = re.sub(r'{%\s*endraw\s*%}', '', content)
    
    # Replace {{ input_var }} with 't' (parameter name)
    content = re.sub(r'{{\s*input_var\s*}}', 't', content)
    
    # Clean up extra whitespace
    content = textwrap.dedent(content).strip()
    
    return content
```

**Manual steps:**
1. Rename `.m.j2` → `.m`
2. Remove all `{% raw %}` and `{% endraw %}` blocks
3. Replace `{{ input_var }}` with parameter name `t`
4. Remove any other Jinja2 syntax (`{{ }}`, `{% %}`)
5. Validate that function signature is preserved: `(t as table) as table =>`

## Benefits Summary

### For Users
- ✅ Write **pure M-code** (no templating syntax to learn)
- ✅ **Reusable functions** across multiple tables
- ✅ **Standard patterns** familiar to Power Query developers
- ✅ **Better debugging** with native M-code

### For Developers
- ✅ **Simpler codebase** (remove Jinja2 complexity)
- ✅ **Easier testing** (pure functions, no template rendering)
- ✅ **Better maintainability** (standard M-code patterns)
- ✅ **Clearer separation** (data vs. logic)

### For Generated Code
- ✅ **More readable** partition M-code
- ✅ **Better performance** (Power Query can optimize function calls)
- ✅ **Standard TMDL** (matches Power BI Desktop output)
- ✅ **Smaller files** (function call vs. inline code)

## Risk Mitigation

### Potential Issues
1. **Breaking change**: Existing `.m.j2` files won't work
   - **Mitigation**: Clear migration guide, conversion script provided
   
2. **Parameter passing**: Current Jinja2 params won't work
   - **Mitigation**: Document higher-order function pattern, provide examples
   
3. **Dynamic column lists**: Some transforms use `{{ column_names }}`
   - **Mitigation**: Use M-code parameter passing or table introspection
   
4. **No backward compatibility**: Users must migrate immediately
   - **Mitigation**: Provide clear error messages pointing to migration guide

### Testing Strategy
1. Unit tests for each refactored component
2. Integration tests for end-to-end compilation
3. Regression tests comparing old vs. new output (where compatible)
4. Example projects to validate real-world usage

## Next Steps

1. ✅ Review and approve this plan (approved - no backward compatibility)
2. Create feature branch for implementation
3. Implement Phase 1 (core changes)
4. Update tests to pass
5. Migrate all example transform files
6. Update documentation
7. Release with breaking change notice

---

**References:**
- Reference implementation: [`reference/expressions.tmdl`](../reference/expressions.tmdl)
- Current builder: [`yaml2pbip/mcode/builder.py`](../yaml2pbip/mcode/builder.py)
- Current transforms: [`yaml2pbip/transforms.py`](../yaml2pbip/transforms.py)
- Expression template: [`yaml2pbip/templates/expressions.tmdl.j2`](../yaml2pbip/templates/expressions.tmdl.j2)