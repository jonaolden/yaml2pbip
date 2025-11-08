# yaml2pbip

A compiler that converts YAML specifications to Power BI Project (.pbip) format with TMDL (Tabular Model Definition Language) files.

## Overview

yaml2pbip simplifies Power BI semantic model development by allowing you to define your models in clean, version-control-friendly YAML files instead of managing complex TMDL syntax directly.

**Key Benefits:**
- 📝 Write models in simple, readable YAML
- 🔄 Better version control and diffing
- 🎯 Focus on structure, not syntax
- 🚀 Faster iteration and development
- ✅ Schema validation with Pydantic

## Features

- ✨ **Measure Tables**: Zero-column tables for organizing cross-table measures
- 📊 **Column Policies**: Control column selection (`select_only`, `keep_all`, `hide_extras`)
- 🔌 **Flexible Partitions**: Both navigation-based and native SQL support
- 🔗 **Relationships**: Easy relationship definition with cardinality
- 🎨 **Format Strings**: Apply formatting to columns and measures
- 🏷️ **Type System**: Rich data type support (int64, decimal, string, date, datetime, boolean, etc.)
- ☁️ **Snowflake Support**: First-class Snowflake connector support

## Installation

**Requirements:**
- Python >= 3.10
- Power BI Desktop (to open generated .pbip files)

**Install from source:**

```bash
# Clone the repository
git clone <repository-url>
cd yaml2pbip

# Install dependencies
pip install -e .
```

## Quick Start

1. Create your YAML files (or use examples):

```bash
# Create sources.yml defining your data connections
# Create model.yml defining your semantic model
```

2. Compile to Power BI Project:

```bash
yaml2pbip compile model.yml sources.yml --out ./output
```

3. Open the generated `.pbip` file in Power BI Desktop

See [`examples/`](examples/) for complete working examples.

## Usage

### Command Line Interface

```bash
# Basic compilation
yaml2pbip compile <model.yml> <sources.yml> --out <output-directory>

# Options
--no-stub-report          # Don't create a stub report
--introspect-hide-extras  # Enable hide_extras introspection (MVP: not implemented)
-v, --verbose             # Enable verbose logging

# Show version
yaml2pbip version

# Help
yaml2pbip --help
yaml2pbip compile --help
```

### Output Structure

The compiler generates a complete Power BI Project:

```
<output-dir>/
  <ModelName>.pbip                # Project file (open in Power BI Desktop)
  <ModelName>.SemanticModel/
    definition.pbism              # Semantic model metadata
    definition/
      model.tmdl                  # Model properties
      relationships.tmdl          # Relationships
      expressions.tmdl            # M source functions
      tables/
        <Table1>.tmdl            # Table definitions
        <Table2>.tmdl
        ...
  <ModelName>.Report/
    definition.pbir               # Report definition (stub)
```

## YAML Schema Overview

### sources.yml

Defines data source connections:

```yaml
version: 1
sources:
  source_name:
    kind: snowflake
    server: your-server.snowflakecomputing.com
    warehouse: YOUR_WH
    database: YOUR_DB
    role: YOUR_ROLE
    options:
      implementation: "2.0"
      queryTag: yaml2pbip
```

**Key Concepts:**
- **Source name**: Used to reference the source in [`model.yml`](model.yml)
- **kind**: Currently only `snowflake` is supported
- **options**: Connector-specific settings (implementation version, query tags)

### model.yml

Defines your semantic model structure:

```yaml
version: 1
model:
  name: ModelName
  culture: en-US
  
  tables:
    - name: TableName
      kind: table  # or measureTable
      column_policy: select_only  # or keep_all, hide_extras
      columns:
        - name: ColumnName
          dataType: int64
          formatString: "#,0"
          description: "Column description"
      measures:
        - name: MeasureName
          expression: "SUM ( Table[Column] )"
          formatString: "#,0.00"
          description: "Measure description"
      source:
        use: source_name
        navigation:
          database: DATABASE
          schema: SCHEMA
          table: TABLE
      partitions:
        - name: PartitionName
          mode: import  # or directquery
          description: "Partition description"
  
  relationships:
    - from: FactTable[ForeignKey]
      to: DimTable[PrimaryKey]
      cardinality: manyToOne  # or oneToOne, oneToMany, manyToMany
      crossFilter: single  # or both
      description: "Relationship description"
```

**Key Concepts:**
- **Measure Tables**: Use `kind: measureTable` for zero-column tables containing cross-table measures
- **Column Policies**: Control how columns from the source are handled
- **Partitions**: Define data loading with navigation paths or native SQL queries
- **Relationships**: Define foreign key relationships with cardinality

See [`examples/`](examples/) for comprehensive, annotated examples.

## Features in Detail

### 1. Measure Tables

Create zero-column tables to organize cross-table measures:

```yaml
tables:
  - name: _Measures
    kind: measureTable
    measures:
      - name: Total Profit
        expression: "SUMX ( FactSales, FactSales[Revenue] - FactSales[Cost] )"
        formatString: "$#,0"
```

**Benefits:**
- Organize measures logically separate from data tables
- Create calculations that reference multiple tables
- Cleaner model structure

### 2. Column Policies

Control how columns from the data source are included:

#### `select_only`
Only explicitly declared columns are included. Best for dimension tables where you want precise control.

```yaml
tables:
  - name: DimDate
    column_policy: select_only
    columns:
      - name: Date
        dataType: dateTime
      - name: Year
        dataType: int64
```

#### `keep_all`
All source columns are included, but only declared columns get metadata (descriptions, format strings). Ideal for fact tables.

```yaml
tables:
  - name: FactSales
    column_policy: keep_all
    columns:
      - name: Revenue
        dataType: decimal
        formatString: "$#,0.00"
        description: "Total revenue"
```

#### `hide_extras` (MVP: Not Implemented)
Would introspect the source schema and include all columns, hiding undeclared ones. Currently treated as `keep_all`.

### 3. Partition Types

#### Navigation-based Partitions

Direct table access using database navigation:

```yaml
source:
  use: sf_main
  navigation:
    database: SALES
    schema: DIM
    table: DATE

partitions:
  - name: Full
    mode: import
```

#### Native SQL Partitions

Custom SQL queries for data transformation or filtering:

```yaml
partitions:
  - name: CurrentYear
    mode: import
    use: sf_main
    nativeQuery: |
      SELECT OrderID, Amount, OrderDate
      FROM SALES.FACT.SALES
      WHERE OrderDate >= DATEADD(year, -1, CURRENT_DATE())
```

### 4. Data Source Configuration

Configure Snowflake connections with warehouse, database, and role:

```yaml
sources:
  sf_main:
    kind: snowflake
    server: xy12345.snowflakecomputing.com
    warehouse: COMPUTE_WH
    database: SALES
    role: ANALYST
    options:
      implementation: "2.0"
      queryTag: yaml2pbip
```

### 5. Relationship Management

Define relationships with cardinality and cross-filter behavior:

```yaml
relationships:
  - from: FactSales[OrderDate]
    to: DimDate[Date]
    cardinality: manyToOne
    crossFilter: single
    description: "Links sales to date dimension"
```

**Cardinality options:**
- `manyToOne` (most common for fact → dimension)
- `oneToMany`
- `oneToOne`
- `manyToMany`

**Cross-filter options:**
- `single` (default, one-way filtering)
- `both` (bidirectional filtering)

### 6. Type System and Format Strings

Rich data type support with optional format strings:

```yaml
columns:
  - name: Revenue
    dataType: decimal
    formatString: "$#,0.00"
  
  - name: Date
    dataType: dateTime
  
  - name: Quantity
    dataType: int64
    formatString: "#,0"
  
  - name: IsActive
    dataType: boolean
```

**Supported data types:**
- `int64` - Integer numbers
- `decimal` - Decimal numbers with precision
- `double` - Floating point numbers
- `string` - Text values
- `date` - Date only
- `dateTime` - Date and time
- `boolean` - True/false values
- `currency` - Currency values

**Common format strings:**
- `$#,0` - Currency with thousands separator
- `#,0.00` - Decimal with two places
- `0.00%` - Percentage format
- `#,0` - Integer with thousands separator

## Project Structure

```
yaml2pbip/
  __init__.py           # Package initialization and version
  spec.py               # Pydantic models for YAML validation
  compile.py            # Main compilation pipeline
  emit.py               # TMDL emission functions
  cli.py                # Command-line interface
  __main__.py           # Python module entry point
  templates/            # Jinja2 templates for TMDL generation
    model.tmdl.j2
    table.tmdl.j2
    relationships.tmdl.j2
    expressions.tmdl.j2
examples/               # Example YAML files
  sources.yml           # Sample data source configuration
  model.yml             # Sample semantic model
  README.md             # Detailed examples documentation
```

## Development

### Running from Source

Install in development mode:

```bash
pip install -e .
```

Run the compiler:

```bash
# Using the installed command
yaml2pbip compile examples/model.yml examples/sources.yml --out test-output

# Or using Python module
python -m yaml2pbip compile examples/model.yml examples/sources.yml --out test-output
```

### Testing Changes

After making changes to the code:

```bash
# Run with verbose output to see detailed logging
yaml2pbip compile examples/model.yml examples/sources.yml --out test-output -v

# Open the generated .pbip file in Power BI Desktop to validate
```

### Contributing

Contributions are welcome! When contributing:

1. Ensure your code follows the existing style
2. Update documentation for any new features
3. Test with the example files to verify functionality
4. Consider adding new examples for significant features

## MVP Limitations

This is an MVP (Minimum Viable Product) implementation with some known limitations:

### 1. hide_extras Introspection
The `hide_extras` column policy is accepted but not yet implemented. Currently, it behaves the same as `keep_all`. Full implementation would require:
- Connecting to the data source during compilation
- Introspecting the source table schema
- Generating TMDL with hidden columns for undeclared fields

### 2. Data Source Support
Currently only supports **Snowflake** as a data source. Future versions may add:
- Azure SQL Database
- SQL Server
- Other Power BI connectors

### 3. Row-Level Security
Role definitions are accepted in the YAML schema but not fully implemented in the TMDL output. Basic structure is generated but role-based filtering is not yet supported.

### 4. Advanced Features
Some advanced Power BI features not yet supported:
- Calculated tables
- Calculated columns
- Perspectives
- Translations
- Annotations
- Query groups

Future versions will address these limitations based on user feedback and requirements.

## Examples

The [`examples/`](examples/) directory contains a complete working example:

- **[`sources.yml`](examples/sources.yml)**: Snowflake data source configuration
- **[`model.yml`](examples/model.yml)**: Comprehensive semantic model with:
  - Measure table with cross-table calculations
  - Date dimension with `select_only` policy
  - Product dimension with `select_only` policy
  - Sales fact table with `keep_all` policy and native SQL partition
  - Relationships between fact and dimension tables

See the [`examples/README.md`](examples/README.md) for detailed documentation of the example files and how to use them.

## License

This project implements the specifications defined in [`idea.md`](idea.md).

## Version

Current version: **0.1.0** (MVP)

For the latest changes and updates, check the project repository.