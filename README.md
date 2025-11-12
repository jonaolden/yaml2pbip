# yaml2pbip

A compiler that converts YAML model specs into Power BI Project (.pbip) with TMDL files.

## Quick overview

yaml2pbip lets you define Power BI semantic models in readable YAML and compiles them to a .pbip project (TMDL + artifacts).

Key benefits:
- Write models in YAML for clean diffs
- Pydantic schema validation
- Generates a ready-to-open .pbip for Power BI Desktop

## Installation

Requirements:
- Python >= 3.10
- Power BI Desktop (to open generated .pbip)

Install from source:

```bash
git clone <repository-url>
cd yaml2pbip
pip install -e .
```

## Quick start

1. Create or reuse examples in [`examples/`](examples/:1).

2. Compile:

```bash
# installed CLI
yaml2pbip compile examples/model.yml examples/sources.yml --out ./output

# or using module form
python -m yaml2pbip compile examples/model.yml examples/sources.yml --out ./output
```

3. Open the generated `<ModelName>.pbip` in Power BI Desktop.

## CLI

```bash
# basic
yaml2pbip compile <model.yml> <sources.yml> --out <output-dir>

# options
-v, --verbose             # verbose logging

# other
yaml2pbip version
yaml2pbip --help
yaml2pbip compile --help
```

## Output layout

```
<output-dir>/
  <ModelName>.pbip
  <ModelName>.SemanticModel/
    definition.pbism
    definition/
      model.tmdl
      relationships.tmdl
      expressions.tmdl
      tables/
        <Table>.tmdl
  <ModelName>.Report/
    definition.pbir
```

## Minimal YAML overview

sources.yml (connections):

```yaml
version: 1
sources:
  sf_main:
    kind: snowflake
    server: your-account.snowflakecomputing.com
    warehouse: WH
    database: DB
    role: ROLE
    options:
      implementation: "2.0"
      queryTag: yaml2pbip
```

model.yml (model skeleton):

```yaml
version: 1
model:
  name: ModelName
  culture: en-US
  tables:
    - name: FactSales
      kind: table
      column_policy: keep_all
      source:
        use: sf_main
        navigation:
          database: SALES
          schema: FACT
          table: SALES
  relationships:
    - from: FactSales[OrderDate]
      to: DimDate[Date]
      cardinality: manyToOne
```

See examples in [`examples/`](examples/:1) for annotated, working files.

## Notes & limitations

- hide_extras is accepted but currently behaves like `keep_all` (introspection not implemented).
- Only Snowflake and Excel connectors are tested; other connectors have template stubs.
- Advanced features (calculated columns/tables, perspectives, translations, RLS) are not implemented yet.

## Development

Install in editable mode and run locally:

```bash
pip install -e .
yaml2pbip compile examples/model.yml examples/sources.yml --out test-output -v
```

Or:

```bash
python -m yaml2pbip compile examples/model.yml examples/sources.yml --out test-output
```

## Examples

The [`examples/sample_model/README.md`](examples/sample_model/README.md:1) and [`examples/financial_sample/README.md`](examples/financial_sample/README.md:1) contain runnable samples and guidance.

## Project layout

```
yaml2pbip/
  yaml2pbip/           # package
  templates/           # Jinja2 templates used for TMDL
  examples/            # example YAMLs
  testing/             # unit tests and sample pbip artifacts
```

## Version

Current version: 0.1.0 (MVP)

For full design notes see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md:1).