# Financial Sample - Comprehensive yaml2pbip Example

This example demonstrates all **5 table kinds** supported by yaml2pbip using the Power BI Financial Sample dataset.

## Overview

The Financial Sample model showcases:
- **Regular Table** (`table`) - Standard fact table with financial data
- **Measure Table** (`measureTable`) - Cross-table business metrics
- **Calculated Table** (`calculatedTable`) - Dynamic top products ranking
- **Calculation Group** (`calculationGroup`) - Time intelligence calculations
- **Field Parameter** (`fieldParameter`) - Dynamic metric selector

## Files

- `sources.yml` - Excel source connection configuration
- `model.yml` - Complete semantic model with all 5 table kinds
- `transforms/clean_headers.m` - Excel header cleaning transform
- `transforms/convert_types.m` - Data type conversion transform

## Model Structure

### 1. Financials (Regular Table)
Fact table containing all financial transactions with 16 columns:
- **Dimensions**: Segment, Country, Product, Discount Band, Date, Month, Year
- **Metrics**: Units Sold, Manufacturing Price, Sale Price, Gross Sales, Discounts, Sales, COGS, Profit

**Measures**:
- Total Units Sold
- Total Sales
- Total Profit
- Total COGS

### 2. Key Metrics (Measure Table)
Cross-table business KPIs:
- Profit Margin %
- Average Sale Price
- Discount %
- YTD Sales
- YTD Profit

### 3. Top Products by Profit (Calculated Table)
Dynamic DAX table showing top 10 products by profit across all countries.

**Columns**:
- Product
- Country
- Total Profit
- Total Sales

### 4. Time Intelligence (Calculation Group)
Time-based calculation modifiers:
- Current Period
- MTD (Month-to-Date)
- QTD (Quarter-to-Date)
- YTD (Year-to-Date)
- PY (Prior Year)
- YoY % (Year-over-Year percentage change)

### 5. Metric Selector (Field Parameter)
Dynamic measure selector for switching between:
- Sales
- Profit
- Units
- Margin %

## Data Source

This example references the Financial Sample Excel workbook included with Power BI Desktop:
```
C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_2.148.1226.0_x64__8wekyb3d8bbwe\bin\SampleData\Financial Sample.xlsx
```

You can also download it from: [Microsoft Power BI Financial Sample](https://learn.microsoft.com/en-us/power-bi/create-reports/sample-financial-download)

## Usage

To compile this model into a .pbip file:

```bash
python -m yaml2pbip examples/financial_sample
```

This will generate:
```
examples/financial_sample/
  FinancialSample.pbip
  FinancialSample.SemanticModel/
    definition.pbism
    definition/
      model.tmdl
      expressions.tmdl
      tables/
        Financials.tmdl
        Key Metrics.tmdl
        Top Products by Profit.tmdl
        Time Intelligence.tmdl
        Metric Selector.tmdl
```

## Key Features Demonstrated

### Excel Source Support
Shows how to connect to Excel workbooks using the `excel` source kind.

### All Table Kinds
Complete reference implementation of every table type in Power BI's TMDL format:
- ✅ Regular import tables with partitions
- ✅ Measure-only tables for organizing KPIs
- ✅ Calculated tables with DAX expressions
- ✅ Calculation groups for time intelligence
- ✅ Field parameters for dynamic analysis

### Transform Pipeline
Demonstrates M-code transforms for:
- Promoting and cleaning Excel headers
- Converting text columns to proper data types (Currency, Int64, DateTime)

### DAX Patterns
- Time intelligence (YTD, MTD, QTD, YoY)
- Division with zero handling (DIVIDE)
- Table filtering (TOPN, SUMMARIZE)
- Context modification (CALCULATE)

## Notes

- This is a single-table model (no relationships) as the Financial Sample is denormalized
- All date calculations reference the `Financials[Date]` column directly
- The model uses `en-US` culture for formatting
- Measure formats are explicitly defined with formatString property

## Testing

This example serves as a comprehensive test case for yaml2pbip, ensuring all table kinds generate valid TMDL output.
