# yaml2pbip Examples

This directory contains example YAML files demonstrating the yaml2pbip compiler functionality.

## Files Overview

### [`sources.yml`](sources.yml)
Defines data source connections for the semantic model. This example includes:
- **sf_main**: Primary Snowflake data warehouse connection
- **sf_archive**: Secondary archive connection (optional)
- Configuration options like warehouse, database, role, and query tags

### [`model.yml`](model.yml)
Defines the complete semantic model structure. This comprehensive example demonstrates:
- **Measure Table** (`_Measures`): Cross-table DAX measures
- **Dimension Tables**: Date and Product dimensions
- **Fact Table** (`FactSales`): Sales transactions with measures
- **Relationships**: Foreign key relationships between tables
- **Multiple features**: Column policies, partition types, and data types

## Running the Examples

### Using Python Module
From the project root directory:

```bash
python -m yaml2pbip compile examples/model.yml examples/sources.yml --out ./test-output
```

### Using Installed CLI
If you've installed yaml2pbip via pip:

```bash
yaml2pbip compile examples/model.yml examples/sources.yml --out ./test-output
```

### Command Options
- `examples/model.yml` - Path to model definition file
- `examples/sources.yml` - Path to sources configuration file
- `--out ./test-output` - Output directory for generated PBIP project

## Generated Output Structure

After compilation, the following structure will be created:

```
test-output/
├── SalesModel.pbip                          # Project file (open this in Power BI Desktop)
├── SalesModel.SemanticModel/
│   ├── definition.pbism                     # Semantic model metadata
│   └── definition/
│       ├── model.tmdl                       # Model-level settings
│       ├── relationships.tmdl               # Relationship definitions
│       ├── expressions.tmdl                 # Shared expressions (if any)
│       └── tables/
│           ├── _Measures.tmdl               # Measure table
│           ├── DimDate.tmdl                 # Date dimension
│           ├── DimProduct.tmdl              # Product dimension
│           └── FactSales.tmdl               # Sales fact table
└── SalesModel.Report/
    └── definition.pbir                      # Report definition (empty)
```

## Key Features Demonstrated

### 1. Measure Table (`_Measures`)
A special zero-column table containing cross-table DAX measures:
- **Total Profit**: Calculated measure across fact table
- **Profit Margin %**: Division with error handling
- **YTD Revenue**: Time intelligence function

### 2. Column Policies
Two different approaches to column management:

#### `select_only` (DimDate, DimProduct)
- Only explicitly declared columns are included
- Provides precise control over model structure
- Example: DimDate with 9 specific columns (Date, Year, Quarter, etc.)

#### `keep_all` (FactSales)
- All columns from source are included
- Only explicit columns get metadata (descriptions, format strings)
- Ideal for fact tables with many columns

### 3. Partition Types

#### Navigation-based Partitions (DimDate, DimProduct)
Direct table access using database navigation:
```yaml
source:
  use: sf_main
  navigation:
    database: SALES
    schema: DIM
    table: DATE
```

#### Native SQL Partitions (FactSales)
Custom SQL query for data transformation:
```yaml
partitions:
  - name: CurrentYear
    mode: import
    use: sf_main
    nativeQuery: |
      SELECT ...
      FROM SALES.FACT.SALES
      WHERE OrderDate >= DATEADD(year, -1, CURRENT_DATE())
```

### 4. Relationships
Foreign key relationships with cardinality and cross-filter settings:
- **FactSales → DimDate**: Many-to-one on OrderDate
- **FactSales → DimProduct**: Many-to-one on ProductKey

### 5. Measures
Two types of measures are demonstrated:

#### Cross-table Measures (in `_Measures` table)
- Reference multiple tables
- Available throughout the model
- Example: Total Profit, Profit Margin %

#### Table-specific Measures (in `FactSales`, `DimProduct`)
- Scoped to their parent table
- Useful for table-specific calculations
- Example: Total Orders, Average Order Value

### 6. Data Types and Formatting
Various Power BI data types with format strings:
- **dateTime**: Date columns
- **int64**: Integer columns (Year, Quantity)
- **decimal**: Currency and numeric values
- **string**: Text columns (MonthName, ProductName)
- **boolean**: True/false values (IsWeekend)

Format strings:
- `$#,0` - Currency with thousands separator
- `#,0.00` - Decimal with two places
- `0.00%` - Percentage format

## Opening in Power BI Desktop

1. Navigate to the output directory (`test-output/`)
2. Double-click [`SalesModel.pbip`](SalesModel.pbip) to open in Power BI Desktop
3. When prompted, provide your Snowflake credentials:
   - Server: `xy12345.eu-central-1.snowflakecomputing.com`
   - Warehouse: `COMPUTE_WH`
   - Database: `SALES`
   - Role: `ANALYST`
4. Click "Refresh" to load data from your Snowflake instance
5. Explore the model in the Model view
6. Create visualizations using the measures and dimensions

## Prerequisites

To use these examples, you need:
- **Snowflake Instance**: With the database structure matching the navigation paths
- **Power BI Desktop**: October 2023 or later (for PBIP support)
- **Python 3.8+**: To run the yaml2pbip compiler

## Database Schema Requirements

The examples assume the following Snowflake schema structure:

```sql
-- Date Dimension
SALES.DIM.DATE (
  Date TIMESTAMP,
  Year NUMBER,
  Quarter NUMBER,
  Month NUMBER,
  MonthName VARCHAR,
  DayOfWeek NUMBER,
  DayName VARCHAR,
  IsWeekend BOOLEAN
)

-- Product Dimension
SALES.DIM.PRODUCT (
  ProductKey NUMBER,
  ProductID VARCHAR,
  ProductName VARCHAR,
  Category VARCHAR,
  SubCategory VARCHAR,
  UnitPrice NUMBER(10,2)
)

-- Sales Fact
SALES.FACT.SALES (
  OrderID NUMBER,
  OrderLineID NUMBER,
  OrderDate TIMESTAMP,
  ProductKey NUMBER,
  Quantity NUMBER,
  UnitPrice NUMBER(10,2),
  Revenue NUMBER(10,2),
  Cost NUMBER(10,2),
  Discount NUMBER(10,2)
)
```

## Customization

To adapt these examples for your environment:

1. **Update [`sources.yml`](sources.yml)**:
   - Change server, warehouse, database, and role to match your Snowflake instance
   - Add additional sources as needed

2. **Update [`model.yml`](model.yml)**:
   - Modify table names and columns to match your schema
   - Adjust navigation paths (database.schema.table)
   - Customize measures and calculations for your business logic
   - Update relationships based on your data model

3. **Run the compiler** with your modified files

## Troubleshooting

### Connection Issues
- Verify Snowflake credentials are correct
- Ensure your IP is whitelisted in Snowflake
- Check that the warehouse is running

### Missing Tables
- Confirm database, schema, and table names match exactly (case-sensitive)
- Verify your role has SELECT permissions on all tables

### Compilation Errors
- Validate YAML syntax (indentation is critical)
- Check that all referenced sources exist in sources.yml
- Ensure column names don't contain special characters

## Next Steps

After successfully compiling and opening the example:
1. Review the generated TMDL files to understand the output format
2. Modify the YAML files to add your own tables and measures
3. Experiment with different column policies and partition types
4. Create custom DAX measures in the _Measures table
5. Build reports using the semantic model

## Additional Resources

- [Power BI Project (.pbip) documentation](https://learn.microsoft.com/power-bi/developer/projects/projects-overview)
- [TMDL documentation](https://learn.microsoft.com/power-bi/developer/projects/projects-dataset)
- [DAX function reference](https://learn.microsoft.com/dax/)
- [Snowflake connector documentation](https://learn.microsoft.com/power-bi/connect-data/desktop-connect-snowflake)