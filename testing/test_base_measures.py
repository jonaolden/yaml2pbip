"""Test bulk measure generation from base_measures."""
import pytest
from yaml2pbip.spec import Table, Measure


def test_base_measures_simple():
    """Test basic base_measures expansion."""
    table_data = {
        "name": "Sales",
        "base_measures": {
            "sum": "sales_amount, sales_profit",
            "avg": "rating"
        },
        "partitions": [{"name": "P1", "use": "source1"}]
    }
    
    table = Table(**table_data)
    
    # Should generate 3 measures
    assert len(table.measures) == 3
    
    # Check measure names
    measure_names = {m.name for m in table.measures}
    assert measure_names == {"sum_sales_amount", "sum_sales_profit", "avg_rating"}
    
    # Check DAX expressions
    measures_dict = {m.name: m.expression for m in table.measures}
    assert measures_dict["sum_sales_amount"] == "SUM([sales_amount])"
    assert measures_dict["sum_sales_profit"] == "SUM([sales_profit])"
    assert measures_dict["avg_rating"] == "AVERAGE([rating])"


def test_base_measures_with_table_reference():
    """Test base_measures with explicit table references."""
    table_data = {
        "name": "Metrics",
        "kind": "measureTable",
        "base_measures": {
            "sum": "fact_sales.sales_amount, fact_sales.sales_profit",
            "avg": "customer.rating"
        }
    }
    
    table = Table(**table_data)
    
    # Should generate 3 measures
    assert len(table.measures) == 3
    
    # Check DAX expressions with table references
    measures_dict = {m.name: m.expression for m in table.measures}
    assert measures_dict["sum_sales_amount"] == "SUM('fact_sales'[sales_amount])"
    assert measures_dict["sum_sales_profit"] == "SUM('fact_sales'[sales_profit])"
    assert measures_dict["avg_rating"] == "AVERAGE('customer'[rating])"


def test_base_measures_multiple_functions():
    """Test multiple aggregation functions."""
    table_data = {
        "name": "Analytics",
        "kind": "measureTable",
        "base_measures": {
            "sum": "revenue",
            "avg": "revenue",
            "min": "revenue",
            "max": "revenue",
            "count": "customer_id"
        }
    }
    
    table = Table(**table_data)
    
    # Should generate 5 measures
    assert len(table.measures) == 5
    
    measures_dict = {m.name: m.expression for m in table.measures}
    assert measures_dict["sum_revenue"] == "SUM([revenue])"
    assert measures_dict["avg_revenue"] == "AVERAGE([revenue])"
    assert measures_dict["min_revenue"] == "MIN([revenue])"
    assert measures_dict["max_revenue"] == "MAX([revenue])"
    assert measures_dict["count_customer_id"] == "COUNT([customer_id])"


def test_base_measures_with_explicit_measures():
    """Test that explicit measures are preserved alongside generated ones."""
    table_data = {
        "name": "Sales",
        "base_measures": {
            "sum": "sales_amount"
        },
        "measures": [
            {"name": "Custom Measure", "expression": "CALCULATE(SUM([amount]))"}
        ],
        "partitions": [{"name": "P1", "use": "source1"}]
    }
    
    table = Table(**table_data)
    
    # Should have both generated and explicit measures
    assert len(table.measures) == 2
    
    measure_names = {m.name for m in table.measures}
    assert "sum_sales_amount" in measure_names
    assert "Custom Measure" in measure_names


def test_no_base_measures():
    """Test that tables without base_measures work normally."""
    table_data = {
        "name": "Sales",
        "measures": [
            {"name": "Total Sales", "expression": "SUM([amount])"}
        ],
        "partitions": [{"name": "P1", "use": "source1"}]
    }
    
    table = Table(**table_data)
    
    assert len(table.measures) == 1
    assert table.measures[0].name == "Total Sales"


def test_empty_base_measures():
    """Test that empty base_measures dict doesn't cause issues."""
    table_data = {
        "name": "Sales",
        "base_measures": {},
        "partitions": [{"name": "P1", "use": "source1"}]
    }
    
    table = Table(**table_data)
    
    assert len(table.measures) == 0


def test_base_measures_distinctcount():
    """Test distinctcount aggregation function."""
    table_data = {
        "name": "Metrics",
        "kind": "measureTable",
        "base_measures": {
            "distinctcount": "customer.customer_id"
        }
    }
    
    table = Table(**table_data)
    
    assert len(table.measures) == 1
    assert table.measures[0].name == "distinctcount_customer_id"
    assert table.measures[0].expression == "DISTINCTCOUNT('customer'[customer_id])"


def test_base_measures_list_syntax():
    """Test base_measures using YAML list syntax (- sum:)."""
    table_data = {
        "name": "Metrics",
        "kind": "measureTable",
        "base_measures": [
            {"sum": "fact_sales.sales_amount, fact_sales.sales_profit"},
            {"avg": "customer.rating"}
        ]
    }
    
    table = Table(**table_data)
    
    # Should generate 3 measures
    assert len(table.measures) == 3
    
    # Check measure names
    measure_names = {m.name for m in table.measures}
    assert measure_names == {"sum_sales_amount", "sum_sales_profit", "avg_rating"}
    
    # Check DAX expressions
    measures_dict = {m.name: m.expression for m in table.measures}
    assert measures_dict["sum_sales_amount"] == "SUM('fact_sales'[sales_amount])"
    assert measures_dict["sum_sales_profit"] == "SUM('fact_sales'[sales_profit])"
    assert measures_dict["avg_rating"] == "AVERAGE('customer'[rating])"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])