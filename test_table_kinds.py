"""Test table template refactoring with new table kinds."""
from pathlib import Path
import tempfile
from yaml2pbip.spec import (
    SourcesSpec,
    Source,
    SourceOptions,
    ModelBody,
    Table,
    Column,
    Measure,
    Partition,
    Navigation,
)
from yaml2pbip.emit import (
    emit_pbism,
    emit_model_tmdl,
    emit_expressions_tmdl,
    emit_table_tmdl,
)


def test_all_table_kinds():
    """Test rendering all table kinds with per-kind templates."""
    # Create sources
    sources = SourcesSpec(
        version=1,
        sources={
            "sf_main": Source(
                kind="snowflake",
                server="xy12345.eu-central-1.snowflakecomputing.com",
                warehouse="COMPUTE_WH",
                database="SALES",
                options=SourceOptions(implementation="2.0")
            )
        }
    )
    
    # Create model with all table kinds
    model = ModelBody(
        name="AllTableKindsTest",
        culture="en-US",
        tables=[
            # Regular table
            Table(
                name="DimProduct",
                kind="table",
                columns=[
                    Column(name="ProductID", dataType="int64"),
                    Column(name="ProductName", dataType="string"),
                ],
                partitions=[
                    Partition(
                        name="Full",
                        mode="import",
                        use="sf_main",
                        navigation=Navigation(database="SALES", schema="DIM", table="PRODUCT"),
                    )
                ],
            ),
            # Measure table
            Table(
                name="Measures",
                kind="measureTable",
                measures=[
                    Measure(
                        name="Total Sales",
                        expression="SUM(FactSales[Amount])",
                        formatString="#,0.00"
                    ),
                ],
            ),
            # Calculated table
            Table(
                name="CalcTable",
                kind="calculatedTable",
                partitions=[
                    Partition(
                        name="Calc",
                        mode="import",
                        use="sf_main",
                        navigation=Navigation(database="SALES", schema="DIM", table="CALC"),
                    )
                ],
            ),
            # Field parameter
            Table(
                name="FieldParam",
                kind="fieldParameter",
                columns=[
                    Column(name="FieldValue", dataType="string"),
                ],
            ),
            # Calculation group
            Table(
                name="CalcGroup",
                kind="calculationGroup",
                measures=[
                    Measure(
                        name="GroupMeasure",
                        expression="1"
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
        
        print("Emitting TMDL files with all table kinds...")
        emit_pbism(sm_dir)
        emit_model_tmdl(def_dir, model)
        emit_expressions_tmdl(def_dir, sources)
        
        for table in model.tables:
            emit_table_tmdl(tbl_dir, table, sources)
        
        # Verify all files were created
        assert (tbl_dir / "DimProduct.tmdl").exists(), "table (kind='table') not created"
        assert (tbl_dir / "Measures.tmdl").exists(), "measureTable not created"
        assert (tbl_dir / "CalcTable.tmdl").exists(), "calculatedTable not created"
        assert (tbl_dir / "FieldParam.tmdl").exists(), "fieldParameter not created"
        assert (tbl_dir / "CalcGroup.tmdl").exists(), "calculationGroup not created"
        
        print("✓ All table files created successfully!\n")
        
        # Display contents
        for kind, filename in [
            ("table", "DimProduct.tmdl"),
            ("measureTable", "Measures.tmdl"),
            ("calculatedTable", "CalcTable.tmdl"),
            ("fieldParameter", "FieldParam.tmdl"),
            ("calculationGroup", "CalcGroup.tmdl"),
        ]:
            filepath = tbl_dir / filename
            content = filepath.read_text()
            print(f"--- {kind} ({filename}) ---")
            print(content[:300] if len(content) > 300 else content)
            print()
        
        print("✓ All table kinds rendered successfully!")


if __name__ == "__main__":
    test_all_table_kinds()
