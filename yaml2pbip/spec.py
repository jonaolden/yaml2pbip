"""Pydantic models for yaml2pbip specification validation."""
from __future__ import annotations
from typing import List, Literal, Optional, Dict
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
_HAS_PYDANTIC = True

import re

DataType = Literal["int64", "decimal", "double", "boolean", "string", "date", "dateTime", "time", "currency", "variant"]


class SourceOptions(BaseModel):
    """Options for source configuration."""
    model_config = ConfigDict(extra="allow")
    
    implementation: Optional[Literal["1.0", "2.0"]] = None
    queryTag: Optional[str] = None
    commandTimeout: Optional[int] = None
    encryptConnection: Optional[bool] = None
    trustServerCertificate: Optional[bool] = None
    queryFolding: Optional[bool] = None
    nativeQuery: Optional[bool] = None
    useProxyGateway: Optional[bool] = None
    sessionType: Optional[str] = None


class Source(BaseModel):
    """Source connection configuration."""
    kind: Literal["snowflake", "azuresql", "sqlserver", "databricks", "excel"]
    server: Optional[str] = None
    warehouse: Optional[str] = None
    database: Optional[str] = None
    role: Optional[str] = None
    path: Optional[str] = None  # For Databricks
    file_path: Optional[str] = None  # For Excel
    workbook_name: Optional[str] = None  # For Excel
    description: Optional[str] = None
    options: Optional[SourceOptions] = None


class SourcesSpec(BaseModel):
    """Top-level sources specification."""
    version: int = 1
    sources: Dict[str, Source]


class Column(BaseModel):
    """Column definition in a table."""
    name: str
    dataType: DataType
    formatString: Optional[str] = None
    isHidden: Optional[bool] = None
    sourceColumn: Optional[str] = None  # For calculated tables: references source like "Financials[Product]"
    summarizeBy: Optional[Literal["none", "sum", "average", "count", "min", "max"]] = None
    isNameInferred: Optional[bool] = None  # For calculated table columns that inherit from source


class Measure(BaseModel):
    """Measure definition in a table."""
    name: str
    expression: str
    formatString: Optional[str] = None
    displayFolder: Optional[str] = None
    isHidden: Optional[bool] = None


class CalculationGroupItem(BaseModel):
    """Calculation group item definition."""
    name: str
    expression: str
    ordinal: Optional[int] = None
    formatString: Optional[str] = None


class CalculatedTableDef(BaseModel):
    """Definition for a calculated table with DAX expression or template reference.
    
    Either `expression` or `template` must be provided, but not both.
    - expression: Direct DAX code (e.g., "DISTINCT(Financials[Country])")
    - template: Reference to a .dax file (e.g., "metadata_table" loads metadata_table.dax)
    """
    expression: Optional[str] = None
    template: Optional[str] = None
    description: Optional[str] = None
    
    @model_validator(mode='after')
    def validate_expression_or_template(self):
        """Ensure exactly one of expression or template is provided."""
        if self.expression and self.template:
            raise ValueError("calculatedTableDef cannot have both 'expression' and 'template'")
        if not self.expression and not self.template:
            raise ValueError("calculatedTableDef must have either 'expression' or 'template'")
        return self


class Navigation(BaseModel):
    """Navigation specification for table sources."""
    database: Optional[str] = None
    schema_: str = Field(alias="schema")
    table: str


class Partition(BaseModel):
    """Partition definition for a table."""
    name: str
    mode: Literal["import", "directquery", "directLake"] = "import"
    use: Optional[str] = None  # source key
    navigation: Optional[Navigation] = None
    nativeQuery: Optional[str] = None
    # For entity partitions (directLake)
    entityName: Optional[str] = None
    schemaName: Optional[str] = None
    expressionSource: Optional[str] = None
    # Custom transforms (list of transform names)
    custom_steps: List[str] = Field(default_factory=list)

    @field_validator("navigation", mode="before")
    @classmethod
    def parse_compact_navigation(cls, v):
        """
        Accept compact navigation strings of the form
        'DATABASE.SCHEMA.TABLE' and convert them into the mapping
        expected by the Navigation model.
        """
        if v is None:
            return v
        if isinstance(v, str):
            parts = v.split(".")
            if len(parts) != 3:
                raise ValueError("navigation string must be 'database.schema.table'")
            return {"database": parts[0], "schema": parts[1], "table": parts[2]}
        return v

    @model_validator(mode='after')
    def validate_partition_type(self):
        """Validate that partition has correct fields based on mode."""
        if self.mode == "directLake":
            # Entity partition requires entityName, schemaName, and expressionSource
            if not self.entityName or not self.schemaName or not self.expressionSource:
                raise ValueError("directLake partition requires entityName, schemaName, and expressionSource")
            if self.navigation or self.nativeQuery:
                raise ValueError("directLake partition should not have navigation or nativeQuery")
        else:
            # M partition requires either navigation, nativeQuery, OR just a source reference (for simple sources like Excel)
            # At least 'use' should be specified
            if not self.use:
                raise ValueError("import/directquery partition requires 'use' field to reference a source")
            if self.entityName or self.schemaName or self.expressionSource:
                raise ValueError("import/directquery partition should not have entityName, schemaName, or expressionSource")
        return self


class Table(BaseModel):
    """Table definition in the model."""
    name: str
    kind: Literal["table", "measureTable", "calculatedTable", "fieldParameter", "calculationGroup"] = "table"
    column_policy: Literal["select_only", "keep_all", "hide_extras"] = "keep_all"
    columns: List[Column] = Field(default_factory=list)
    measures: List[Measure] = Field(default_factory=list)
    partitions: List[Partition] = Field(default_factory=list)
    base_measures: Optional[Dict[str, str] | List[Dict[str, str]]] = None  # e.g., {"sum": "table.col1, table.col2"} or [{"sum": "..."}]
 
    @model_validator(mode="before")
    @classmethod
    def populate_partitions_and_base_measures(cls, values):
        """
        Allow either a single partition mapping or a list in the YAML input.
        If any partition omits 'name', populate it from the table name using
        the required transformation: upper-case and replace spaces with '_'.
        
        Also processes base_measures to generate Measure objects automatically.
        """
        if not values:
            return values
        tbl_name = values.get("name")
        
        # Handle partitions
        parts = values.get("partitions")
        if parts is None:
            values["partitions"] = []
        else:
            # Normalize single-mapping into list
            if isinstance(parts, dict):
                parts = [parts]
            normalized = []
            for p in parts:
                # p may already be a Partition instance / non-dict; preserve as-is
                if not isinstance(p, dict):
                    normalized.append(p)
                    continue
                if not p.get("name"):
                    if isinstance(tbl_name, str):
                        p["name"] = tbl_name.upper().replace(" ", "_")
                    else:
                        p["name"] = "PARTITION"
                normalized.append(p)
            values["partitions"] = normalized
        
        # Handle base_measures - expand into actual measure definitions
        base_measures = values.get("base_measures")
        if base_measures:
            # Normalize base_measures to dict format
            # Supports both dict and list of dicts (YAML list syntax)
            if isinstance(base_measures, list):
                # Convert list of single-key dicts to single dict
                # e.g., [{"sum": "col1"}, {"avg": "col2"}] -> {"sum": "col1", "avg": "col2"}
                normalized_base = {}
                for item in base_measures:
                    if isinstance(item, dict):
                        normalized_base.update(item)
                base_measures = normalized_base
            
            if isinstance(base_measures, dict) and base_measures:
                existing_measures = values.get("measures", [])
                if not isinstance(existing_measures, list):
                    existing_measures = []
                
                generated_measures = cls._generate_measures_from_base(base_measures)
                # Prepend generated measures so explicit measures can override
                values["measures"] = generated_measures + existing_measures
        
        return values
    
    @staticmethod
    def _generate_measures_from_base(base_measures: Dict[str, str]) -> List[Dict]:
        """Generate measure definitions from base_measures specification.
        
        Args:
            base_measures: Dict mapping aggregation function to column references
                          e.g., {"sum": "fact_sales.sales_amount, fact_sales.sales_profit",
                                 "avg": "customer.rating"}
        
        Returns:
            List of measure definition dicts
        """
        measures = []
        
        for agg_func, columns_str in base_measures.items():
            # Parse comma-separated column references
            column_refs = [col.strip() for col in columns_str.split(',')]
            
            for col_ref in column_refs:
                if not col_ref:
                    continue
                
                # Parse table.column format
                if '.' in col_ref:
                    table_name, column_name = col_ref.rsplit('.', 1)
                else:
                    # If no table specified, assume current table
                    table_name = None
                    column_name = col_ref
                
                # Generate measure name: {agg_func}_{column_name}
                measure_name = f"{agg_func}_{column_name}"
                
                # Generate DAX expression based on aggregation function
                if table_name:
                    column_ref_dax = f"'{table_name}'[{column_name}]"
                else:
                    column_ref_dax = f"[{column_name}]"
                
                dax_expression = Table._generate_dax_expression(agg_func, column_ref_dax)
                
                measures.append({
                    "name": measure_name,
                    "expression": dax_expression
                })
        
        return measures
    
    @staticmethod
    def _generate_dax_expression(agg_func: str, column_ref: str) -> str:
        """Generate DAX expression for a given aggregation function.
        
        Args:
            agg_func: Aggregation function name (sum, avg, min, max, count, etc.)
            column_ref: DAX column reference like 'Table'[Column] or [Column]
        
        Returns:
            Complete DAX expression
        """
        agg_func_lower = agg_func.lower()
        
        # Map aggregation functions to DAX functions
        dax_functions = {
            "sum": f"SUM({column_ref})",
            "avg": f"AVERAGE({column_ref})",
            "average": f"AVERAGE({column_ref})",
            "min": f"MIN({column_ref})",
            "max": f"MAX({column_ref})",
            "count": f"COUNT({column_ref})",
            "countrows": f"COUNTROWS({column_ref})",
            "distinctcount": f"DISTINCTCOUNT({column_ref})",
        }
        
        return dax_functions.get(agg_func_lower, f"{agg_func.upper()}({column_ref})")
 
    # For calculatedTable: DAX expression
    calculatedTableDef: Optional[CalculatedTableDef] = None
    # For calculationGroup: list of calculation group items
    calculationGroupItems: List[CalculationGroupItem] = Field(default_factory=list)
    source: Optional[Dict] = None  # passthrough; use Partition.use for actual binding

    @model_validator(mode='after')
    def validate_table_kind_constraints(self):
        """Validate table constraints based on table kind."""
        if self.kind == "measureTable":
            # Measure tables must only have measures, no columns or partitions
            if self.columns:
                raise ValueError("measureTable must not define columns")
            if self.partitions:
                raise ValueError("measureTable must not define partitions")
            if not self.measures:
                raise ValueError("measureTable must define at least one measure")
        elif self.kind == "calculatedTable":
            # Calculated tables must not have partitions and must have DAX expression or template
            if self.partitions:
                raise ValueError("calculatedTable must not define partitions")
            if not self.calculatedTableDef:
                raise ValueError("calculatedTable must define calculatedTableDef")
            # The CalculatedTableDef validator ensures exactly one of expression or template is set
        elif self.kind == "fieldParameter":
            # Field parameter tables must not have partitions
            if self.partitions:
                raise ValueError("fieldParameter must not define partitions")
        elif self.kind == "calculationGroup":
            # Calculation group tables must not have partitions and must have calculation group items
            if self.partitions:
                raise ValueError("calculationGroup must not define partitions")
            if not self.calculationGroupItems:
                raise ValueError("calculationGroup must define at least one calculationGroupItem")
        elif self.kind == "table":
            # Regular tables can have columns, measures, and partitions
            # Validate that import/directquery tables have at least one partition
            if not self.partitions:
                raise ValueError("table kind 'table' must define at least one partition")
        return self


class Relationship(BaseModel):
    """Relationship definition between tables.
 
    New usage: specify `using` as a single column name or a comma-separated
    pair "fromCol, toCol". Older explicit `fromcolumn`/tocolumn` fields are
    not required for the new template behavior.
    """
    fromtable: str = Field(alias="from")  # "Fact" (YAML key 'from')
    totable: str = Field(alias="to")      # "Dim"  (YAML key 'to')
    using: Optional[str] = None  # "Col" or "ColFrom, ColTo"
    cardinality: Literal["oneToOne", "oneToMany", "manyToOne"]
    crossFilter: Literal["single", "both"] = "single"
    isActive: Optional[bool] = True

    @field_validator("fromtable", "totable", "using")
    @classmethod
    def no_brackets_in_relationships(cls, v):
        """Validate that table and column names (and using parts) do not contain brackets."""
        if v is None:
            return v
        if not isinstance(v, str):
            return v
        # `using` may contain a comma; ensure there are no bracket characters anywhere.
        if '[' in v or ']' in v:
            raise ValueError("relationship table and column names must not contain brackets")
        return v


class ModelBody(BaseModel):
    """Model body containing tables and relationships."""
    name: str
    culture: str = "en-US"
    tables: List[Table]
    relationships: List[Relationship] = Field(default_factory=list)
    roles: List[Dict] = Field(default_factory=list)

    @field_validator("tables")
    @classmethod
    def unique_table_names(cls, v):
        """Validate that table names are unique."""
        names = [t.name for t in v]
        if len(names) != len(set(names)):
            raise ValueError("duplicate table name")
        return v


class ModelSpec(BaseModel):
    """Top-level model specification."""
    version: int = 1
    model: ModelBody