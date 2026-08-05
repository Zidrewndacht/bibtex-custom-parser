# meta/agreement_3sets_cli_v1.4.py
"""
3-Run Agreement Analysis for ResearchParça (Configurable Domain)

Thin CLI wrapper around shared/agreement.py. All statistics, stratification
(including the decisive off-topic majority eligibility rule), LaTeX generation
and output formatting live in the shared module, so this tool and the web UI's
/agreement_report page can never drift apart.
"""

import argparse
import os
import sys

# Repo root (this script lives in meta/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from meta import agreement_core


def load_domain_config_file(config_path: str) -> dict:
    """Load domain configuration from a YAML file (CLI-side resolution)."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        if not cfg or not isinstance(cfg, dict):
            cfg = {}
    except FileNotFoundError:
        print(f"Warning: Domain config not found at '{config_path}'. "
              f"Only universal fields will be analysed.", file=sys.stderr)
        cfg = {}
    except Exception as e:
        print(f"Error loading domain config: {e}", file=sys.stderr)
        cfg = {}
    cfg.setdefault('groups', [])
    cfg.setdefault('editable_fields', [])
    return cfg


def main():
    parser = argparse.ArgumentParser(
        description='3-run agreement analysis for ResearchParça '
                    '(configurable domain)')
    parser.add_argument('--db', required=True,
                        help='Path to SQLite database (new schema)')
    parser.add_argument('--config', default=None,
                        help='Path to domain_config.yaml '
                             '(default: ./domain_config.yaml)')
    parser.add_argument('-o', '--output',
                        default='agreement_3run_results',
                        help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress progress output')
    parser.add_argument('--no-latex', action='store_true',
                        help='Skip LaTeX table generation')
    args = parser.parse_args()

    from pathlib import Path
    if not Path(args.db).exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # --- Resolve domain config path ---
    if args.config:
        config_path = args.config
    else:
        # Try next to the DB, then CWD, then script directory
        db_dir = Path(args.db).resolve().parent
        candidates = [
            db_dir / 'domain_config.yaml',
            Path.cwd() / 'domain_config.yaml',
            Path(__file__).resolve().parent / 'domain_config.yaml',
        ]
        config_path = str(candidates[0])  # default fallback
        for c in candidates:
            if c.exists():
                config_path = str(c)
                break

    if not args.quiet:
        print("ResearchParça 3-Run Agreement Analysis "
              "(Configurable Domain + Wilson CIs)")
        print(f"Database:      {args.db}")
        print(f"Domain config: {config_path}")

    # --- Load config & discover fields ---
    domain_config = load_domain_config_file(config_path)
    boolean_fields = agreement_core.discover_boolean_fields(domain_config)
    categories = agreement_core.get_field_categories(domain_config, boolean_fields)

    if not args.quiet:
        print(f"Boolean fields ({len(boolean_fields)}): "
              f"{', '.join(boolean_fields)}")
        print(f"Categories: "
              f"{', '.join(name for name, _ in categories)}\n")

    # --- Load data ---
    if not args.quiet:
        print("Loading database into RAM...")
    papers = agreement_core.load_all_papers_from_single_db(args.db, boolean_fields)

    if not args.quiet:
        print(f"Loaded {len(papers)} papers with 3-run data. "
              f"Starting analysis...\n")

    # --- Analyse ---
    results = agreement_core.run_analysis(papers, boolean_fields, args.db,
                                     verbose=not args.quiet)

    if not args.quiet:
        agreement_core.print_summary(results, categories)

    if not args.no_latex:
        latex_path = f"{args.output}_tables.tex"
        if not args.quiet:
            print("Generating LaTeX tables...")
        agreement_core.generate_latex_tables(results, latex_path, categories)

    if not args.quiet:
        print("Analysis complete.")

    return 0


if __name__ == '__main__':
    sys.exit(main())