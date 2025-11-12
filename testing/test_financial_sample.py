"""Test Financial Sample comprehensive example with all 5 table kinds."""
from pathlib import Path
import tempfile
from yaml2pbip.spec import (
    SourcesSpec,
    Source,
    ModelBody,
    Table,
    Column,
    Measure,
    Partition,
    CalculatedTableDef,
    CalculationGroupItem,
)
from yaml2pbip.emit import (
    emit_pbism,
    emit_model_tmdl,
    emit_expressions_tmdl,
    emit_table_tmdl,
)


def test_financial_sample():
    """Test Financial Sample model with all 5 table kinds and Excel source."""
    # Create Excel source
    sources = SourcesSpec(
        version=1,
        sources={
            "financial_excel": Source(
                kind="excel",
                description="Financial Sample Excel workbook from Power BI Desktop",
                file_path=r"C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_2.148.1226.0_x64__8wekyb3d8bbwe\bin\SampleData\Financial Sample.xlsx",
                workbook_name="Financial Sample",
            )
        }
    )
    
    # Create transforms
    transforms = {
        "clean_headers": """(t as table) as table =>
            let
                PromotedHeaders = Table.PromoteHeaders(t, [PromoteAllScalars=true]),
                CleanedColumns = Table.TransformColumnNames(PromotedHeaders, Text.Trim)
            in
                CleanedColumns""",
        "convert_types": """(t as table) as table =>
            let
                ConvertedTypes = Table.TransformColumnTypes(t, {
                    {"Segment", type text},
                    {"Country", type text},
                    {"Product", type text},
                    {"Discount Band", type text},
                    {"Units Sold", type number},
                    {"Manufacturing Price", type number},
                    {"Sale Price", type number},
                    {"Gross Sales", Currency.Type},
                    {"Discounts", Currency.Type},
                    {"Sales", Currency.Type},
                    {"COGS", Currency.Type},
                    {"Profit", Currency.Type},
                    {"Date", type datetime},
                    {"Month Number", Int64.Type},
                    {"Month Name", type text},
                    {"Year", Int64.Type}
                })
            in
                ConvertedTypes"""
    }
    
    # Create comprehensive model with all 5 table kinds
    model = ModelBody(
        name="FinancialSample",
        culture="en-US",
        tables=[
            # 1. Regular Table: Financials
            Table(
                name="Financials",
                kind="table",
                columns=[
                    Column(name="Segment", dataType="string"),
                    Column(name="Country", dataType="string"),
                    Column(name="Product", dataType="string"),
                    Column(name="Discount Band", dataType="string"),
                    Column(name="Units Sold", dataType="decimal", formatString="#,0.00"),
                    Column(name="Manufacturing Price", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Sale Price", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Gross Sales", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Discounts", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Sales", dataType="decimal", formatString="$#,0.00"),
                    Column(name="COGS", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Profit", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Date", dataType="dateTime"),
                    Column(name="Month Number", dataType="int64"),
                    Column(name="Month Name", dataType="string"),
                    Column(name="Year", dataType="int64"),
                ],
                measures=[
                    Measure(name="Total Units Sold", expression="SUM ( Financials[Units Sold] )", formatString="#,0.00"),
                    Measure(name="Total Sales", expression="SUM ( Financials[Sales] )", formatString="$#,0"),
                    Measure(name="Total Profit", expression="SUM ( Financials[Profit] )", formatString="$#,0"),
                    Measure(name="Total COGS", expression="SUM ( Financials[COGS] )", formatString="$#,0"),
                ],
                partitions=[
                    Partition(
                        name="FinancialData",
                        mode="import",
                        use="financial_excel",
                        custom_steps=["clean_headers", "convert_types"],
                    )
                ],
            ),
            # 2. Measure Table: Key Metrics
            Table(
                name="Key Metrics",
                kind="measureTable",
                measures=[
                    Measure(
                        name="Profit Margin %",
                        expression="DIVIDE ( [Total Profit], [Total Sales], 0 ) * 100",
                        formatString="0.00%"
                    ),
                    Measure(
                        name="Average Sale Price",
                        expression="DIVIDE ( [Total Sales], [Total Units Sold], 0 )",
                        formatString="$#,0.00"
                    ),
                    Measure(
                        name="YTD Sales",
                        expression="TOTALYTD ( [Total Sales], Financials[Date] )",
                        formatString="$#,0"
                    ),
                ],
            ),
            # 3. Calculated Table: Top Products by Profit
            Table(
                name="Top Products by Profit",
                kind="calculatedTable",
                calculatedTableDef=CalculatedTableDef(
                    expression='TOPN ( 10, SUMMARIZE ( Financials, Financials[Product], Financials[Country], "Total Profit", [Total Profit], "Total Sales", [Total Sales] ), [Total Profit], DESC )',
                    description="Top 10 products by profit across all countries"
                ),
                columns=[
                    Column(name="Product", dataType="string"),
                    Column(name="Country", dataType="string"),
                    Column(name="Total Profit", dataType="decimal", formatString="$#,0.00"),
                    Column(name="Total Sales", dataType="decimal", formatString="$#,0.00"),
                ],
                measures=[
                    Measure(
                        name="Top Products Profit",
                        expression="SUM ( 'Top Products by Profit'[Total Profit] )",
                        formatString="$#,0"
                    ),
                ],
            ),
            # 4. Calculation Group: Time Intelligence
            Table(
                name="Time Intelligence",
                kind="calculationGroup",
                calculationGroupItems=[
                    CalculationGroupItem(name="Current Period", expression="SELECTEDMEASURE ()", ordinal=0),
                    CalculationGroupItem(name="MTD", expression="CALCULATE ( SELECTEDMEASURE (), DATESMTD ( Financials[Date] ) )", ordinal=1),
                    CalculationGroupItem(name="QTD", expression="CALCULATE ( SELECTEDMEASURE (), DATESQTD ( Financials[Date] ) )", ordinal=2),
                    CalculationGroupItem(name="YTD", expression="CALCULATE ( SELECTEDMEASURE (), DATESYTD ( Financials[Date] ) )", ordinal=3),
                    CalculationGroupItem(name="PY", expression="CALCULATE ( SELECTEDMEASURE (), SAMEPERIODLASTYEAR ( Financials[Date] ) )", ordinal=4),
                    CalculationGroupItem(name="YoY %", expression='VAR CurrentValue = SELECTEDMEASURE () VAR PriorYear = CALCULATE ( SELECTEDMEASURE (), SAMEPERIODLASTYEAR ( Financials[Date] ) ) RETURN DIVIDE ( CurrentValue - PriorYear, PriorYear, BLANK () )', formatString="0.00%", ordinal=5),
                ],
            ),
            # 5. Field Parameter: Metric Selector
            Table(
                name="Metric Selector",
                kind="fieldParameter",
                columns=[
                    Column(name="Metric", dataType="string"),
                    Column(name="Value", dataType="decimal"),
                ],
                measures=[
                    Measure(
                        name="Selected Metric Value",
                        expression='SWITCH ( SELECTEDVALUE ( \'Metric Selector\'[Metric] ), "Sales", [Total Sales], "Profit", [Total Profit], "Units", [Total Units Sold], "Margin %", [Profit Margin %], BLANK () )',
                        formatString="#,0.00"
                    ),
                ],
            ),
        ],
    )
    
    # Emit and verify
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)
        sm_dir = outdir / f"{model.name}.SemanticModel"
        def_dir = sm_dir / "definition"
        tbl_dir = def_dir / "tables"
        
        print("\n" + "="*60)
        print("Financial Sample - Comprehensive Table Kinds Test")
        print("="*60)
        
        print("\nEmitting TMDL files...")
        emit_pbism(sm_dir)
        emit_model_tmdl(def_dir, model)
        emit_expressions_tmdl(def_dir, sources, transforms)
        
        for table in model.tables:
            emit_table_tmdl(tbl_dir, table, sources, transforms)
        
        # Verify all files were created
        expected_files = [
            (sm_dir / "definition.pbism", "PBISM definition"),
            (def_dir / "model.tmdl", "Model definition"),
            (def_dir / "expressions.tmdl", "Expressions (sources)"),
            (tbl_dir / "Financials.tmdl", "Regular table"),
            (tbl_dir / "Key Metrics.tmdl", "Measure table"),
            (tbl_dir / "Top Products by Profit.tmdl", "Calculated table"),
            (tbl_dir / "Time Intelligence.tmdl", "Calculation group"),
            (tbl_dir / "Metric Selector.tmdl", "Field parameter"),
        ]
        
        print("\nVerifying files...")
        all_passed = True
        for filepath, description in expected_files:
            if filepath.exists():
                print(f"  ✓ {description}: {filepath.name}")
            else:
                print(f"  ✗ {description}: NOT FOUND")
                all_passed = False
        
        assert all_passed, "Some expected files were not created"
        
        # Display table contents
        print("\n" + "-"*60)
        print("Generated Table Definitions:")
        print("-"*60)
        
        for table in model.tables:
            filepath = tbl_dir / f"{table.name}.tmdl"
            content = filepath.read_text()
            print(f"\n### {table.name} (kind={table.kind}) ###")
            # Show first 400 chars or full content if shorter
            preview = content[:400] + "..." if len(content) > 400 else content
            print(preview)
        
        # Check expressions.tmdl for Excel source
        expr_content = (def_dir / "expressions.tmdl").read_text()
        assert "Excel.Workbook" in expr_content, "Excel source not found in expressions.tmdl"
        assert "Financial Sample" in expr_content, "Workbook name not found in expressions.tmdl"
        print("\n✓ Excel source correctly generated in expressions.tmdl")
        
        print("\n" + "="*60)
        print("✓ Financial Sample test PASSED!")
        print("  All 5 table kinds generated successfully")
        print("  Excel source configuration validated")
        print("="*60 + "\n")


if __name__ == "__main__":
    test_financial_sample()
