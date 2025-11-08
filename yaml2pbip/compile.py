"""Main compiler pipeline for yaml2pbip."""
from pathlib import Path
import yaml
import json
import logging
from typing import Optional

from .spec import SourcesSpec, ModelSpec
from .emit import (
    emit_pbism,
    emit_model_tmdl,
    emit_expressions_tmdl,
    emit_table_tmdl,
    emit_relationships_tmdl,
    emit_report_by_path
)

logger = logging.getLogger(__name__)


def compile_project(
    model_yaml: Path,
    sources_yaml: Path,
    outdir: Path,
    stub_report: bool = True,
    hide_extras_introspect: bool = False,
    transforms_dirs: list[str] | None = None
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
        hide_extras_introspect: Whether to introspect for hide_extras policy (default: False)
                               Note: MVP implementation treats this as keep_all
    
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
        
        # Log warning if hide_extras_introspect is enabled (MVP limitation)
        if hide_extras_introspect:
            logger.warning(
                "hide_extras_introspect=True is not implemented in MVP. "
                "Tables with column_policy='hide_extras' will be treated as 'keep_all'."
            )
        
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
        
        # Emit model.tmdl with model-level properties
        emit_model_tmdl(def_dir, spec.model)
        logger.debug(f"Created {def_dir / 'model.tmdl'}")
        
        # Resolve and load transforms into context
        from .discovery import resolve_transform_dirs
        from .transforms import load_transforms
        project_root = model_yaml.parent
        dirs = resolve_transform_dirs(project_root, transforms_dirs or [])
        logger.info(f"Loading transforms from {dirs}")
        transforms = load_transforms(dirs, logger)

        # Emit expressions.tmdl with M source functions and transforms
        emit_expressions_tmdl(def_dir, sources, transforms)
        logger.debug(f"Created {def_dir / 'expressions.tmdl'}")
        
        # Emit individual table TMDL files
        logger.info(f"Emitting {len(spec.model.tables)} table(s)...")
        for table in spec.model.tables:
            emit_table_tmdl(tbl_dir, table, sources, transforms)
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
            pbip_content = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [
                    {
                        "report": {
                            "path": f"{spec.model.name}.Report"
                        }
                    }
                ]
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