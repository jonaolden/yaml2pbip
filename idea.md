Proceeding. Here are the finalized YAML schemas, validators, and compiler pseudocode to implement `yaml2pbip` with a proper zero-column measure table, cross-table measures, and column policy.

# 1) YAML schemas

## `sources.yml`

```yaml
version: 1
sources:
  sf_main:
    kind: snowflake
    server: xy12345.eu-central-1.snowflakecomputing.com
    warehouse: COMPUTE_WH
    database: SALES            # optional default
    role: ANALYST              # optional
    options:
      implementation: "2.0"    # connector v2 hint
      queryTag: yaml2pbip
```

## `model.yml`

```yaml
version: 1
model:
  name: SalesModel
  culture: en-US

  tables:
    - name: _Measures
      kind: measureTable
      measures:
        - name: Total Profit
          expression: "SUMX ( Sales, Sales[Revenue] - Sales[Cost] )"
          formatString: "#,0.0"

    - name: DimDate
      kind: table
      column_policy: select_only         # select_only | keep_all | hide_extras
      columns:
        - { name: Date, dataType: date }
        - { name: Year, dataType: int64 }
      source:
        use: sf_main
        navigation: { database: SALES, schema: DIM, table: DATE }
      partitions:
        - { name: Full, mode: import }

    - name: FactSales
      kind: table
      column_policy: keep_all
      columns:
        - { name: OrderID, dataType: int64 }
        - { name: Amount, dataType: decimal, formatString: "#,0.00" }
        - { name: OrderDate, dataType: date }
      measures:
        - { name: Orders, expression: "COUNT ( FactSales[OrderID] )" }
      partitions:
        - name: NativeSQL
          mode: import
          use: sf_main
          nativeQuery: |
            select OrderID, Amount, OrderDate
            from SALES.DBO.FactSales

  relationships:
    - { from: FactSales[OrderDate], to: DimDate[Date], cardinality: manyToOne, crossFilter: single }

  roles: []
```

Notes:

* Measures are table-bound but expressions can reference any table.
* `kind: measureTable` emits a zero-column table with measures only.
* `column_policy` controls M shaping:

  * `select_only`: remove undeclared columns.
  * `keep_all`: keep undeclared columns.
  * `hide_extras`: requires schema discovery; see compiler behavior.

# 2) Pydantic models (core)

```python
# yaml2pbip/spec.py
from __future__ import annotations
from typing import List, Literal, Optional, Dict
from pydantic import BaseModel, Field, root_validator, validator
import re

DataType = Literal["int64","decimal","double","bool","string","date","datetime","time","currency","variant"]

class SourceOptions(BaseModel):
    implementation: Optional[Literal["1.0","2.0"]] = None
    queryTag: Optional[str] = None

class Source(BaseModel):
    kind: Literal["snowflake"]
    server: str
    warehouse: Optional[str] = None
    database: Optional[str] = None
    role: Optional[str] = None
    options: Optional[SourceOptions] = None

class SourcesSpec(BaseModel):
    version: int = 1
    sources: Dict[str, Source]

class Column(BaseModel):
    name: str
    dataType: DataType
    formatString: Optional[str] = None
    isHidden: Optional[bool] = None

class Measure(BaseModel):
    name: str
    expression: str
    formatString: Optional[str] = None
    displayFolder: Optional[str] = None
    isHidden: Optional[bool] = None

class Navigation(BaseModel):
    database: Optional[str] = None
    schema: str
    table: str

class Partition(BaseModel):
    name: str
    mode: Literal["import","directquery"] = "import"
    use: Optional[str] = None              # source key
    navigation: Optional[Navigation] = None
    nativeQuery: Optional[str] = None

    @root_validator
    def nav_or_sql(cls, v):
        nav, sql = v.get("navigation"), v.get("nativeQuery")
        if not nav and not sql:
            raise ValueError("partition requires navigation or nativeQuery")
        return v

class Table(BaseModel):
    name: str
    kind: Literal["table","measureTable"] = "table"
    column_policy: Literal["select_only","keep_all","hide_extras"] = "select_only"
    columns: List[Column] = Field(default_factory=list)
    measures: List[Measure] = Field(default_factory=list)
    partitions: List[Partition] = Field(default_factory=list)
    source: Optional[Dict] = None  # passthrough; use Partition.use for actual binding

    @root_validator
    def validate_measure_table(cls, v):
        if v.get("kind") == "measureTable":
            if v.get("columns"):
                raise ValueError("measureTable must not define columns")
            if v.get("partitions"):
                raise ValueError("measureTable must not define partitions")
        return v

class Relationship(BaseModel):
    from_: str = Field(alias="from")  # "Fact[Col]"
    to: str                           # "Dim[Col]"
    cardinality: Literal["oneToOne","oneToMany","manyToOne"]
    crossFilter: Literal["single","both"] = "single"
    isActive: Optional[bool] = True

    @validator("from_","to")
    def endpoint_syntax(cls, v):
        if not re.match(r"^[A-Za-z_][\w ]*\[[A-Za-z_][\w ]*\]$", v):
            raise ValueError("endpoint must be Table[Column]")
        return v

class ModelBody(BaseModel):
    name: str
    culture: str = "en-US"
    tables: List[Table]
    relationships: List[Relationship] = Field(default_factory=list)
    roles: List[Dict] = Field(default_factory=list)

    @validator("tables")
    def unique_table_names(cls, v):
        names = [t.name for t in v]
        if len(names) != len(set(names)):
            raise ValueError("duplicate table name")
        return v

class ModelSpec(BaseModel):
    version: int = 1
    model: ModelBody
```

# 3) Compiler behavior

## Directory layout

```
<Out>/<Model>.SemanticModel/
  definition.pbism
  definition/
    model.tmdl
    relationships.tmdl
    expressions.tmdl
    tables/<Table>.tmdl
<Out>/<Model>.Report/
  definition.pbir
<Out>/<Model>.pbip
```

## Pipeline pseudocode

```python
# yaml2pbip/compile.py
from pathlib import Path
import yaml
from .spec import SourcesSpec, ModelSpec
from .emit import emit_pbism, emit_model_tmdl, emit_table_tmdl, emit_relationships_tmdl, emit_expressions_tmdl, emit_report_by_path

def compile_project(model_yaml: Path, sources_yaml: Path, outdir: Path, stub_report: bool = True, hide_extras_introspect: bool = False):
    sources = SourcesSpec(**yaml.safe_load(sources_yaml.read_text()))
    spec = ModelSpec(**yaml.safe_load(model_yaml.read_text()))

    root = outdir
    sm_dir = root / f"{spec.model.name}.SemanticModel"
    def_dir = sm_dir / "definition"
    tbl_dir = def_dir / "tables"
    rpt_dir = root / f"{spec.model.name}.Report"
    tbl_dir.mkdir(parents=True, exist_ok=True)

    emit_pbism(sm_dir)                                  # marks TMDL project
    emit_model_tmdl(def_dir, spec.model)                # culture, props
    emit_expressions_tmdl(def_dir, sources)             # M helpers per source
    for t in spec.model.tables:
        emit_table_tmdl(tbl_dir, t, sources)            # includes measures; partitions use M helpers
    emit_relationships_tmdl(def_dir, spec.model)        # cross-table relationships

    if stub_report:
        emit_report_by_path(rpt_dir, rel_model_path=f"../{spec.model.name}.SemanticModel")
        (root / f"{spec.model.name}.pbip").write_text(
            '{"version":"1.0","artifacts":["' + f'{spec.model.name}.Report' + '"]}'
        )
```

## Column policy → Power Query shaping

* `select_only`:

  * Append `Table.SelectColumns(Upstream, declared, MissingField.UseNull)`.
  * Then `Table.TransformColumnTypes` for declared types.
* `keep_all`:

  * Skip `SelectColumns`.
  * Still apply `TransformColumnTypes` for declared columns.
* `hide_extras`:

  * If `hide_extras_introspect=True`, connect using the source M helper, enumerate columns for each partition query, and:

    * Create TMDL column entries for every discovered column not in `columns`.
    * Set `isHidden: true` on those stubs.
  * Else degrade to `keep_all` and log a warning.

## Measure table emission

* Write a table object with `name`, no columns block, no partitions block.
* Emit each measure under that table.
* This yields the calculator icon in Desktop.

## Partitions

* For `navigation`:

  * Generate M:

    ```
    let
      DB  = Source.sf_main("SALES"),
      SCH = DB{[Name="DIM", Kind="Schema"]}[Data],
      T   = SCH{[Name="DATE", Kind="Table"]}[Data],
      /* column policy steps here */
    in Types
    ```
* For `nativeQuery`:

  * Generate M:

    ```
    let
      DB  = Source.sf_main(null),
      SQL = "...",
      Out = Value.NativeQuery(DB, SQL, null, [EnableFolding=true]),
      /* column policy steps here */
    in Types
    ```

## Expressions from `sources.yml`

* Emit one M function per source in `expressions.tmdl`, e.g.:

  ```
  section Source;

  shared sf_main = (optionalDatabase as nullable text) as table =>
  let
      Source  = Snowflake.Databases("xy12345.eu-central-1.snowflakecomputing.com",
                 [Warehouse="COMPUTE_WH", Role="ANALYST", QueryTag="yaml2pbip"]),
      DB      = if optionalDatabase <> null
                then Source{[Name=optionalDatabase, Kind="Database"]}[Data]
                else Source
  in  DB;
  ```
* Partitions call `Source.sf_main("SALES")` or `Source.sf_main(null)`.

# 4) TMDL emission templates (Jinja2, illustrative)

## `tables/<Table>.tmdl.j2`

```jinja
table "{{ table.name }}" {
  {% if table.measures %}
  measures: [
    {% for m in table.measures -%}
    measure "{{ m.name }}" {
      expression: "{{ m.expression | replace('\n',' ') }}"
      {% if m.formatString %} formatString: "{{ m.formatString }}"{% endif %}
      {% if m.displayFolder %} displayFolder: "{{ m.displayFolder }}"{% endif %}
      {% if m.isHidden is not none %} isHidden: {{ 'true' if m.isHidden else 'false' }}{% endif %}
    }{{ "," if not loop.last else "" }}
    {% endfor -%}
  ]
  {% endif %}
  {% if table.kind == "table" %}
  columns: [
    {% for c in table.columns -%}
    column "{{ c.name }}" {
      dataType: {{ c.dataType }}
      {% if c.formatString %} formatString: "{{ c.formatString }}"{% endif %}
      {% if c.isHidden is not none %} isHidden: {{ 'true' if c.isHidden else 'false' }}{% endif %}
    }{{ "," if not loop.last else "" }}
    {% endfor -%}
  ]
  partitions: [
    {% for p in table.partitions -%}
    partition "{{ p.name }}" {
      mode: {{ p.mode }}
      query: """
{{ m_code_for_partition(p, table) }}
"""
    }{{ "," if not loop.last else "" }}
    {% endfor -%}
  ]
  {% endif %}
}
```

## `relationships.tmdl.j2`

```jinja
relationships: [
  {% for r in model.relationships -%}
  relationship {
    from: {{ r.from_ }}
    to: {{ r.to }}
    cardinality: {{ r.cardinality }}
    crossFilter: {{ r.crossFilter }}
    isActive: {{ 'true' if r.isActive else 'false' }}
  }{{ "," if not loop.last else "" }}
  {% endfor -%}
]
```

## `expressions.tmdl.j2`

```jinja
expressions: [
  {% for key, src in sources.sources.items() -%}
  expression "Source.{{ key }}" {
    kind: powerQuery
    code: """
section Source;

shared {{ key }} = (optionalDatabase as nullable text) as table =>
let
  Source = Snowflake.Databases("{{ src.server }}",
    [ {% if src.warehouse %} Warehouse="{{ src.warehouse }}", {% endif %}
      {% if src.role %} Role="{{ src.role }}", {% endif %}
      {% if src.options and src.options.queryTag %} QueryTag="{{ src.options.queryTag }}"{% endif %}
    ]),
  DB = if optionalDatabase <> null
       then Source{[Name=optionalDatabase, Kind="Database"]}[Data]
       else Source
in DB;
"""
  }{{ "," if not loop.last else "" }}
  {% endfor -%}
]
```

# 5) CLI sketch

```python
# yaml2pbip/cli.py
import argparse
from pathlib import Path
from .compile import compile_project

def main():
    ap = argparse.ArgumentParser(prog="yaml2pbip")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile")
    c.add_argument("model_yaml", type=Path)
    c.add_argument("sources_yaml", type=Path)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--no-stub-report", action="store_true")
    c.add_argument("--introspect-hide-extras", action="store_true")

    args = ap.parse_args()
    compile_project(
        args.model_yaml,
        args.sources_yaml,
        args.out,
        stub_report=not args.no_stub_report,
        hide_extras_introspect=args.introspect_hide_extras
    )

if __name__ == "__main__":
    main()
```

# 6) Defaults and guards

* Default `column_policy`: `select_only`.
* `hide_extras` without `--introspect`: downgrade to `keep_all` with a warning.
* Disallow columns or partitions on `measureTable`.
* Validate relationship endpoints and duplicate names.
* Stable output order: sort tables and members by name unless `preserve_order: true` is added later.

# 7) Minimal test plan

* Create `sources.yml` and `model.yml` from above.
* Run `yaml2pbip compile model.yml sources.yml --out ./SalesModel`.
* Open `SalesModel/SalesModel.pbip` in Desktop.
* Confirm:

  * `_Measures` shows calculator icon. No columns. Measures visible.
  * DimDate and FactSales load. Column shaping follows policy.
  * Relationship active.
  * Credentials requested on first refresh, as expected.
