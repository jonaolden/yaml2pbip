# yaml2pbip Architecture

## Overview

yaml2pbip converts YAML model definitions into Power BI Project (PBIP) files using TMDL format. This document describes the refactored architecture that prioritizes maintainability, testability, and source-agnostic design.

## Architecture Principles

1. **Source Agnostic**: All data source-specific logic lives in Jinja2 templates, not Python code
2. **Builder Pattern**: Complex M code construction uses fluent builder API
3. **Separation of Concerns**: Clear module boundaries with single responsibilities
4. **Template-First**: Jinja2 templates are the source of truth for M code generation

---

## Module Structure

```
yaml2pbip/
├── __init__.py
├── cli.py              # Command-line interface
├── compile.py          # High-level compilation orchestration
├── discovery.py        # YAML file discovery
├── emit.py            # TMDL emission (refactored - now orchestration only)
├── spec.py            # Pydantic models for validation
├── transforms.py      # Transform loading and rendering
│
├── mcode/             # M code generation (NEW MODULE)
│   ├── __init__.py
│   ├── builder.py     # MCodePartitionBuilder class
│   ├── source_resolver.py  # Template-based source generation
│   └── utils.py       # Type mapping and utilities
│
└── templates/
    ├── model.tmdl.j2
    ├── table.tmdl.j2
    ├── expressions.tmdl.j2
    └── sources/       # Source-specific templates
        ├── snowflake.j2        # Standard template
        ├── snowflake_inline.j2 # Inline connection call
        ├── azuresql.j2
        ├── azuresql_inline.j2
        ├── databricks.j2
        ├── databricks_inline.j2
        ├── sqlserver.j2
        ├── sqlserver_inline.j2
        └── excel.j2
```

---

## Key Components

### 1. emit.py (Refactored)

**Before:** 521 lines with embedded source-specific logic  
**After:** ~200 lines focused on orchestration

**Key Changes:**
- Removed `_build_snowflake_call()` function (165-188 lines)
- Removed `_map_datatype_to_m()` function (moved to mcode/utils.py)
- Simplified `generate_partition_mcode()` from 290+ lines to ~40 lines using builder pattern
- All source connection logic delegated to templates

**Example (New Pattern):**
```python
def generate_partition_mcode(partition, table, sources, transforms=None):
    """Generate M code using builder pattern."""
    builder = MCodePartitionBuilder(partition, table, sources)
    
    if partition.navigation:
        return (builder
                .add_source_connection()
                .add_navigation()
                .add_column_selection()
                .add_type_transformation()
                .add_custom_transforms(transforms)
                .build())
```

---

### 2. mcode/builder.py

**Purpose:** Construct partition M code using builder pattern

**Class:** `MCodePartitionBuilder`

**Methods:**
- `add_source_connection()` - Add data source connection
- `add_navigation()` - Navigate to database/schema/table
- `add_native_query()` - Execute SQL query
- `add_column_selection()` - Select columns based on policy
- `add_type_transformation()` - Apply column type transformations
- `add_custom_transforms()` - Apply user-defined transforms
- `build()` - Construct final M code string

**Benefits:**
- Each method has single responsibility
- Easy to test individual steps
- Clear, readable construction flow
- Extensible for new features

---

### 3. mcode/source_resolver.py

**Purpose:** Generate source connection M code using templates

**Key Functions:**

#### `generate_inline_source_mcode(source, source_key, inline=True)`
Generates source connection code using templates. When `inline=True`, uses `*_inline.j2` templates that produce just the connection function call (e.g., `Snowflake.Databases(...)`).

#### `parse_source_mcode(mcode)`
Parses standard source templates to extract variable definitions and final variable name.

#### `resolve_database_navigation(source, source_key, database)`
Generates database navigation lines using inline templates.

**Template Resolution:**
1. Try `sources/{kind}_inline.j2` first (for inline calls)
2. Fall back to `sources/{kind}.j2` (standard format)
3. Extract inline code from standard if needed

---

### 4. mcode/utils.py

**Purpose:** Utility functions for M code generation

**Key Functions:**
- `map_datatype_to_m(datatype)` - Convert Pydantic type to M type
- `format_column_list(columns)` - Format column names for M
- `format_types_list(columns)` - Format type list for TransformColumnTypes
- `ensure_trailing_comma(line)` - Comma handling utilities
- `remove_trailing_comma(line)`
- `normalize_indentation(lines)` - Consistent indentation

---

### 5. Template Strategy

#### Standard Templates (`sources/{kind}.j2`)
Generate complete M expressions with let...in structure:

```m
let
    Source = Snowflake.Databases("server.snowflake.com"),
    Database = Source{[Name = "DB", Kind = "Database"]}[Data]
in
    Database
```

#### Inline Templates (`sources/{kind}_inline.j2`)
Generate just the connection function call for embedding:

```m
Snowflake.Databases("server.snowflake.com", "warehouse", [Role = "role"])
```

**Usage:**
- **Inline**: When embedding connection directly in partition M code (avoids composite model errors)
- **Standard**: When creating shared expressions in expressions.tmdl

---

## Data Flow

```
YAML Files
    ↓
spec.py (Validation)
    ↓
compile.py (Orchestration)
    ↓
emit.py (TMDL Generation)
    ↓
┌─────────────────────────────┐
│  generate_partition_mcode() │
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│  MCodePartitionBuilder      │
│  - add_source_connection()  │
│  - add_navigation()         │
│  - add_column_selection()   │
│  - add_type_transformation()│
│  - add_custom_transforms()  │
│  - build()                  │
└─────────────┬───────────────┘
              ↓
    ┌─────────┴─────────┐
    ↓                   ↓
source_resolver      utils.py
    ↓                   ↓
templates/*_inline.j2  Type mappings
                       Formatting
```

---

## Adding New Data Sources

To add a new data source (e.g., PostgreSQL):

### 1. Add to spec.py
```python
class Source(BaseModel):
    kind: Literal["snowflake", "azuresql", "sqlserver", 
                  "databricks", "excel", "postgresql"]  # Add here
    # ... other fields
```

### 2. Create Standard Template
`templates/sources/postgresql.j2`:
```jinja2
let
    Source = PostgreSQL.Database("{{ src.server }}", "{{ src.database }}")
in
    Source
```

### 3. Create Inline Template
`templates/sources/postgresql_inline.j2`:
```jinja2
PostgreSQL.Database("{{ src.server }}", "{{ src.database }}")
```

### 4. Done!
No Python code changes required. The system automatically:
- Discovers templates by source kind
- Uses templates for M code generation
- Handles inline vs standard formatting

---

## Benefits of Refactored Architecture

### 1. Maintainability
- **Clear responsibilities**: Each module has one job
- **Small functions**: Most functions < 50 lines
- **No magic**: Explicit flow through builder pattern

### 2. Testability
- **Unit testable**: Each builder method can be tested independently
- **Mock-friendly**: Clear interfaces for dependency injection
- **Integration tested**: Existing tests verify backward compatibility

### 3. Source Agnostic
- **Template-driven**: All source logic in Jinja2
- **Zero Python changes**: New sources = new templates
- **Consistent patterns**: Same approach for all sources

### 4. Extensibility
- **Builder pattern**: Easy to add new transformation steps
- **Plugin architecture**: Templates are plugins
- **Minimal coupling**: Components communicate through interfaces

---

## Migration Notes

### Backward Compatibility

All existing functionality preserved:
- ✅ All tests pass without modification
- ✅ Same M code output
- ✅ Same API surface

### Deprecated (But Still Functional)

The following internal functions still exist as wrappers for backward compatibility:
- `generate_source_mcode()` - Now wraps `generate_inline_source_mcode()`

### Removed Internal Functions

These were internal-only and removed:
- `_build_snowflake_call()` - Logic moved to templates
- `_map_datatype_to_m()` - Moved to mcode/utils.py
- Nested helper functions in `generate_partition_mcode()`

---

## Code Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| emit.py lines | 521 | ~200 | -62% |
| Largest function | 290 lines | 40 lines | -86% |
| Source-specific code in Python | 24 lines | 0 lines | -100% |
| Template files | 5 | 10 | +100% |
| Total Python lines | 521 | 630 | +21% |

*While total Python increased slightly, the code is now:*
- More modular
- Easier to test
- Clearer to understand
- Source-agnostic

---

## Future Enhancements

With this architecture, these become easy:

1. **New Sources**: Just add templates
2. **Custom Transform Steps**: Already supported
3. **Alternative M Code Generators**: Swap builder implementation
4. **Source Mixins**: Combine template features
5. **Unit Testing**: Test each builder method independently
6. **Performance Optimization**: Profile and optimize specific methods

---

## Questions?

For more information, see:
- `mcode/builder.py` - Detailed builder implementation
- `mcode/source_resolver.py` - Template resolution logic  
- `templates/sources/` - Source-specific examples
- Test files - Usage examples