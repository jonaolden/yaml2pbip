"""Tests for DAX template-based calculated tables."""
import pytest
from pathlib import Path
from yaml2pbip.spec import ModelSpec, CalculatedTableDef
from yaml2pbip.dax import load_dax_templates, canonical_name
from yaml2pbip.compile import compile_project
import tempfile
import shutil


def test_calculated_table_def_validation():
    """Test CalculatedTableDef validation for expression vs template."""
    # Valid: expression only
    calc_def = CalculatedTableDef(expression="DISTINCT(Table[Column])")
    assert calc_def.expression == "DISTINCT(Table[Column])"
    assert calc_def.template is None
    
    # Valid: template only
    calc_def = CalculatedTableDef(template="metadata_table")
    assert calc_def.template == "metadata_table"
    assert calc_def.expression is None
    
    # Invalid: both expression and template
    with pytest.raises(ValueError, match="cannot have both"):
        CalculatedTableDef(expression="DISTINCT(Table[Column])", template="metadata_table")
    
    # Invalid: neither expression nor template
    with pytest.raises(ValueError, match="must have either"):
        CalculatedTableDef()


def test_canonical_name():
    """Test DAX template name extraction."""
    assert canonical_name(Path("metadata_table.dax")) == "metadata_table"
    assert canonical_name(Path("path/to/my_template.dax")) == "my_template"
    assert canonical_name(Path("some-template.dax")) == "some_template"


def test_load_dax_templates(tmp_path):
    """Test loading DAX templates from directories."""
    # Create test DAX files
    dax_dir = tmp_path / "dax"
    dax_dir.mkdir()
    
    (dax_dir / "metadata_table.dax").write_text("INFO.VIEWTABLES()")
    (dax_dir / "distinct_values.dax").write_text("DISTINCT(Table[Column])")
    
    # Load templates
    templates = load_dax_templates([dax_dir])
    
    assert "metadata_table" in templates
    assert templates["metadata_table"] == "INFO.VIEWTABLES()"
    assert "distinct_values" in templates
    assert templates["distinct_values"] == "DISTINCT(Table[Column])"


def test_dax_template_precedence(tmp_path):
    """Test that later directories override earlier ones."""
    # Create two directories with overlapping template names
    dir1 = tmp_path / "global_dax"
    dir2 = tmp_path / "local_dax"
    dir1.mkdir()
    dir2.mkdir()
    
    (dir1 / "template.dax").write_text("GLOBAL VERSION")
    (dir2 / "template.dax").write_text("LOCAL VERSION")
    
    # Load with dir1 first, dir2 second (dir2 should win)
    templates = load_dax_templates([dir1, dir2])
    assert templates["template"] == "LOCAL VERSION"


def test_compile_with_dax_template():
    """Test full compilation with DAX template reference."""
    # Create temporary directories
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create test files
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        
        # Create DAX template
        dax_dir = model_dir / "dax"
        dax_dir.mkdir()
        (dax_dir / "test_template.dax").write_text("INFO.VIEWTABLES()")
        
        # Create sources.yml
        sources_content = """
version: 1
sources:
  test_source:
    kind: excel
    file_path: test.xlsx
    workbook_name: TestWorkbook
"""
        sources_file = model_dir / "sources.yml"
        sources_file.write_text(sources_content)
        
        # Create model.yml with template reference
        model_content = """
version: 1
model:
  name: TestModel
  culture: en-US
  tables:
    - name: TestTable
      kind: calculatedTable
      calculatedTableDef:
        template: test_template
        description: Test calculated table using template
      columns:
        - name: TableName
          dataType: string
"""
        model_file = model_dir / "model.yml"
        model_file.write_text(model_content)
        
        # Compile project
        output_dir = tmp_path / "output"
        compile_project(
            model_yaml=model_file,
            sources_yaml=sources_file,
            outdir=output_dir,
            stub_report=False
        )
        
        # Verify output
        table_file = output_dir / "TestModel.SemanticModel" / "definition" / "tables" / "TestTable.tmdl"
        assert table_file.exists()
        
        content = table_file.read_text()
        assert "INFO.VIEWTABLES()" in content
        assert "TestTable-Partition" in content


def test_missing_template_error():
    """Test that missing template raises clear error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        
        sources_content = """
version: 1
sources:
  test_source:
    kind: excel
    file_path: test.xlsx
    workbook_name: TestWorkbook
"""
        sources_file = model_dir / "sources.yml"
        sources_file.write_text(sources_content)
        
        model_content = """
version: 1
model:
  name: TestModel
  culture: en-US
  tables:
    - name: TestTable
      kind: calculatedTable
      calculatedTableDef:
        template: nonexistent_template
      columns:
        - name: Col1
          dataType: string
"""
        model_file = model_dir / "model.yml"
        model_file.write_text(model_content)
        
        output_dir = tmp_path / "output"
        
        with pytest.raises(ValueError, match="DAX template 'nonexistent_template' not found"):
            compile_project(
                model_yaml=model_file,
                sources_yaml=sources_file,
                outdir=output_dir,
                stub_report=False
            )