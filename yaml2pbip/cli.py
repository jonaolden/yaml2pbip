"""Command-line interface for yaml2pbip."""

import argparse
import logging
import sys
from pathlib import Path

from .compile import compile_project


def main():
    """Main entry point for the yaml2pbip CLI."""
    parser = argparse.ArgumentParser(
        prog="yaml2pbip",
        description="Compile YAML specifications to Power BI Project format"
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Compile subcommand
    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile YAML files to .pbip project"
    )
    compile_parser.add_argument(
        "model_yaml",
        type=Path,
        help="Path to model.yml file"
    )
    compile_parser.add_argument(
        "sources_yaml",
        type=Path,
        help="Path to sources.yml file"
    )
    compile_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for generated project"
    )
    compile_parser.add_argument(
        "--no-stub-report",
        action="store_true",
        help="Don't create a stub report"
    )
    # compile_parser.add_argument(
    #     "--introspect-hide-extras",
    #     action="store_true",
    #     help="Enable introspection for hide_extras column policy (MVP: not yet implemented)"
    # )

    compile_parser.add_argument(
        "--transforms-dir",
        action="append",
        default=[],
        help="Additional transforms directories (repeatable)."
    )
    compile_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    # Version subcommand
    version_parser = subparsers.add_parser(
        "version",
        help="Show version"
    )
    
    args = parser.parse_args()
    
    # Configure logging based on verbosity
    if args.command == "compile":
        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(levelname)s: %(message)s"
        )
    
    # Handle version command
    if args.command == "version":
        from . import __version__
        print(f"yaml2pbip version {__version__}")
        sys.exit(0)
    
    # Execute compile command
    if args.command == "compile":
        # Validate input files exist
        if not args.model_yaml.exists():
            logging.error(f"Model file not found: {args.model_yaml}")
            sys.exit(1)
        
        if not args.sources_yaml.exists():
            logging.error(f"Sources file not found: {args.sources_yaml}")
            sys.exit(1)
        
        try:
            compile_project(
                model_yaml=args.model_yaml,
                sources_yaml=args.sources_yaml,
                outdir=args.out,
                stub_report=not args.no_stub_report,
                # hide_extras_introspect=args.introspect_hide_extras,
                transforms_dirs=args.transforms_dir
            )
            # Find the generated .pbip file to display in success message
            pbip_files = list(args.out.glob("*.pbip"))
            if pbip_files:
                print(f"\n✓ Successfully compiled to {pbip_files[0]}")
            else:
                print(f"\n✓ Successfully compiled to {args.out}")
            sys.exit(0)
        except (FileNotFoundError, ValueError) as e:
            logging.error(f"Error: {e}")
            if args.verbose:
                logging.exception("Full traceback:")
            sys.exit(1)
        except Exception as e:
            logging.error(f"Compilation failed: {e}")
            if args.verbose:
                logging.exception("Full traceback:")
            sys.exit(1)


if __name__ == "__main__":
    main()