"""Main compiler pipeline for yaml2pbip."""
from pathlib import Path
import yaml
import json
import logging
import re
from typing import Optional

from .spec import SourcesSpec, ModelSpec, Table, Column
from .emit import (
    emit_pbism,
    emit_model_tmdl,
    emit_database_tmdl,
    emit_culture_tmdl,
    emit_expressions_tmdl,
    emit_table_tmdl,
    emit_relationships_tmdl,
    emit_report_by_path
)

logger = logging.getLogger(__name__)


def infer_calculated_table_column_properties(table: Table) -> None:
    """Infer sourceColumn and other properties for calculated table columns from DAX expression.
    
    For calculated tables with SUMMARIZE expressions, this function parses the DAX to identify:
    - Direct column references (e.g., Financials[Product]) -> sets sourceColumn to Financials[Product]
    - Calculated columns (e.g., "Total Profit", [Total Profit]) -> sets sourceColumn to Financials[Total Profit]
    
    Also sets isNameInferred=True for direct references and appropriate summarizeBy values.
    
    Args:
        table: Table object to enrich with inferred properties (mutates in place)
    """
    if table.kind != "calculatedTable" or not table.calculatedTableDef:
        return
    
    dax_expr = table.calculatedTableDef.expression
    
    # Build a mapping of column names to their source references
    # Key: column name, Value: source reference
    source_mapping = {}
    
    # Extract the base table from SUMMARIZE function (first argument)
    # Pattern: SUMMARIZE ( TableName, ...
    summarize_pattern = r'SUMMARIZE\s*\(\s*([A-Za-z_][\w ]*)\s*,'
    summarize_match = re.search(summarize_pattern, dax_expr, re.IGNORECASE)
    base_table = summarize_match.group(1).strip() if summarize_match else None
    
    # Pattern 1: Direct column references - TableName[ColumnName]
    # Matches: Financials[Product], Financials[Country], etc.
    # Pattern allows spaces in both table and column names
    column_ref_pattern = r"([A-Za-z_][\w ]*)\[([^\]]+)\]"
    column_refs = re.findall(column_ref_pattern, dax_expr)
    
    for table_name, col_name in column_refs:
        # Check if this is NOT part of a calculated column definition
        # Pattern: "NewColumnName", [Measure or Column]
        # If we find a quoted string before this reference, it's a calculated column
        calc_pattern = rf'"{col_name}"\s*,\s*\[{re.escape(col_name)}\]'
        
        if calc_pattern not in dax_expr:
            # This is a direct column reference from source table
            source_mapping[col_name] = f"{table_name}[{col_name}]"
    
    # Pattern 2: Calculated columns with measure references
    # Matches: "Total Profit", [Total Profit]
    # The column name in quotes becomes the new column, and [Measure] is the source
    calc_col_pattern = r'"([^"]+)"\s*,\s*\[([^\]]+)\]'
    calc_cols = re.findall(calc_col_pattern, dax_expr)
    
    for new_col_name, measure_name in calc_cols:
        # For calculated columns, use the base table context for measure references
        if base_table:
            source_mapping[new_col_name] = f"{base_table}[{measure_name}]"
        else:
            # Fallback if we couldn't extract base table
            source_mapping[new_col_name] = f"[{measure_name}]"
    
    # Enrich each column with inferred properties
    for column in table.columns:
        col_name = column.name
        
        if col_name in source_mapping:
            source_ref = source_mapping[col_name]
            column.sourceColumn = source_ref
            
            # Only set isNameInferred for direct table column references (not measures)
            # Measure references will be in format TableName[MeasureName] but not have isNameInferred
            # We distinguish by checking if this came from a calculated column pattern
            is_direct_column = col_name in [cn for _, cn in column_refs 
                                           if f'"{col_name}"' not in dax_expr]
            if is_direct_column:
                column.isNameInferred = True
            
            # Numeric types get summarizeBy: sum, others get none
            if column.dataType in ("int64", "decimal", "double", "currency"):
                column.summarizeBy = "sum"
            else:
                column.summarizeBy = "none"
        else:
            # Fallback: set summarizeBy even if no sourceColumn found
            if column.dataType in ("int64", "decimal", "double", "currency"):
                column.summarizeBy = "sum"
            else:
                column.summarizeBy = "none"


def set_regular_table_column_properties(table: Table) -> None:
    """Set sourceColumn and summarizeBy properties for regular table columns.
    
    For regular tables (kind='table'), this sets:
    - sourceColumn: column name itself (e.g., "Country" not "TableName[Country]")
    - summarizeBy: "sum" for numeric types, "none" for others
    
    Args:
        table: Table object to enrich with properties (mutates in place)
    """
    if table.kind != "table":
        return
    
    for column in table.columns:
        # Set sourceColumn to the column name itself
        if not column.sourceColumn:
            column.sourceColumn = column.name
        
        # Set summarizeBy based on data type
        if not column.summarizeBy:
            if column.dataType in ("int64", "decimal", "double", "currency"):
                column.summarizeBy = "sum"
            else:
                column.summarizeBy = "none"


def compile_project(
    model_yaml: Path,
    sources_yaml: Path,
    outdir: Path,
    stub_report: bool = True,
    transforms_dirs: list[str] | None = None,
    dax_dirs: list[str] | None = None
) -> None:
    """
    Compile YAML specifications into a Power BI Project (.pbip) with TMDL files.
    
    This function orchestrates the complete compilation pipeline:
    1. Loads and validates YAML files using Pydantic models
    2. Creates the output directory structure for the Power BI project
    3. Emits all TMDL files (model, expressions, tables, relationships)
    4. Creates the complete .pbip project with semantic model and optional report
    
    Args:
        model_yaml: Path to model.yml file containing table and relationship definitions
        sources_yaml: Path to sources.yml file containing data source configurations
        outdir: Output directory for the generated Power BI project
        stub_report: Whether to create a stub report (default: True)
        transforms_dirs: Optional list of directories to search for M-code transforms
        dax_dirs: Optional list of directories to search for DAX templates
    
    Raises:
        FileNotFoundError: If input YAML files don't exist
        ValidationError: If YAML files don't match the expected schema
        ValueError: If there are validation errors in the specifications
        Exception: For other compilation errors (I/O, template rendering, etc.)
    
    Example:
        >>> from pathlib import Path
        >>> compile_project(
        ...     model_yaml=Path("specs/model.yml"),
        ...     sources_yaml=Path("specs/sources.yml"),
        ...     outdir=Path("output/MyProject")
        ... )
    """
    try:
        # Step 1: Load and validate YAML files
        logger.info(f"Loading model from {model_yaml}")
        if not model_yaml.exists():
            raise FileNotFoundError(f"Model file not found: {model_yaml}")
        
        logger.info(f"Loading sources from {sources_yaml}")
        if not sources_yaml.exists():
            raise FileNotFoundError(f"Sources file not found: {sources_yaml}")
        
        # Load sources specification
        sources_data = yaml.safe_load(sources_yaml.read_text(encoding='utf-8'))
        sources = SourcesSpec(**sources_data)
        logger.info(f"Loaded {len(sources.sources)} source(s)")
        
        # Load model specification
        model_data = yaml.safe_load(model_yaml.read_text(encoding='utf-8'))
        spec = ModelSpec(**model_data)
        logger.info(f"Loaded model '{spec.model.name}' with {len(spec.model.tables)} table(s)")
        
        # # Log warning if hide_extras_introspect is enabled (MVP limitation)
        # if hide_extras_introspect:
        #     logger.warning(
        #         "hide_extras_introspect=True is not implemented in MVP. "
        #         "Tables with column_policy='hide_extras' will be treated as 'keep_all'."
        #     )
        
        # Step 2: Create directory structure
        root = outdir
        sm_dir = root / f"{spec.model.name}.SemanticModel"
        def_dir = sm_dir / "definition"
        tbl_dir = def_dir / "tables"
        
        logger.info(f"Creating project structure at {outdir}")
        tbl_dir.mkdir(parents=True, exist_ok=True)
        
        # Step 3: Emit all TMDL files
        logger.info("Emitting semantic model files...")
        
        # Emit .pbism marker file
        emit_pbism(sm_dir)
        logger.debug(f"Created {sm_dir / 'definition.pbism'}")
        
        # Emit database.tmdl with compatibility level
        emit_database_tmdl(def_dir)
        logger.debug(f"Created {def_dir / 'database.tmdl'}")
        
        # Emit model.tmdl with model-level properties
        emit_model_tmdl(def_dir, spec.model)
        logger.debug(f"Created {def_dir / 'model.tmdl'}")
        
        # Emit culture info
        emit_culture_tmdl(def_dir, spec.model.culture)
        logger.debug(f"Created {def_dir / 'cultures' / spec.model.culture}.tmdl")
        
        # Resolve and load transforms into context
        from .discovery import resolve_transform_dirs
        from .transforms import load_transforms
        from .dax import load_dax_templates
        
        project_root = model_yaml.parent
        
        # Load M-code transforms
        transform_search_dirs = resolve_transform_dirs(project_root, transforms_dirs or [])
        logger.info(f"Loading transforms from {transform_search_dirs}")
        transforms = load_transforms(transform_search_dirs, logger)
        
        # Load DAX templates
        # Use same search pattern as transforms: project-local dirs override global
        dax_search_dirs = []
        if dax_dirs:
            dax_search_dirs.extend([Path(d) for d in dax_dirs])
        # Also check for 'dax' subdirectory in project root
        project_dax_dir = project_root / "dax"
        if project_dax_dir.exists():
            dax_search_dirs.append(project_dax_dir)
        
        logger.info(f"Loading DAX templates from {dax_search_dirs}")
        dax_templates = load_dax_templates(dax_search_dirs, logger)

        # Emit expressions.tmdl with M source functions and transforms
        # DISABLED: Shared expressions cause composite model errors in Power BI
        # emit_expressions_tmdl(def_dir, sources, transforms)
        # logger.debug(f"Created {def_dir / 'expressions.tmdl'}")
        
        # Emit individual table TMDL files
        logger.info(f"Emitting {len(spec.model.tables)} table(s)...")
        for table in spec.model.tables:
            # Resolve DAX templates before processing
            if table.kind == "calculatedTable" and table.calculatedTableDef:
                if table.calculatedTableDef.template:
                    template_name = table.calculatedTableDef.template
                    if template_name in dax_templates:
                        # Replace template reference with actual DAX expression
                        table.calculatedTableDef.expression = dax_templates[template_name]
                        logger.debug(f"Resolved DAX template '{template_name}' for table '{table.name}'")
                    else:
                        raise ValueError(
                            f"DAX template '{template_name}' not found for table '{table.name}'. "
                            f"Available templates: {list(dax_templates.keys())}"
                        )
            
            # Set properties for regular tables
            if table.kind == "table":
                set_regular_table_column_properties(table)
            # Infer sourceColumn properties for calculated tables
            elif table.kind == "calculatedTable":
                infer_calculated_table_column_properties(table)
            
            emit_table_tmdl(tbl_dir, table, sources, transforms, dax_templates)
            logger.debug(f"Created {tbl_dir / table.name}.tmdl")
        
        # Emit relationships.tmdl if relationships exist
        if spec.model.relationships:
            emit_relationships_tmdl(def_dir, spec.model)
            logger.info(f"Created {len(spec.model.relationships)} relationship(s)")
        else:
            logger.info("No relationships to emit")
        
        # Step 4: Create stub report and .pbip file
        if stub_report:
            rpt_dir = root / f"{spec.model.name}.Report"
            logger.info("Creating stub report...")
            emit_report_by_path(rpt_dir, rel_model_path=f"../{spec.model.name}.SemanticModel")
            logger.debug(f"Created {rpt_dir / 'definition.pbir'}")
            
            # Create .pbip project file
            # Note: Only the report artifact is listed; Power BI discovers the semantic model automatically
            pbip_content = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [
                    {
                        "report": {
                            "path": f"{spec.model.name}.Report"
                        }
                    }
                ],
                "settings": {
                    "enableAutoRecovery": True
                }
            }
            
            pbip_path = root / f"{spec.model.name}.pbip"
            pbip_path.write_text(json.dumps(pbip_content, indent=2), encoding='utf-8')
            logger.info(f"Compilation complete: {pbip_path}")
        else:
            logger.info(f"Compilation complete: {sm_dir}")
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}")
        raise ValueError(f"Invalid YAML format: {e}") from e
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"Compilation failed: {e}")
        raise