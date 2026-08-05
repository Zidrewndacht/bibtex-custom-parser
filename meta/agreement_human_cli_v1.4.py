# meta/agreement_human_cli_v1.4.py
"""
Generates the intended Human--AI Alignment Summary table from the exact
intersection of papers present in both the user-modified DB and the AI DB.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import yaml
from scipy import stats


# ============================================================================
# Constants
# ============================================================================

MIN_N_FOR_CI = 100

PLACEHOLDER_TITLE = (
    "Database is missing or empty. Import BibTeX or restore from a backup "
    "to start working"
)

OUTCOMES: List[Tuple[str, str]] = [
    ("exact_match", "Exact Match"),
    ("partial_match", "Partial Match"),
    ("conflict", "Conflicts"),
    ("ai_overconfidence", "AI Overconfidence"),
    ("ai_underconfidence", "AI Underconfidence"),
    ("internal_contradiction", "Internal Contradiction"),
]


# ============================================================================
# Config loading
# ============================================================================

def load_domain_config(config_path: Optional[str], ai_db_path: str) -> dict:
    """
    Load domain_config.yaml.

    Resolution order:
      1. explicit --config;
      2. next to the AI DB;
      3. current working directory;
      4. script directory;
      5. parent directory.
    """

    def _load(path: Path) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)

            if cfg is None:
                return {}

            if isinstance(cfg, dict):
                return cfg

            print(f"Warning: {path} is not a YAML dictionary.", file=sys.stderr)

        except Exception as e:
            print(f"Warning: Failed to parse {path}: {e}", file=sys.stderr)

        return None

    if config_path:
        p = Path(config_path)
        if p.exists():
            cfg = _load(p)
            if cfg is not None:
                return cfg
        else:
            print(f"Warning: explicit config not found: {config_path}",
                  file=sys.stderr)

    candidates = [
        Path(ai_db_path).resolve().parent / "domain_config.yaml",
        Path.cwd() / "domain_config.yaml",
        Path(__file__).resolve().parent / "domain_config.yaml",
        Path(__file__).resolve().parent.parent / "domain_config.yaml",
    ]

    for candidate in candidates:
        if candidate.exists():
            cfg = _load(candidate)
            if cfg is not None:
                return cfg

    print(
        "Warning: domain_config.yaml not found. Using only universal field "
        "'is_offtopic'. Results will only be comparable if the other script "
        "is also run without a domain config.",
        file=sys.stderr,
    )
    return {}


def discover_boolean_fields(domain_config: dict) -> List[str]:
    """
    Same field-discovery logic as the 3-run agreement script:

    - always include is_offtopic;
    - include tri_state group json_paths;
    - include inclusion/none group fields as parent.key;
    - skip fields with render_type == 'text_presence'.
    """
    fields: List[str] = ["is_offtopic"]

    for group in domain_config.get("groups", []):
        ft = group.get("filter_type")

        if ft == "tri_state":
            path = group.get("json_path", "")
            if path and path not in fields:
                fields.append(path)

        elif ft in ("inclusion", "none"):
            parent = group.get("json_path", "")

            for fdef in group.get("fields", []):
                if fdef.get("render_type") == "text_presence":
                    continue

                key = fdef.get("key", "")
                if not key:
                    continue

                full_path = f"{parent}.{key}" if parent else key
                if full_path not in fields:
                    fields.append(full_path)

    return fields


# ============================================================================
# Generic helpers
# ============================================================================

def get_val_by_path(d: Dict, path: str):
    """Safely get a value from a nested dict using dot-notation."""
    if not d or not path:
        return None

    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None

    return cur


def parse_json_blob(blob) -> Dict:
    """Parse a JSON blob column into a dict safely."""
    if not blob:
        return {}

    if isinstance(blob, dict):
        return blob

    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def encode_tri_state(val) -> int:
    """
    Encode values as:
      2 = True / Yes
      1 = False / No
      0 = Unknown / None
    """
    if val is True:
        return 2
    if val is False:
        return 1
    if val == 1:
        return 2
    if val == 0:
        return 1

    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return 2
        if v in ("false", "0", "no", "off"):
            return 1

    return 0


# ============================================================================
# Statistical helpers
# ============================================================================

def wilson_score_interval(successes: int, n: int,
                          confidence: float = 0.95) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 100.0

    z = stats.norm.ppf((1 + confidence) / 2)
    p_hat = successes / n
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denominator
    margin = (
        z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator
    )

    lower = max(0.0, (centre - margin) * 100)
    upper = min(100.0, (centre + margin) * 100)

    return lower, upper


def format_with_ci(pct: float, count: int, total: int,
                   min_n: int = MIN_N_FOR_CI) -> str:
    if total < min_n:
        return f"{pct:.2f}% ({count:,})"

    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"


# ============================================================================
# Alignment logic
# ============================================================================

def majority_value(values: List[int]) -> int:
    """
    AI majority value from three encoded runs.

    2 = Yes, 1 = No, 0 = Unknown.
    """
    yes = values.count(2)
    no = values.count(1)

    if yes > no:
        return 2
    if no > yes:
        return 1

    return 0


def classify_ai_internal_agreement(values: List[int]) -> str:
    """
    Simplified 3-run AI agreement class:

    - perfect: all three runs identical;
    - contradiction: Yes and No both appear;
    - uncertain: anything else.
    """
    counts = Counter(values)

    if len(counts) == 1:
        return "perfect"

    has_yes = counts.get(2, 0) > 0
    has_no = counts.get(1, 0) > 0

    if has_yes and has_no:
        return "contradiction"

    return "uncertain"


def classify_human_ai_outcome(human_val: int, ai_values: List[int]) -> str:
    """
    Mutually exclusive Human--AI alignment outcome.

    Precedence:
      1. AI internal contradiction.
      2. Human agrees with AI majority:
           - exact if AI perfect;
           - partial if AI uncertain.
      3. Human/AI known disagreement:
           - conflict if both known and opposite;
           - AI overconfidence if AI known and human unknown;
           - AI underconfidence if human known and AI unknown.
    """
    ai_internal = classify_ai_internal_agreement(ai_values)
    ai_main = majority_value(ai_values)

    if ai_internal == "contradiction":
        return "internal_contradiction"

    if human_val == ai_main:
        if ai_internal == "perfect":
            return "exact_match"
        return "partial_match"

    if human_val in (1, 2) and ai_main in (1, 2):
        return "conflict"

    if ai_main in (1, 2) and human_val == 0:
        return "ai_overconfidence"

    if ai_main == 0 and human_val in (1, 2):
        return "ai_underconfidence"

    return "partial_match"


# ============================================================================
# Data loading
# ============================================================================

def load_alignment_data(user_db_path: str,
                        ai_db_path: str,
                        fields: List[str],
                        quiet: bool = False) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Load both DBs and return only the exact intersection of paper IDs.
    """
    if not quiet:
        print(f"  Loading User DB: {user_db_path}")

    conn_u = sqlite3.connect(user_db_path)
    conn_u.row_factory = sqlite3.Row
    user_rows = {
        str(row["id"]): dict(row)
        for row in conn_u.execute("SELECT * FROM papers")
    }
    conn_u.close()

    if not quiet:
        print(f"  Loading AI DB: {ai_db_path}")

    conn_a = sqlite3.connect(ai_db_path)
    conn_a.row_factory = sqlite3.Row
    ai_rows = {
        str(row["id"]): dict(row)
        for row in conn_a.execute("SELECT * FROM papers")
    }
    conn_a.close()

    common_ids = sorted(set(user_rows.keys()) & set(ai_rows.keys()), key=str)

    missing_in_user = set(ai_rows.keys()) - set(user_rows.keys())
    missing_in_ai = set(user_rows.keys()) - set(ai_rows.keys())

    if not quiet:
        if missing_in_user:
            print(f"  ⚠️  {len(missing_in_user)} papers in AI DB missing from User DB")
        if missing_in_ai:
            print(f"  ⚠️  {len(missing_in_ai)} papers in User DB missing from AI DB")

    # Exclude placeholder row explicitly.
    common_ids = [
        pid for pid in common_ids
        if user_rows[pid].get("title") != PLACEHOLDER_TITLE
        and ai_rows[pid].get("title") != PLACEHOLDER_TITLE
    ]

    data: Dict[str, Dict] = {}

    for pid in common_ids:
        user_blob = parse_json_blob(user_rows[pid].get("classification"))

        ai_blobs = [
            parse_json_blob(ai_rows[pid].get("set_1_llm")),
            parse_json_blob(ai_rows[pid].get("set_2_llm")),
            parse_json_blob(ai_rows[pid].get("set_3_llm")),
        ]

        human_values = {
            field: encode_tri_state(get_val_by_path(user_blob, field))
            for field in fields
        }

        ai_values = {
            field: [
                encode_tri_state(get_val_by_path(ai_blobs[0], field)),
                encode_tri_state(get_val_by_path(ai_blobs[1], field)),
                encode_tri_state(get_val_by_path(ai_blobs[2], field)),
            ]
            for field in fields
        }

        # AI off-topic majority:
        # off-topic if two or more AI sets say is_offtopic == True.
        ai_offtopic_votes = sum(
            1
            for blob in ai_blobs
            if encode_tri_state(get_val_by_path(blob, "is_offtopic")) == 2
        )

        data[pid] = {
            "human": human_values,
            "ai_vals": ai_values,
            "ai_offtopic": ai_offtopic_votes >= 2,
        }

    return data, common_ids


# ============================================================================
# Analysis
# ============================================================================

def analyze_stratum(data: Dict[str, Dict],
                    paper_ids: List[str],
                    fields: List[str],
                    stratum_name: str) -> Dict:
    counts = Counter()

    for pid in paper_ids:
        human = data[pid]["human"]
        ai_vals = data[pid]["ai_vals"]

        for field in fields:
            outcome = classify_human_ai_outcome(human[field], ai_vals[field])
            counts[outcome] += 1

    n_papers = len(paper_ids)
    n_obs = n_papers * len(fields)

    result = {
        "stratum": stratum_name,
        "n_papers": n_papers,
        "n_observations": n_obs,
    }

    for outcome_key, _ in OUTCOMES:
        cnt = counts.get(outcome_key, 0)
        pct = (cnt / n_obs * 100) if n_obs else 0.0
        lower, upper = wilson_score_interval(cnt, n_obs)

        result[outcome_key] = {
            "count": cnt,
            "pct": pct,
            "ci_lower": lower,
            "ci_upper": upper,
        }

    return result


def run_analysis(data: Dict[str, Dict],
                 paper_ids: List[str],
                 fields: List[str]) -> Dict:
    """
    Analyze the exact intersection set.

    Stratification is by AI 3-set majority off-topic status, matching the
    3-run agreement script.
    """
    on_topic = [pid for pid in paper_ids if not data[pid]["ai_offtopic"]]
    off_topic = [pid for pid in paper_ids if data[pid]["ai_offtopic"]]

    return {
        "on_topic": analyze_stratum(data, on_topic, fields, "on_topic"),
        "off_topic": analyze_stratum(data, off_topic, fields, "off_topic"),
        "all": analyze_stratum(data, paper_ids, fields, "all"),
    }


# ============================================================================
# Output
# ============================================================================

def print_summary(results: Dict, fields: List[str], subset_label: str) -> None:
    print("\n" + "=" * 90)
    print(f"HUMAN--AI ALIGNMENT SUMMARY ({subset_label})")
    print("=" * 90)

    for stratum_key, stratum_label in [
        ("all", "ALL"),
        ("on_topic", "ON-TOPIC"),
        ("off_topic", "OFF-TOPIC"),
    ]:
        s = results[stratum_key]

        print(
            f"\n📊 {stratum_label} "
            f"({s['n_papers']:,} papers × {len(fields)} fields = "
            f"{s['n_observations']:,} classification decisions)"
        )

        for outcome_key, outcome_label in OUTCOMES:
            d = s[outcome_key]
            line = format_with_ci(d["pct"], d["count"], s["n_observations"])
            print(f"   {outcome_label:<22} {line}")

    print("\n" + "=" * 90 + "\n")


def generate_latex_table(results: Dict,
                         output_path: str,
                         subset_label: str) -> None:
    on = results["on_topic"]
    off = results["off_topic"]
    all_ = results["all"]

    def cell(res: Dict, key: str) -> str:
        d = res[key]
        return rf"{d['pct']:.2f}\% ({d['count']:,})"

    def ci(res: Dict, key: str) -> str:
        d = res[key]
        return (
            rf"\textit{{\footnotesize "
            rf"[{d['ci_lower']:.2f}\%, {d['ci_upper']:.2f}\%]}}"
        )

    lines: List[str] = []

    lines.append(r"\begin{table*}[t]")
    lines.append(r"\centering")
    lines.append(
        rf"\caption{{Human--AI Alignment Summary ({subset_label}). "
        rf"Percentage shown first; count of classification decisions in parentheses. "
        rf"Wilson 95\% Confidence Intervals in italics}}"
    )
    lines.append(r"\label{tab:human_alignment}")
    lines.append(r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lccc@{}}")
    lines.append(r"\hline")
    lines.append(
        rf"\textbf{{Outcome}} & "
        rf"\textbf{{On-Topic ({on['n_observations']:,})}} & "
        rf"\textbf{{Off-Topic ({off['n_observations']:,})}} & "
        rf"\textbf{{All ({all_['n_observations']:,})}} \\"
    )
    lines.append(r"\hline")

    last_index = len(OUTCOMES) - 1

    for i, (outcome_key, outcome_label) in enumerate(OUTCOMES):
        lines.append(
            rf"\textbf{{{outcome_label}}} & "
            rf"{cell(on, outcome_key)} & "
            rf"{cell(off, outcome_key)} & "
            rf"{cell(all_, outcome_key)} \\"
        )

        spacing = r"\\[6pt]" if i != last_index else r"\\"

        lines.append(
            rf"\quad \textit{{\footnotesize 95\% CI}} & "
            rf"{ci(on, outcome_key)} & "
            rf"{ci(off, outcome_key)} & "
            rf"{ci(all_, outcome_key)} "
            rf"{spacing}"
        )

    lines.append(r"\hline")
    lines.append(r"\end{tabular*}")
    lines.append(r"\end{table*}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("% Human--AI Alignment Summary\n")
        f.write("% Generated by human_ai_alignment_summary.py\n\n")
        f.write("\n".join(lines))
        f.write("\n")

    print(f"  LaTeX table saved to: {output_path}")


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the intended Human--AI Alignment Summary table from "
            "the exact intersection of a user-modified DB and an AI DB."
        )
    )

    parser.add_argument("--user-db", required=True,
                        help="Path to user-modified database")
    parser.add_argument("--ai-db", required=True,
                        help="Path to AI-classified database")
    parser.add_argument("--config", default=None,
                        help="Path to domain_config.yaml. For comparability, "
                             "use the same config as the 3-run script.")
    parser.add_argument("-o", "--output",
                        default="human_ai_alignment_table.tex",
                        help="Output .tex path")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress progress output")
    parser.add_argument("--no-latex", action="store_true",
                        help="Print summary but do not write LaTeX")

    args = parser.parse_args()

    if not Path(args.user_db).exists() or not Path(args.ai_db).exists():
        print("Error: One or both database files not found.", file=sys.stderr)
        return 1

    if not args.quiet:
        print("ResearchParsa | Human--AI Alignment Summary")

    domain_cfg = load_domain_config(args.config, args.ai_db)
    fields = discover_boolean_fields(domain_cfg)

    if not args.quiet:
        if domain_cfg:
            print("  ✅ Loaded domain_config.yaml")
        else:
            print("  ⚠️  No usable domain_config.yaml found")

        preview = ", ".join(fields[:5])
        ellipsis = "..." if len(fields) > 5 else ""
        print(f"  📋 Comparing {len(fields)} fields: {preview}{ellipsis}")

    data, common_ids = load_alignment_data(
        args.user_db,
        args.ai_db,
        fields,
        quiet=args.quiet,
    )

    if not common_ids:
        print("Error: No common paper IDs found between databases.",
              file=sys.stderr)
        return 1

    if not args.quiet:
        on_count = sum(1 for pid in common_ids if not data[pid]["ai_offtopic"])
        off_count = len(common_ids) - on_count
        print(f"  Intersection size: {len(common_ids)} papers")
        print(f"  Stratification: {on_count} on-topic, {off_count} off-topic")

    results = run_analysis(data, common_ids, fields)

    # Caption label is derived from the intersection size only.
    # If you prefer the literal word "intersection", change this one line to:
    #   subset_label = f"{len(common_ids)}-paper intersection subset"
    subset_label = f"{len(common_ids)}-paper stratified subset"

    if not args.quiet:
        print_summary(results, fields, subset_label)

    if not args.no_latex:
        output_path = args.output
        if not output_path.lower().endswith(".tex"):
            output_path += ".tex"

        generate_latex_table(results, output_path, subset_label)

    if not args.quiet:
        print("Analysis complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())