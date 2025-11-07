"""Pydantic models for yaml2pbip specification validation."""
from __future__ import annotations
from typing import List, Literal, Optional, Dict
from pydantic import BaseModel, Field, field_validator, model_validator
import re

DataType = Literal["int64", "decimal", "double", "bool", "string", "date", "datetime", "time", "currency", "variant"]


class SourceOptions(BaseModel):
    """Options for source configuration."""
    implementation: Optional[Literal["1.0", "2.0"]] = None
    queryTag: Optional[str] = None


class Source(BaseModel):
    """Source connection configuration."""
    kind: Literal["snowflake"]
    server: str
    warehouse: Optional[str] = None
    database: Optional[str] = None
    role: Optional[str] = None
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


class Measure(BaseModel):
    """Measure definition in a table."""
    name: str
    expression: str
    formatString: Optional[str] = None
    displayFolder: Optional[str] = None
    isHidden: Optional[bool] = None


class Navigation(BaseModel):
    """Navigation specification for table sources."""
    database: Optional[str] = None
    schema_: str = Field(alias="schema")
    table: str


class Partition(BaseModel):
    """Partition definition for a table."""
    name: str
    mode: Literal["import", "directquery"] = "import"
    use: Optional[str] = None  # source key
    navigation: Optional[Navigation] = None
    nativeQuery: Optional[str] = None

    @model_validator(mode='after')
    def nav_or_sql(self):
        """Validate that partition has either navigation or nativeQuery."""
        if not self.navigation and not self.nativeQuery:
            raise ValueError("partition requires navigation or nativeQuery")
        return self


class Table(BaseModel):
    """Table definition in the model."""
    name: str
    kind: Literal["table", "measureTable"] = "table"
    column_policy: Literal["select_only", "keep_all", "hide_extras"] = "select_only"
    columns: List[Column] = Field(default_factory=list)
    measures: List[Measure] = Field(default_factory=list)
    partitions: List[Partition] = Field(default_factory=list)
    source: Optional[Dict] = None  # passthrough; use Partition.use for actual binding

    @model_validator(mode='after')
    def validate_measure_table(self):
        """Validate that measureTable has no columns or partitions."""
        if self.kind == "measureTable":
            if self.columns:
                raise ValueError("measureTable must not define columns")
            if self.partitions:
                raise ValueError("measureTable must not define partitions")
        return self


class Relationship(BaseModel):
    """Relationship definition between tables."""
    from_: str = Field(alias="from")  # "Fact[Col]"
    to: str  # "Dim[Col]"
    cardinality: Literal["oneToOne", "oneToMany", "manyToOne"]
    crossFilter: Literal["single", "both"] = "single"
    isActive: Optional[bool] = True

    @field_validator("from_", "to")
    @classmethod
    def endpoint_syntax(cls, v):
        """Validate relationship endpoint syntax."""
        if not re.match(r"^[A-Za-z_][\w ]*\[[A-Za-z_][\w ]*\]$", v):
            raise ValueError("endpoint must be Table[Column]")
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