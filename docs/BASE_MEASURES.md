# Base Measures - Bulk Measure Generation

## Overview

The `base_measures` feature allows you to automatically generate multiple DAX measures using a concise YAML syntax. Instead of writing individual measure definitions, you can specify aggregation functions and column references to generate measures in bulk.

## Syntax

```yaml
tables:
  - name: TableName
    base_measures:
      aggregation_function: column1, column2, table.column3
      another_function: column4
```

## Generated Measure Names

Measures are automatically named using the pattern: `{aggregation_function}_{column_name}`

Examples:
- `sum: sales_amount` → `sum_sales_amount`
- `avg: customer.rating` → `avg_rating`
- `distinctcount: order_id` → `distinctcount_order_id`

## Supported Aggregation Functions

| Function | DAX Generated | Example |
|----------|---------------|---------|
| `sum` | `SUM(column)` | `sum_sales_amount = SUM([sales_amount])` |
| `avg` / `average` | `AVERAGE(column)` | `avg_rating = AVERAGE([rating])` |
| `min` | `MIN(column)` | `min_price = MIN([price])` |
| `max` | `MAX(column)` | `max_price = MAX([price])` |
| `count` | `COUNT(column)` | `count_items = COUNT([item_id])` |
| `distinctcount` | `DISTINCTCOUNT(column)` | `distinctcount_customers = DISTINCTCOUNT([customer_id])` |
| `countrows` | `COUNTROWS(column)` | `countrows_table = COUNTROWS([table])` |

## Column Reference Formats

### Local Columns (Same Table)
```yaml
base_measures:
  sum: sales_amount, profit
```
Generates:
```dax
sum_sales_amount = SUM([sales_amount])
sum_profit = SUM([profit])
```

### Cross-Table References
```yaml
base_measures:
  sum: fact_sales.sales_amount, fact_sales.profit
  avg: dim_customer.rating
```
Generates:
```dax
sum_sales_amount = SUM('fact_sales'[sales_amount])
sum_profit = SUM('fact_sales'[profit])
avg_rating = AVERAGE('dim_customer'[rating])
```

## Usage Examples

### Example 1: Fact Table with Multiple Aggregations

```yaml
tables:
  - name: Sales
    columns:
      - name: sales_amount
        dataType: decimal
      - name: quantity
        dataType: int64
      - name: customer_id
        dataType: string
    
    base_measures:
      sum: sales_amount, quantity
      avg: sales_amount
      min: sales_amount
      max: sales_amount
      distinctcount: customer_id
    
    partitions:
      - name: SALES
        use: my_source
        navigation: DB.SCHEMA.SALES
```

**Generated Measures:**
- `sum_sales_amount = SUM([sales_amount])`
- `sum_quantity = SUM([quantity])`
- `avg_sales_amount = AVERAGE([sales_amount])`
- `min_sales_amount = MIN([sales_amount])`
- `max_sales_amount = MAX([sales_amount])`
- `distinctcount_customer_id = DISTINCTCOUNT([customer_id])`

### Example 2: Measure Table with Cross-Table References

```yaml
tables:
  - name: Key Metrics
    kind: measureTable
    
    base_measures:
      sum: Sales.revenue, Sales.profit
      avg: Customer.satisfaction_score
      distinctcount: Orders.order_id, Sales.customer_id
    
    measures:
      - name: Profit Margin
        expression: |
          DIVIDE(
              SUM(Sales[profit]),
              SUM(Sales[revenue]),
              0
          )
```

**Generated Measures:**
- `sum_revenue = SUM('Sales'[revenue])`
- `sum_profit = SUM('Sales'[profit])`
- `avg_satisfaction_score = AVERAGE('Customer'[satisfaction_score])`
- `distinctcount_order_id = DISTINCTCOUNT('Orders'[order_id])`
- `distinctcount_customer_id = DISTINCTCOUNT('Sales'[customer_id])`

Plus the custom `Profit Margin` measure.

### Example 3: Combining with Explicit Measures

```yaml
tables:
  - name: Products
    
    # Generated measures
    base_measures:
      avg: unit_price, cost
      min: unit_price
      max: unit_price
    
    # Custom measures
    measures:
      - name: Markup Percentage
        expression: |
          DIVIDE(
              [avg_unit_price] - [avg_cost],
              [avg_cost],
              0
          )
        formatString: "0.0%"
      
      - name: Price Range
        expression: "[max_unit_price] - [min_unit_price]"
        formatString: "$#,##0.00"
    
    partitions:
      - name: PRODUCTS
        use: source
        navigation: DB.SCHEMA.PRODUCTS
```

This generates base measures that can be referenced in custom measures.

## Benefits

### 1. **Reduced Boilerplate**
Instead of:
```yaml
measures:
  - name: sum_sales_amount
    expression: SUM([sales_amount])
  - name: sum_profit
    expression: SUM([profit])
  - name: avg_sales_amount
    expression: AVERAGE([sales_amount])
  - name: avg_profit
    expression: AVERAGE([profit])
```

Write:
```yaml
base_measures:
  sum: sales_amount, profit
  avg: sales_amount, profit
```

### 2. **Consistency**
All generated measures follow the same naming convention and pattern.

### 3. **Maintainability**
Easy to add or remove aggregations for multiple columns at once.

### 4. **Composability**
Generated measures can be referenced in custom measures:
```yaml
base_measures:
  sum: revenue, cost

measures:
  - name: Profit
    expression: "[sum_revenue] - [sum_cost]"
```

## Best Practices

### 1. Use for Standard Aggregations
`base_measures` works best for simple, standard aggregations:
```yaml
base_measures:
  sum: amount, quantity
  avg: price
  distinctcount: customer_id
```

### 2. Use Custom Measures for Complex Logic
For measures with `CALCULATE`, `FILTER`, or other complex DAX:
```yaml
base_measures:
  sum: sales_amount

measures:
  - name: Sales Last Year
    expression: |
      CALCULATE(
          [sum_sales_amount],
          DATEADD('Date'[Date], -1, YEAR)
      )
```

### 3. Organize by Table Type

**Fact Tables:** Typically sum/avg numeric columns
```yaml
base_measures:
  sum: revenue, cost, quantity
  avg: unit_price
```

**Dimension Tables:** Typically count distinct keys
```yaml
base_measures:
  distinctcount: customer_id, product_id
```

**Measure Tables:** Mix of cross-table references
```yaml
base_measures:
  sum: FactSales.amount
  distinctcount: DimCustomer.customer_id
```

### 4. Combine with Formatting

Add formatting to generated measures by defining them explicitly:
```yaml
base_measures:
  sum: sales_amount

measures:
  - name: sum_sales_amount  # Override generated measure
    expression: SUM([sales_amount])
    formatString: "$#,##0.00"
    displayFolder: Sales Metrics
```

## Processing Order

1. `base_measures` are processed first and converted to `Measure` objects
2. Generated measures are **prepended** to the measures list
3. Explicit `measures` can override generated ones (same name = explicit wins)
4. All measures are validated by Pydantic models

## Limitations

1. **Simple Aggregations Only**: Cannot generate measures with `CALCULATE`, `FILTER`, time intelligence, etc.
2. **No Custom Formatting**: Generated measures use default formatting (can be overridden)
3. **No Display Folders**: Generated measures have no display folders (can be overridden)
4. **Fixed Naming Pattern**: Always `{function}_{column}` (cannot customize)

For complex scenarios, use explicit `measures` definitions.

## Migration from Explicit Measures

**Before:**
```yaml
measures:
  - name: sum_revenue
    expression: SUM([revenue])
  - name: sum_cost
    expression: SUM([cost])
  - name: sum_profit
    expression: SUM([profit])
  - name: avg_revenue
    expression: AVERAGE([revenue])
```

**After:**
```yaml
base_measures:
  sum: revenue, cost, profit
  avg: revenue
```

## See Also

- [Measure Tables](MEASURE_TABLES.md)
- [DAX Expressions](DAX_EXPRESSIONS.md)
- [Table Kinds](TABLE_KINDS.md)