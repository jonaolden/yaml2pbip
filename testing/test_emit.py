"""Simple test to verify TMDL emission functionality."""
from pathlib import Path
import tempfile
import shutil

from yaml2pbip.spec import (
    SourcesSpec,
    Source,
    SourceOptions,
    ModelSpec,
    ModelBody,
    Table,
    Column,
    Measure,
    Partition,
    Navigation,
    Relationship,
)
from yaml2pbip.emit import (
    emit_pbism,
    emit_model_tmdl,
    emit_expressions_tmdl,
    emit_table_tmdl,
    emit_relationships_tmdl,
    emit_report_by_path,
)


def test_emission():
    """Test TMDL emission with sample data."""
    # Create sources
    sources = SourcesSpec(
        version=1,
        sources={
            "sf_main": Source(
                kind="snowflake",
                server="xy12345.eu-central-1.snowflakecomputing.com",
                warehouse="COMPUTE_WH",
                database="SALES",
                role="ANALYST",
                options=SourceOptions(implementation="2.0", queryTag="yaml2pbip")
            )
        }
    )
    
    # Create sample transforms
    transforms = {
        "proper_naming": "(t as table) as table => Table.RenameColumns(t, {{\"OLD_NAME\", \"NewName\"}})",
        "cast_numbers": "(t as table) as table => Table.TransformColumnTypes(t, {{\"Amount\", Int64.Type}})"
    }
    
    # Create model
    model = ModelBody(
        name="TestModel",
        culture="en-US",
        tables=[
            Table(
                name="_Measures",
                kind="measureTable",
                measures=[
                    Measure(
                        name="Total Profit",
                        expression='SUMX ( Sales, Sales[Revenue] - Sales[Cost] )',
                        formatString="#,0.0"
                    )
                ]
            ),
            Table(
                name="DimDate",
                kind="table",
                column_policy="select_only",
                columns=[
                    Column(name="Date", dataType="date"),
                    Column(name="Year", dataType="int64"),
                ],
                partitions=[
                    Partition(
                        name="Full",
                        mode="import",
                        use="sf_main",
                        navigation=Navigation(database="SALES", schema="DIM", table="DATE"),
                        custom_steps=["proper_naming", "cast_numbers"]
                    )
                ],
                source={"use": "sf_main"}
            ),
            Table(
                name="FactSales",
                kind="table",
                column_policy="keep_all",
                columns=[
                    Column(name="OrderID", dataType="int64"),
                    Column(name="Amount", dataType="decimal", formatString="#,0.00"),
                    Column(name="OrderDate", dataType="date"),
                ],
                measures=[
                    Measure(name="Orders", expression='COUNT ( FactSales[OrderID] )')
                ],
                partitions=[
                    Partition(
                        name="NativeSQL",
                        mode="import",
                        use="sf_main",
                        nativeQuery="select OrderID, Amount, OrderDate\nfrom SALES.DBO.FactSales"
                    )
                ]
            )
        ],
        relationships=[
            Relationship(
                **{
                    "from": "FactSales",
                    "to": "DimDate",
                    "using": "OrderDate, Date",
                    "cardinality": "manyToOne",
                    "crossFilter": "single"
                }
            )
        ]
    )
    
    # Create temporary output directory
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)
        
        # Set up directories
        sm_dir = outdir / f"{model.name}.SemanticModel"
        def_dir = sm_dir / "definition"
        tbl_dir = def_dir / "tables"
        rpt_dir = outdir / f"{model.name}.Report"
        
        # Emit all files
        print("Emitting TMDL files...")
        emit_pbism(sm_dir)
        emit_model_tmdl(def_dir, model)
        emit_expressions_tmdl(def_dir, sources, transforms)
        
        # Pass transforms to table emission
        for table in model.tables:
            emit_table_tmdl(tbl_dir, table, sources, transforms=transforms)

        # Additional unit test: ensure partition transform injection works with sequential steps
        print("\nTesting partition transform sequential step injection...")
        from yaml2pbip.emit import generate_partition_mcode
        # Create a navigation partition that references transforms
        t_partition = Partition(
            name="WithTransforms",
            mode="import",
            use="sf_main",
            navigation=Navigation(database="SALES", schema="DIM", table="DATE"),
            custom_steps=["proper_naming", "cast_numbers"]
        )
        t_table = Table(
            name="DimDate",
            column_policy="select_only",
            columns=[Column(name="Date", dataType="date")],
            partitions=[t_partition],
            source={"use": "sf_main"}
        )
        mcode = generate_partition_mcode(t_partition, t_table, sources, transforms=transforms)
        # Check that transforms are embedded as complete let...in blocks
        assert "__proper_naming_1 =" in mcode, "First transform should be assigned to __proper_naming_1"
        assert "__cast_numbers_2 =" in mcode, "Second transform should be assigned to __cast_numbers_2"
        assert "Table.RenameColumns(t," in mcode, "Transform body should reference parameter 't' (not replaced in original transform)"
        assert "in\n  __cast_numbers_2" in mcode, "Final step __cast_numbers_2 should be returned in 'in' clause"
        print("✓ Sequential transform steps with embedded let...in blocks appear in generated M code")
        
        emit_relationships_tmdl(def_dir, model)
        emit_report_by_path(rpt_dir, f"../{model.name}.SemanticModel")
        
        # Create .pbip file
        (outdir / f"{model.name}.pbip").write_text(
            '{"version":"1.0","artifacts":["' + f'{model.name}.Report' + '"]}'
        )
        
        # Verify files exist
        assert (sm_dir / "definition.pbism").exists(), "definition.pbism not created"
        assert (def_dir / "model.tmdl").exists(), "model.tmdl not created"
        assert (def_dir / "expressions.tmdl").exists(), "expressions.tmdl not created"
        assert (def_dir / "relationships.tmdl").exists(), "relationships.tmdl not created"
        assert (tbl_dir / "_Measures.tmdl").exists(), "_Measures.tmdl not created"
        assert (tbl_dir / "DimDate.tmdl").exists(), "DimDate.tmdl not created"
        assert (tbl_dir / "FactSales.tmdl").exists(), "FactSales.tmdl not created"
        assert (rpt_dir / "definition.pbir").exists(), "definition.pbir not created"
        assert (outdir / f"{model.name}.pbip").exists(), ".pbip file not created"
        
        print("\n✓ All files created successfully!")
        
        # Print sample outputs
        print("\n--- model.tmdl ---")
        print((def_dir / "model.tmdl").read_text())
        
        print("\n--- expressions.tmdl (first 50 lines) ---")
        expr_content = (def_dir / "expressions.tmdl").read_text()
        print("\n".join(expr_content.split("\n")[:50]))
        
        print("\n--- _Measures.tmdl ---")
        print((tbl_dir / "_Measures.tmdl").read_text())
        
        print("\n--- DimDate.tmdl (first 40 lines) ---")
        content = (tbl_dir / "DimDate.tmdl").read_text()
        print("\n".join(content.split("\n")[:40]))
        
        print("\n--- relationships.tmdl ---")
        print((def_dir / "relationships.tmdl").read_text())
        
        print("\n✓ Test completed successfully!")


if __name__ == "__main__":
    test_emission()