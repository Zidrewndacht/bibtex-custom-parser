#!/usr/bin/env python3
"""
3-Run Agreement Analysis for ResearchParça (Configurable Domain)

Reads field definitions from domain_config.yaml and paper data from the
new single-DB schema (set_N_llm JSON blobs).  All statistical results
and output formatting are identical to the original standalone version.
"""

import argparse
import sqlite3
import json
import sys
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
import numpy as np
import pandas as pd
from scipy import stats
import yaml

# ============================================================================
# CONFIGURATION — loaded dynamically from domain_config.yaml
# ============================================================================

MIN_N_FOR_CI = 100
SET_LOG_COLUMNS = ['set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']

# Relevance bin configuration (0-10 integer scale) — unchanged
RELEVANCE_BINS = [
    (0, 1, "Very Low (0-1)"),
    (2, 3, "Low (2-3)"),
    (4, 5, "Medium (4-5)"),
    (6, 7, "High (6-7)"),
    (8, 10, "Very High (8-10)")
]


# ============================================================================
# DOMAIN CONFIG LOADING & FIELD DISCOVERY
# ============================================================================

def load_domain_config(config_path: str) -> dict:
    """Load domain configuration from a YAML file."""
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


def discover_boolean_fields(domain_config: dict) -> List[str]:
    """
    Build the list of boolean (tri-state) fields from domain_config groups.
    'is_offtopic' is always included as a universal field required for
    stratification, even when the YAML does not list it explicitly.
    """
    fields: List[str] = ['is_offtopic']
    for group in domain_config.get('groups', []):
        ft = group.get('filter_type')
        if ft == 'tri_state':
            path = group.get('json_path', '')
            if path and path not in fields:
                fields.append(path)
        elif ft in ('inclusion', 'none'):
            parent = group.get('json_path', '')
            for fdef in group.get('fields', []):
                key = fdef.get('key', '')
                if not key:
                    continue
                full_path = f"{parent}.{key}" if parent else key
                if full_path not in fields:
                    fields.append(full_path)
    return fields


def get_field_categories(domain_config: dict,
                         boolean_fields: List[str]) -> List[Tuple[str, List[str]]]:
    """
    Derive display categories from domain_config groups for the summary
    printer and LaTeX Table 5.  Returns [(category_name, [field, …]), …].
    """
    categories: List[Tuple[str, List[str]]] = []
    already: set = set()

    for group in domain_config.get('groups', []):
        ft = group.get('filter_type')
        cat_name = (group.get('friendly_name')
                    or group.get('label')
                    or group.get('json_path', 'Unknown'))
        cat_fields: List[str] = []

        if ft == 'tri_state':
            path = group.get('json_path', '')
            if path in boolean_fields:
                cat_fields.append(path)
        elif ft in ('inclusion', 'none'):
            parent = group.get('json_path', '')
            for fdef in group.get('fields', []):
                key = fdef.get('key', '')
                full_path = f"{parent}.{key}" if parent else key
                if full_path in boolean_fields:
                    cat_fields.append(full_path)

        if cat_fields:
            categories.append((cat_name, cat_fields))
            already.update(cat_fields)

    # Prepend universal fields that no group claimed (e.g. is_offtopic)
    uncategorized = [f for f in boolean_fields if f not in already]
    if uncategorized:
        categories.insert(0, ('Universal / Main Classification', uncategorized))

    return categories


def get_val_by_path(d: dict, path: str):
    """Safely traverse a nested dict with a dot-separated key path."""
    if not d or not path:
        return None
    for k in path.split('.'):
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d


# ============================================================================
# STATISTICAL HELPERS  (unchanged)
# ============================================================================

def wilson_score_interval(successes: int, n: int,
                          confidence: float = 0.95) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    z = stats.norm.ppf((1 + confidence) / 2)
    p_hat = successes / n
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2*n)) / denominator
    margin = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*n)) / n) / denominator
    lower = max(0, (centre - margin) * 100)
    upper = min(100, (centre + margin) * 100)
    return lower, upper


def format_with_ci(pct: float, count: int, total: int,
                   min_n: int = MIN_N_FOR_CI) -> str:
    if total < min_n:
        return f"{pct:.2f}% ({count:,})"
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"


def escape_latex_percent(text: str) -> str:
    return text.replace('%', '\\%')


def bin_relevance_score(relevance: Optional[int]) -> str:
    if relevance is None:
        return "Unknown"
    for low, high, label in RELEVANCE_BINS:
        if low <= relevance <= high:
            return label
    return "Unknown"


# ============================================================================
# DATA LOADING  (adapted to new schema: set_N_llm JSON blobs)
# ============================================================================

def load_all_papers_from_single_db(db_path: str,
                                   boolean_fields: List[str]
                                   ) -> Dict[str, Dict[int, Dict]]:
    """
    Read every paper's three set_N_llm JSON blobs and encode each
    boolean field as 2 (True), 1 (False), 0 (None/unknown).
    Also stores the integer relevance score under '_relevance'.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()

    papers: Dict[str, Dict[int, Dict]] = {}
    for row in rows:
        paper_id = str(row['id'])
        row_dict = dict(row)

        sets_data: Dict[int, Dict] = {}
        for set_num in (1, 2, 3):
            blob_key = f'set_{set_num}_llm'
            try:
                blob = json.loads(row_dict.get(blob_key) or '{}')
                if not isinstance(blob, dict):
                    blob = {}
            except (json.JSONDecodeError, TypeError):
                blob = {}

            encoded: Dict = {}

            # Boolean fields (dot-path into the JSON blob)
            for field in boolean_fields:
                val = get_val_by_path(blob, field)
                if val is True or val == 1:
                    encoded[field] = 2
                elif val is False or val == 0:
                    encoded[field] = 1
                else:
                    encoded[field] = 0

            # Relevance (integer, used for stratification only)
            rel_val = blob.get('relevance')
            encoded['_relevance'] = (int(rel_val)
                                     if isinstance(rel_val, (int, float))
                                     else None)

            sets_data[set_num] = encoded

        papers[paper_id] = sets_data

    return papers

def analyze_llm_logs(db_path: str, paper_ids: List[str]) -> Dict:
    """
    Analyzes the full history of LLM logs for the given papers.
    Counts invalid entries (including superseded ones) and tracks runs to consensus.
    """
    empty_consensus = {
        'avg_runs': 0.0, 'max_runs': 0, 'max_runs_paper': None, 
        'max_runs_set': None, 'total_classify_runs': 0, 'num_sets_analyzed': 0
    }
    empty_logs = {'total_entries': 0, 'invalid_entries': 0, 'invalid_pct': 0, 'per_set': {}}

    if not paper_ids:
        return {'log_stats': empty_logs, 'consensus_stats': empty_consensus}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    total_entries = 0
    invalid_entries = 0
    per_set_stats = {col: {'total': 0, 'invalid': 0} for col in SET_LOG_COLUMNS}
    
    all_runs_counts = [] 
    
    # Chunk queries to avoid SQLite's MAX_VARIABLE_NUMBER limit (usually 999)
    chunk_size = 900
    for i in range(0, len(paper_ids), chunk_size):
        chunk = paper_ids[i:i + chunk_size]
        placeholders = ','.join('?' * len(chunk))
        query = f"""
            SELECT id, set_1_llm_log, set_2_llm_log, set_3_llm_log 
            FROM papers WHERE id IN ({placeholders})
        """
        cursor.execute(query, chunk)
        rows = cursor.fetchall()
        
        for row in rows:
            paper_id = str(row['id'])
            for set_num, log_col in enumerate(SET_LOG_COLUMNS, start=1):
                log_json = row[log_col]
                if not log_json:
                    continue
                
                try:
                    log = json.loads(log_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                    
                set_total = 0
                set_invalid = 0
                classify_runs = 0
                
                # Iterate over the ENTIRE history array, including superseded entries
                for entry in log:
                    set_total += 1
                    if not entry.get('valid', True):
                        set_invalid += 1
                    
                    entry_type = entry.get('type', '')
                    if entry_type in ('classifier', 'consensus'):
                        classify_runs += 1
                        
                per_set_stats[log_col]['total'] += set_total
                per_set_stats[log_col]['invalid'] += set_invalid
                total_entries += set_total
                invalid_entries += set_invalid
                
                if classify_runs > 0:
                    all_runs_counts.append((classify_runs, paper_id, set_num))

    conn.close()

    for col in SET_LOG_COLUMNS:
        t = per_set_stats[col]['total']
        i = per_set_stats[col]['invalid']
        per_set_stats[col]['invalid_pct'] = (i / t * 100) if t > 0 else 0

    total_classify_runs = sum(r[0] for r in all_runs_counts)
    num_sets_with_runs = len(all_runs_counts)
    avg_runs = (total_classify_runs / num_sets_with_runs) if num_sets_with_runs > 0 else 0.0
    
    max_runs = 0
    max_paper = None
    max_set = None
    if all_runs_counts:
        max_entry = max(all_runs_counts, key=lambda x: x[0])
        max_runs = max_entry[0]
        max_paper = max_entry[1]
        max_set = max_entry[2]

    return {
        'log_stats': {
            'total_entries': total_entries,
            'invalid_entries': invalid_entries,
            'invalid_pct': (invalid_entries / total_entries * 100) if total_entries > 0 else 0,
            'per_set': per_set_stats
        },
        'consensus_stats': {
            'avg_runs': avg_runs,
            'max_runs': max_runs,
            'max_runs_paper': max_paper,
            'max_runs_set': max_set,
            'total_classify_runs': total_classify_runs,
            'num_sets_analyzed': num_sets_with_runs
        }
    }

# ============================================================================
# 3-RUN AGREEMENT LOGIC  (unchanged)
# ============================================================================

def classify_3run_agreement(values: List[int]) -> str:
    counts = Counter(values)
    if len(counts) == 1:
        return 'perfect'

    has_yes = counts.get(2, 0) > 0
    has_no = counts.get(1, 0) > 0

    if has_yes and has_no:
        yes_count = counts.get(2, 0)
        no_count = counts.get(1, 0)
        unknown_count = counts.get(0, 0)

        if yes_count == 1 and no_count == 1 and unknown_count == 1:
            return 'contradiction_chaotic'
        elif yes_count == 2 and no_count == 1:
            return 'contradiction_biased_yes'
        elif yes_count == 1 and no_count == 2:
            return 'contradiction_biased_no'
        else:
            return 'contradiction_chaotic'

    known_count = counts.get(2, 0) + counts.get(1, 0)
    if known_count == 2:
        return 'uncertain_biased_certain'
    else:
        return 'uncertain_biased_uncertain'


def analyze_field_agreement(papers: Dict[str, Dict[int, Dict]], field: str,
                            paper_ids: List[str]) -> Dict:
    perfect_count = 0
    uncertain_biased_certain_count = 0
    uncertain_biased_uncertain_count = 0
    contradiction_biased_yes_count = 0
    contradiction_biased_no_count = 0
    contradiction_chaotic_count = 0

    raw_yes = 0
    raw_no = 0
    raw_unknown = 0

    for paper_id in paper_ids:
        values = [papers[paper_id][set_num].get(field, 0) for set_num in [1, 2, 3]]

        raw_yes += values.count(2)
        raw_no += values.count(1)
        raw_unknown += values.count(0)

        agreement = classify_3run_agreement(values)

        if agreement == 'perfect':
            perfect_count += 1
        elif agreement == 'uncertain_biased_certain':
            uncertain_biased_certain_count += 1
        elif agreement == 'uncertain_biased_uncertain':
            uncertain_biased_uncertain_count += 1
        elif agreement == 'contradiction_biased_yes':
            contradiction_biased_yes_count += 1
        elif agreement == 'contradiction_biased_no':
            contradiction_biased_no_count += 1
        elif agreement == 'contradiction_chaotic':
            contradiction_chaotic_count += 1

    total = len(paper_ids)
    raw_total = total * 3

    return {
        'field': field,
        'n_papers': total,
        'n_observations': total,
        'raw_total': raw_total,
        'raw_yes': raw_yes,
        'raw_yes_pct': (raw_yes / raw_total * 100) if raw_total > 0 else 0,
        'raw_no': raw_no,
        'raw_no_pct': (raw_no / raw_total * 100) if raw_total > 0 else 0,
        'raw_unknown': raw_unknown,
        'raw_unknown_pct': (raw_unknown / raw_total * 100) if raw_total > 0 else 0,
        'perfect': perfect_count,
        'perfect_pct': (perfect_count / total * 100) if total > 0 else 0,
        'perfect_ci_lower': wilson_score_interval(perfect_count, total)[0],
        'perfect_ci_upper': wilson_score_interval(perfect_count, total)[1],
        'uncertain_biased_certain': uncertain_biased_certain_count,
        'uncertain_biased_certain_pct': (uncertain_biased_certain_count / total * 100) if total > 0 else 0,
        'uncertain_biased_certain_ci_lower': wilson_score_interval(uncertain_biased_certain_count, total)[0],
        'uncertain_biased_certain_ci_upper': wilson_score_interval(uncertain_biased_certain_count, total)[1],
        'uncertain_biased_uncertain': uncertain_biased_uncertain_count,
        'uncertain_biased_uncertain_pct': (uncertain_biased_uncertain_count / total * 100) if total > 0 else 0,
        'uncertain_biased_uncertain_ci_lower': wilson_score_interval(uncertain_biased_uncertain_count, total)[0],
        'uncertain_biased_uncertain_ci_upper': wilson_score_interval(uncertain_biased_uncertain_count, total)[1],
        'uncertain': uncertain_biased_certain_count + uncertain_biased_uncertain_count,
        'uncertain_pct': ((uncertain_biased_certain_count + uncertain_biased_uncertain_count) / total * 100) if total > 0 else 0,
        'uncertain_ci_lower': wilson_score_interval(
            uncertain_biased_certain_count + uncertain_biased_uncertain_count, total)[0],
        'uncertain_ci_upper': wilson_score_interval(
            uncertain_biased_certain_count + uncertain_biased_uncertain_count, total)[1],
        'contradiction_biased_yes': contradiction_biased_yes_count,
        'contradiction_biased_yes_pct': (contradiction_biased_yes_count / total * 100) if total > 0 else 0,
        'contradiction_biased_yes_ci_lower': wilson_score_interval(contradiction_biased_yes_count, total)[0],
        'contradiction_biased_yes_ci_upper': wilson_score_interval(contradiction_biased_yes_count, total)[1],
        'contradiction_biased_no': contradiction_biased_no_count,
        'contradiction_biased_no_pct': (contradiction_biased_no_count / total * 100) if total > 0 else 0,
        'contradiction_biased_no_ci_lower': wilson_score_interval(contradiction_biased_no_count, total)[0],
        'contradiction_biased_no_ci_upper': wilson_score_interval(contradiction_biased_no_count, total)[1],
        'contradiction_chaotic': contradiction_chaotic_count,
        'contradiction_chaotic_pct': (contradiction_chaotic_count / total * 100) if total > 0 else 0,
        'contradiction_chaotic_ci_lower': wilson_score_interval(contradiction_chaotic_count, total)[0],
        'contradiction_chaotic_ci_upper': wilson_score_interval(contradiction_chaotic_count, total)[1],
        'contradiction': contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count,
        'contradiction_pct': ((contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count) / total * 100) if total > 0 else 0,
        'contradiction_ci_lower': wilson_score_interval(
            contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count, total)[0],
        'contradiction_ci_upper': wilson_score_interval(
            contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count, total)[1],
    }


def analyze_stratum(papers: Dict[str, Dict[int, Dict]], paper_ids: List[str], 
                   fields: List[str], stratum_name: str, db_path: str) -> Dict:
    print(f"  Analyzing {stratum_name} ({len(paper_ids)} papers)...")
    
    empty_consensus = {
        'avg_runs': 0.0, 'max_runs': 0, 'max_runs_paper': None, 
        'max_runs_set': None, 'total_classify_runs': 0, 'num_sets_analyzed': 0
    }
    empty_logs = {'total_entries': 0, 'invalid_entries': 0, 'invalid_pct': 0, 'per_set': {}}

    if len(paper_ids) == 0:
        return {
            'stratum': stratum_name,
            'n_papers': 0,
            'n_fields': len(fields),
            'n_observations': 0,
            'field_results': pd.DataFrame(),
            'overall_perfect_pct': 0,
            'overall_contradiction_pct': 0,
            'overall_perfect_ci': (0, 100),
            'overall_contradiction_ci': (0, 100),
            'overall_raw_yes': 0, 'overall_raw_yes_pct': 0,
            'overall_raw_no': 0, 'overall_raw_no_pct': 0,
            'overall_raw_unknown': 0, 'overall_raw_unknown_pct': 0,
            'overall_raw_total': 0,
            'log_stats': empty_logs,
            'consensus_stats': empty_consensus
        }
    

    field_results = []
    for field in fields:
        result = analyze_field_agreement(papers, field, paper_ids)
        field_results.append(result)

    results_df = pd.DataFrame(field_results)

    overall_perfect = results_df['perfect'].sum()
    overall_uncertain = results_df['uncertain'].sum()
    overall_contradiction = results_df['contradiction'].sum()
    overall_contradiction_biased_yes = results_df['contradiction_biased_yes'].sum()
    overall_contradiction_biased_no = results_df['contradiction_biased_no'].sum()
    overall_contradiction_chaotic = results_df['contradiction_chaotic'].sum()
    total_observations = len(paper_ids) * len(fields)

    overall_perfect_ci = wilson_score_interval(overall_perfect, total_observations)
    overall_uncertain_ci = wilson_score_interval(overall_uncertain, total_observations)
    overall_contradiction_ci = wilson_score_interval(overall_contradiction, total_observations)

    overall_uncertain_biased_certain = results_df['uncertain_biased_certain'].sum()
    overall_uncertain_biased_uncertain = results_df['uncertain_biased_uncertain'].sum()
    overall_uncertain = overall_uncertain_biased_certain + overall_uncertain_biased_uncertain
    overall_uncertain_biased_certain_ci = wilson_score_interval(overall_uncertain_biased_certain, total_observations)
    overall_uncertain_biased_uncertain_ci = wilson_score_interval(overall_uncertain_biased_uncertain, total_observations)

    overall_raw_yes = results_df['raw_yes'].sum()
    overall_raw_no = results_df['raw_no'].sum()
    overall_raw_unknown = results_df['raw_unknown'].sum()
    overall_raw_total = results_df['raw_total'].sum()

    # Replace the old count_invalid_log_entries call:
    log_analysis = analyze_llm_logs(db_path, paper_ids)
    
    return {
        'stratum': stratum_name,
        'n_papers': len(paper_ids),
        'n_fields': len(fields),
        'n_observations': total_observations,
        'field_results': results_df,
        'overall_perfect': overall_perfect,
        'overall_perfect_pct': (overall_perfect / total_observations * 100) if total_observations > 0 else 0,
        'overall_perfect_ci_lower': overall_perfect_ci[0],
        'overall_perfect_ci_upper': overall_perfect_ci[1],
        'overall_uncertain_biased_certain': overall_uncertain_biased_certain,
        'overall_uncertain_biased_certain_pct': (overall_uncertain_biased_certain / total_observations * 100) if total_observations > 0 else 0,
        'overall_uncertain_biased_certain_ci_lower': overall_uncertain_biased_certain_ci[0],
        'overall_uncertain_biased_certain_ci_upper': overall_uncertain_biased_certain_ci[1],
        'overall_uncertain_biased_uncertain': overall_uncertain_biased_uncertain,
        'overall_uncertain_biased_uncertain_pct': (overall_uncertain_biased_uncertain / total_observations * 100) if total_observations > 0 else 0,
        'overall_uncertain_biased_uncertain_ci_lower': overall_uncertain_biased_uncertain_ci[0],
        'overall_uncertain_biased_uncertain_ci_upper': overall_uncertain_biased_uncertain_ci[1],
        'overall_uncertain': overall_uncertain,
        'overall_uncertain_pct': (overall_uncertain / total_observations * 100) if total_observations > 0 else 0,
        'overall_uncertain_ci_lower': overall_uncertain_ci[0],
        'overall_uncertain_ci_upper': overall_uncertain_ci[1],
        'overall_contradiction': overall_contradiction,
        'overall_contradiction_pct': (overall_contradiction / total_observations * 100) if total_observations > 0 else 0,
        'overall_contradiction_ci_lower': overall_contradiction_ci[0],
        'overall_contradiction_ci_upper': overall_contradiction_ci[1],
        'overall_contradiction_biased_yes': overall_contradiction_biased_yes,
        'overall_contradiction_biased_no': overall_contradiction_biased_no,
        'overall_contradiction_chaotic': overall_contradiction_chaotic,
        'overall_raw_yes': overall_raw_yes,
        'overall_raw_yes_pct': (overall_raw_yes / overall_raw_total * 100) if overall_raw_total > 0 else 0,
        'overall_raw_no': overall_raw_no,
        'overall_raw_no_pct': (overall_raw_no / overall_raw_total * 100) if overall_raw_total > 0 else 0,
        'overall_raw_unknown': overall_raw_unknown,
        'overall_raw_unknown_pct': (overall_raw_unknown / overall_raw_total * 100) if overall_raw_total > 0 else 0,
        'overall_raw_total': overall_raw_total,
        'log_stats': log_analysis['log_stats'],
        'consensus_stats': log_analysis['consensus_stats']
    }

def run_analysis(papers: Dict[str, Dict[int, Dict]], fields: List[str],
                 db_path: str) -> Dict:
    """Run stratified 3-run agreement analysis with relevance bins."""
    print(f"\nAnalyzing {len(fields)} fields across 3 runs...\n")

    all_paper_ids = list(papers.keys())

    # Stratify by off-topic status (from set 1)
    on_topic_ids: List[str] = []
    off_topic_ids: List[str] = []
    for paper_id in all_paper_ids:
        offtopic_val = papers[paper_id][1].get('is_offtopic', 0)
        if offtopic_val == 2:
            off_topic_ids.append(paper_id)
        else:
            on_topic_ids.append(paper_id)

    print(f"  Stratification: {len(on_topic_ids)} on-topic, "
          f"{len(off_topic_ids)} off-topic")

    # Stratify on-topic papers by relevance bin (using set_1 relevance)
    relevance_strata_clean: Dict[str, List[str]] = {}
    for low, high, label in RELEVANCE_BINS:
        key = (f"relevance_{label.replace(' ', '_')
                              .replace('(', '')
                              .replace(')', '')
                              .replace('-', '_')}")
        relevance_strata_clean[key] = [
            pid for pid in on_topic_ids
            if papers[pid][1].get('_relevance') is not None
            and low <= papers[pid][1]['_relevance'] <= high
        ]

    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids,
        **{f"on_topic_{key}": ids
           for key, ids in relevance_strata_clean.items()}
    }

    results = {}
    for stratum_name, stratum_ids in strata.items():
        results[stratum_name] = analyze_stratum(
            papers, stratum_ids, fields, stratum_name, db_path)

    return results


# ============================================================================
# LATEX TABLE GENERATION  (categories now dynamic)
# ============================================================================

def escape_latex_underscores(text: str) -> str:
    return text.replace('_', '\\_')


def generate_latex_tables(results: Dict, output_path: str,
                          categories: List[Tuple[str, List[str]]]):
    """Generate LaTeX tables for Elsevier two-column template."""
    tables = []

    on_topic_n = results['on_topic_only']['n_observations']
    off_topic_n = results['off_topic_only']['n_observations']
    all_papers_n = results['all_papers']['n_observations']

    # Guard against division by zero in empty strata
    def _pct(num, den):
        return (num / den * 100) if den > 0 else 0.0

    # =========================================================================
    # TABLE 1: OVERVIEW
    # =========================================================================
    ot_p = results['on_topic_only']['overall_perfect']
    ot_u = results['on_topic_only']['overall_uncertain']
    ot_c = results['on_topic_only']['overall_contradiction']
    off_p = results['off_topic_only']['overall_perfect']
    off_u = results['off_topic_only']['overall_uncertain']
    off_c = results['off_topic_only']['overall_contradiction']
    all_p = results['all_papers']['overall_perfect']
    all_u = results['all_papers']['overall_uncertain']
    all_c = results['all_papers']['overall_contradiction']

    table1 = f"""
\\begin{{table*}}[t]
\\centering
\\caption{{3-Run Agreement Analysis Overview. Percentage is shown first; count of classification decisions for each set is in the (parentheses).}}
\\label{{tab:agreement_overview}}
\\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
\\hline
\\textbf{{Overview}} & \\textbf{{On-topic ({on_topic_n:,} samples)}} & \\textbf{{Off-topic ({off_topic_n:,} samples)}} & \\textbf{{All papers ({all_papers_n:,} samples)}} \\\\
\\hline
\\textbf{{Perfect (YYY/NNN/UUU)}} & {_pct(ot_p, on_topic_n):.2f}\\% ({ot_p:,}) & {_pct(off_p, off_topic_n):.2f}\\% ({off_p:,}) & {_pct(all_p, all_papers_n):.2f}\\% ({all_p:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_perfect_ci_lower']:.2f}\\%, {results['all_papers']['overall_perfect_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Uncertain (no Y+N)}} & {_pct(ot_u, on_topic_n):.2f}\\% ({ot_u:,}) & {_pct(off_u, off_topic_n):.2f}\\% ({off_u:,}) & {_pct(all_u, all_papers_n):.2f}\\% ({all_u:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_uncertain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Contradictions (Y+N present)}} & {_pct(ot_c, on_topic_n):.2f}\\% ({ot_c:,}) & {_pct(off_c, off_topic_n):.2f}\\% ({off_c:,}) & {_pct(all_c, all_papers_n):.2f}\\% ({all_c:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_contradiction_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_contradiction_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_contradiction_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_contradiction_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_contradiction_ci_lower']:.2f}\\%, {results['all_papers']['overall_contradiction_ci_upper']:.2f}\\%]}} \\\\
\\hline
\\end{{tabular*}}
\\end{{table*}}
"""
    tables.append(("Overview", table1))

    # =========================================================================
    # TABLE 2: UNCERTAINTY BREAKDOWN
    # =========================================================================
    ot_ubc = results['on_topic_only']['overall_uncertain_biased_certain']
    ot_ubu = results['on_topic_only']['overall_uncertain_biased_uncertain']
    off_ubc = results['off_topic_only']['overall_uncertain_biased_certain']
    off_ubu = results['off_topic_only']['overall_uncertain_biased_uncertain']
    all_ubc = results['all_papers']['overall_uncertain_biased_certain']
    all_ubu = results['all_papers']['overall_uncertain_biased_uncertain']

    table2 = f"""
\\begin{{table*}}[t]
\\centering
\\caption{{Uncertainty Types Breakdown. Percentage is shown first; count of classification decisions for each set is in the (parentheses).}}
\\label{{tab:uncertainty}}
\\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
\\hline
\\textbf{{Uncertainty Type}} & \\textbf{{On-topic ({on_topic_n:,} samples)}} & \\textbf{{Off-topic ({off_topic_n:,} samples)}} & \\textbf{{All papers ({all_papers_n:,} samples)}} \\\\
\\hline
\\textbf{{Biased Certain (YYU/NNU)}} & {_pct(ot_ubc, on_topic_n):.2f}\\% ({ot_ubc:,}) & {_pct(off_ubc, off_topic_n):.2f}\\% ({off_ubc:,}) & {_pct(all_ubc, all_papers_n):.2f}\\% ({all_ubc:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Biased Uncertain (YUU/NUU)}} & {_pct(ot_ubu, on_topic_n):.2f}\\% ({ot_ubu:,}) & {_pct(off_ubu, off_topic_n):.2f}\\% ({off_ubu:,}) & {_pct(all_ubu, all_papers_n):.2f}\\% ({all_ubu:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} \\\\
\\hline
\\end{{tabular*}}
\\end{{table*}}
"""
    tables.append(("Uncertainty", table2))

    # =========================================================================
    # TABLE 3: CONTRADICTIONS BREAKDOWN
    # =========================================================================
    ot_cby = results['on_topic_only']['overall_contradiction_biased_yes']
    ot_cbn = results['on_topic_only']['overall_contradiction_biased_no']
    ot_cch = results['on_topic_only']['overall_contradiction_chaotic']
    off_cby = results['off_topic_only']['overall_contradiction_biased_yes']
    off_cbn = results['off_topic_only']['overall_contradiction_biased_no']
    off_cch = results['off_topic_only']['overall_contradiction_chaotic']
    all_cby = results['all_papers']['overall_contradiction_biased_yes']
    all_cbn = results['all_papers']['overall_contradiction_biased_no']
    all_cch = results['all_papers']['overall_contradiction_chaotic']

    ot_cby_ci = wilson_score_interval(ot_cby, on_topic_n)
    ot_cbn_ci = wilson_score_interval(ot_cbn, on_topic_n)
    ot_cch_ci = wilson_score_interval(ot_cch, on_topic_n)
    off_cby_ci = wilson_score_interval(off_cby, off_topic_n)
    off_cbn_ci = wilson_score_interval(off_cbn, off_topic_n)
    off_cch_ci = wilson_score_interval(off_cch, off_topic_n)
    all_cby_ci = wilson_score_interval(all_cby, all_papers_n)
    all_cbn_ci = wilson_score_interval(all_cbn, all_papers_n)
    all_cch_ci = wilson_score_interval(all_cch, all_papers_n)

    table3 = f"""
\\begin{{table*}}[t]
\\centering
\\caption{{Contradiction Types Breakdown. Percentage is shown first; count of classification decisions for each set is in the (parentheses).}}
\\label{{tab:contradictions}}
\\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
\\hline
\\textbf{{Contradiction Type}} & \\textbf{{On-topic ({on_topic_n:,} samples)}} & \\textbf{{Off-topic ({off_topic_n:,} samples)}} & \\textbf{{All papers ({all_papers_n:,} samples)}} \\\\
\\hline
\\textbf{{Biased Yes (YYN)}} & {_pct(ot_cby, on_topic_n):.2f}\\% ({ot_cby:,}) & {_pct(off_cby, off_topic_n):.2f}\\% ({off_cby:,}) & {_pct(all_cby, all_papers_n):.2f}\\% ({all_cby:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cby_ci[0]:.2f}\\%, {ot_cby_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cby_ci[0]:.2f}\\%, {off_cby_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cby_ci[0]:.2f}\\%, {all_cby_ci[1]:.2f}\\%]}} \\\\[6pt]
\\textbf{{Biased No (YNN)}} & {_pct(ot_cbn, on_topic_n):.2f}\\% ({ot_cbn:,}) & {_pct(off_cbn, off_topic_n):.2f}\\% ({off_cbn:,}) & {_pct(all_cbn, all_papers_n):.2f}\\% ({all_cbn:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cbn_ci[0]:.2f}\\%, {ot_cbn_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cbn_ci[0]:.2f}\\%, {off_cbn_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cbn_ci[0]:.2f}\\%, {all_cbn_ci[1]:.2f}\\%]}} \\\\[6pt]
\\textbf{{Chaotic (YNU)}} & {_pct(ot_cch, on_topic_n):.2f}\\% ({ot_cch:,}) & {_pct(off_cch, off_topic_n):.2f}\\% ({off_cch:,}) & {_pct(all_cch, all_papers_n):.2f}\\% ({all_cch:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cch_ci[0]:.2f}\\%, {ot_cch_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cch_ci[0]:.2f}\\%, {off_cch_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cch_ci[0]:.2f}\\%, {all_cch_ci[1]:.2f}\\%]}} \\\\
\\hline
\\end{{tabular*}}
\\end{{table*}}
"""
    tables.append(("Contradictions", table3))

    # =========================================================================
    # TABLE 4: BY RELEVANCE SCORE (ON-TOPIC ONLY)
    # =========================================================================
    relevance_keys = [
        ("2--3", "on_topic_relevance_Low_2_3"),
        ("4--5", "on_topic_relevance_Medium_4_5"),
        ("6--7", "on_topic_relevance_High_6_7"),
        ("8--10", "on_topic_relevance_Very_High_8_10")
    ]

    bin_data = []
    for col_label, key in relevance_keys:
        s = results.get(key)
        if s and s['n_observations'] > 0:
            n = s['n_observations']
            p_pct, p_cnt = s['overall_perfect_pct'], s['overall_perfect']
            u_pct, u_cnt = s['overall_uncertain_pct'], s['overall_uncertain']
            c_pct, c_cnt = s['overall_contradiction_pct'], s['overall_contradiction']
            bin_data.append({
                'p': f"{p_pct:.2f}\\% ({p_cnt:,})",
                'p_ci': wilson_score_interval(p_cnt, n),
                'u': f"{u_pct:.2f}\\% ({u_cnt:,})",
                'u_ci': wilson_score_interval(u_cnt, n),
                'c': f"{c_pct:.2f}\\% ({c_cnt:,})",
                'c_ci': wilson_score_interval(c_cnt, n)
            })
        else:
            bin_data.append({
                'p': '--', 'p_ci': (0.0, 0.0),
                'u': '--', 'u_ci': (0.0, 0.0),
                'c': '--', 'c_ci': (0.0, 0.0)
            })

    table4 = """
\\begin{table*}[t]
\\centering
\\caption{Agreement by Relevance Score (On-Topic Papers Only). Percentage is shown first; count of classification decisions is in the (parentheses).}
\\label{tab:by_relevance}
\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lcccc@{}}
\\hline
\\textbf{Relevance Score} & \\textbf{Low (2--3)} & \\textbf{Medium (4--5)} & \\textbf{High (6--7)} & \\textbf{Very High (8--10)} \\\\
\\hline
"""
    table4 += "\\textbf{Perfect} "
    for d in bin_data:
        table4 += f"& {d['p']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data:
        table4 += f"& \\textit{{\\footnotesize [{d['p_ci'][0]:.2f}\\%, {d['p_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\[6pt]\n"

    table4 += "\\textbf{Uncertain} "
    for d in bin_data:
        table4 += f"& {d['u']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data:
        table4 += f"& \\textit{{\\footnotesize [{d['u_ci'][0]:.2f}\\%, {d['u_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\[6pt]\n"

    table4 += "\\textbf{Contradiction} "
    for d in bin_data:
        table4 += f"& {d['c']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data:
        table4 += f"& \\textit{{\\footnotesize [{d['c_ci'][0]:.2f}\\%, {d['c_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\\n"

    table4 += """\\hline
\\end{tabular*}
\\end{table*}
"""
    tables.append(("By Relevance", table4))

    # =========================================================================
    # TABLE 5: BY CATEGORY (ON-TOPIC ONLY) — now driven by domain config
    # =========================================================================
    on_topic = results['on_topic_only']
    field_results = on_topic['field_results']

    if not field_results.empty:
        table5_rows = []
        for idx, (cat_name, cat_fields) in enumerate(categories):
            cat_df = field_results[field_results['field'].isin(cat_fields)]
            if cat_df.empty:
                continue

            cat_n_papers = len(cat_fields) * on_topic['n_papers']
            cat_perfect_count = int(cat_df['perfect'].sum())
            cat_uncertain_count = int(cat_df['uncertain'].sum())
            cat_contra_count = int(cat_df['contradiction'].sum())

            cat_perfect = (cat_perfect_count / cat_n_papers * 100) if cat_n_papers else 0
            cat_uncertain = (cat_uncertain_count / cat_n_papers * 100) if cat_n_papers else 0
            cat_contra = (cat_contra_count / cat_n_papers * 100) if cat_n_papers else 0

            most_contra = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
            contra_field = escape_latex_underscores(most_contra['field'])

            escaped_cat = escape_latex_underscores(cat_name)
            table5_rows.append(f"\\textbf{{{escaped_cat}}} & & & \\\\")

            table5_rows.append(
                f"\\textbf{{\\quad Overall ({cat_n_papers:,} samples)}} "
                f"& {cat_perfect_count:,} ({cat_perfect:.2f}\\%) "
                f"& {cat_uncertain_count:,} ({cat_uncertain:.2f}\\%) "
                f"& {cat_contra_count:,} ({cat_contra:.2f}\\%) \\\\")
            table5_rows.append(
                f"\\quad \\textit{{\\footnotesize 95\\% CI}} "
                f"& \\textit{{\\footnotesize [{wilson_score_interval(cat_perfect_count, cat_n_papers)[0]:.2f}\\%, "
                f"{wilson_score_interval(cat_perfect_count, cat_n_papers)[1]:.2f}\\%]}} "
                f"& \\textit{{\\footnotesize [{wilson_score_interval(cat_uncertain_count, cat_n_papers)[0]:.2f}\\%, "
                f"{wilson_score_interval(cat_uncertain_count, cat_n_papers)[1]:.2f}\\%]}} "
                f"& \\textit{{\\footnotesize [{wilson_score_interval(cat_contra_count, cat_n_papers)[0]:.2f}\\%, "
                f"{wilson_score_interval(cat_contra_count, cat_n_papers)[1]:.2f}\\%]}} \\\\[6pt]")

            table5_rows.append(
                f"\\textbf{{\\quad Most contradictory: "
                f"\\texttt{{{contra_field}}} "
                f"({most_contra['n_papers']:,} samples)}} "
                f"& {most_contra['perfect']:,} ({most_contra['perfect_pct']:.2f}\\%) "
                f"& {most_contra['uncertain']:,} ({most_contra['uncertain_pct']:.2f}\\%) "
                f"& {most_contra['contradiction']:,} ({most_contra['contradiction_pct']:.2f}\\%) \\\\")
            table5_rows.append(
                f"\\quad \\textit{{\\footnotesize 95\\% CI}} "
                f"& \\textit{{\\footnotesize [{most_contra['perfect_ci_lower']:.2f}\\%, "
                f"{most_contra['perfect_ci_upper']:.2f}\\%]}} "
                f"& \\textit{{\\footnotesize [{most_contra['uncertain_ci_lower']:.2f}\\%, "
                f"{most_contra['uncertain_ci_upper']:.2f}\\%]}} "
                f"& \\textit{{\\footnotesize [{most_contra['contradiction_ci_lower']:.2f}\\%, "
                f"{most_contra['contradiction_ci_upper']:.2f}\\%]}} \\\\")

            if idx < len(categories) - 1:
                table5_rows.append("\\midrule")

        rendered_field_count = sum(len(cf) for _, cf in categories)
        caption_text = (
            f"Agreement by Category (On-Topic Papers Only) -- "
            f"Total classification decisions: {on_topic['n_observations']:,} "
            f"({on_topic['n_papers']:,} papers $\\times$ "
            f"{rendered_field_count:,} fields).")

        table5 = f"""
\\begin{{table*}}[t]
\\centering
\\caption{{{caption_text}}}
\\label{{tab:by_category}}
\\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
\\hline
& \\textbf{{Perfect}} & \\textbf{{Uncertain}} & \\textbf{{Contradiction}} \\\\
\\hline
{chr(10).join(table5_rows)}
\\hline
\\end{{tabular*}}
\\end{{table*}}
"""
        tables.append(("By Category", table5))

    # =========================================================================
    # WRITE ALL TABLES
    # =========================================================================
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("% 3-Run Agreement Analysis Tables\n")
        f.write("% Generated for Elsevier two-column template\n")
        f.write("% Requires: booktabs package\n")
        for table_name, table_content in tables:
            f.write(f"% ===== {table_name} =====\n")
            f.write(table_content)
            f.write("\n")
    print(f"  LaTeX tables saved to: {output_path}")


# ============================================================================
# OUTPUT  (field groupings now dynamic)
# ============================================================================

def print_summary(results: Dict,
                  categories: List[Tuple[str, List[str]]]):
    """Print human-readable summary with confidence intervals."""
    print("\n" + "=" * 90)
    print("3-RUN AGREEMENT ANALYSIS - SUMMARY")
    print("(Simple logic: Perfect/Uncertain/Contradiction "
          "| Wilson 95% CIs where n≥100)")
    print("=" * 90)

    # --- Relevance strata ---
    print(f"\n🎯 BY RELEVANCE SCORE (On-Topic Papers Only)")
    print(f"   Testing: Does lower relevance correlate with "
          f"higher uncertainty/contradiction?")
    print("-" * 90)

    for low, high, label in RELEVANCE_BINS:
        key = (f"on_topic_relevance_"
               f"{label.replace(' ', '_')
                       .replace('(', '')
                       .replace(')', '')
                       .replace('-', '_')}")
        if key not in results or results[key]['n_papers'] == 0:
            continue

        s = results[key]
        n_obs = s['n_observations']

        print(f"\n   📊 {label} (n={s['n_papers']:,} papers × "
              f"{s['n_fields']:,} fields = {n_obs:,} obs)")
        print(f"      Raw responses: ✅Yes {s['overall_raw_yes_pct']:.1f}% "
              f"| ❌No {s['overall_raw_no_pct']:.1f}% "
              f"| ❓Unknown {s['overall_raw_unknown_pct']:.1f}%")

        perfect_fmt = format_with_ci(
            s['overall_perfect_pct'], s['overall_perfect'], n_obs)
        uncertain_fmt = format_with_ci(
            s['overall_uncertain_pct'], s['overall_uncertain'], n_obs)
        contradiction_fmt = format_with_ci(
            s['overall_contradiction_pct'], s['overall_contradiction'], n_obs)

        print(f"      ✅ Perfect:          {perfect_fmt}")
        print(f"      ⚠️  Uncertain:        {uncertain_fmt}")
        print(f"      ❌ Contradiction:    {contradiction_fmt}")

    # --- Main strata ---
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        if s['n_papers'] == 0:
            continue

        print(f"\n📊 {stratum_name.upper().replace('_', ' ')}")
        print(f"   Sample: {s['n_papers']:,} papers × "
              f"{s['n_fields']:,} fields = "
              f"{s['n_observations']:,} observations")

        print(f"\n   📊 Raw Response Distribution "
              f"(n={s['overall_raw_total']:,} individual classifications):")
        print(f"      ✅ Yes:     {s['overall_raw_yes']:,} "
              f"({s['overall_raw_yes_pct']:.2f}%)")
        print(f"      ❌ No:      {s['overall_raw_no']:,} "
              f"({s['overall_raw_no_pct']:.2f}%)")
        print(f"      ❓ Unknown: {s['overall_raw_unknown']:,} "
              f"({s['overall_raw_unknown_pct']:.2f}%)")

        perfect_fmt = format_with_ci(
            s['overall_perfect_pct'], s['overall_perfect'],
            s['n_observations'])
        uncertain_fmt = format_with_ci(
            s['overall_uncertain_pct'], s['overall_uncertain'],
            s['n_observations'])
        contradiction_fmt = format_with_ci(
            s['overall_contradiction_pct'], s['overall_contradiction'],
            s['n_observations'])

        print(f"\n   ✅ Perfect (YYY/NNN/UUU):          "
              f"{perfect_fmt:40s} Trust")

        uncertain_total = s['overall_uncertain']
        biased_certain = s.get('overall_uncertain_biased_certain', 0)
        biased_uncertain = s.get('overall_uncertain_biased_uncertain', 0)

        uncertain_fmt = format_with_ci(
            s['overall_uncertain_pct'], uncertain_total,
            s['n_observations'])
        biased_certain_fmt = format_with_ci(
            (biased_certain / s['n_observations'] * 100)
            if s['n_observations'] > 0 else 0,
            biased_certain, s['n_observations'])
        biased_uncertain_fmt = format_with_ci(
            (biased_uncertain / s['n_observations'] * 100)
            if s['n_observations'] > 0 else 0,
            biased_uncertain, s['n_observations'])

        print(f"   ⚠️  Uncertain (no Y↔N):             "
              f"{uncertain_fmt:40s} Acceptable")
        if uncertain_total > 0:
            print(f"      ├─ Biased→Certain   (YYU/NNU):  {biased_certain_fmt}")
            print(f"      └─ Biased→Uncertain (YUU/NUU):  {biased_uncertain_fmt}")

        contradiction_total = s['overall_contradiction']
        biased_yes = s.get('overall_contradiction_biased_yes', 0)
        biased_no = s.get('overall_contradiction_biased_no', 0)
        chaotic = s.get('overall_contradiction_chaotic', 0)

        biased_yes_fmt = format_with_ci(
            (biased_yes / s['n_observations'] * 100)
            if s['n_observations'] > 0 else 0,
            biased_yes, s['n_observations'])
        biased_no_fmt = format_with_ci(
            (biased_no / s['n_observations'] * 100)
            if s['n_observations'] > 0 else 0,
            biased_no, s['n_observations'])
        chaotic_fmt = format_with_ci(
            (chaotic / s['n_observations'] * 100)
            if s['n_observations'] > 0 else 0,
            chaotic, s['n_observations'])

        print(f"   ❌ Contradiction (Y+N present):    "
              f"{contradiction_fmt:39s} Review needed")
        if contradiction_total > 0:
            print(f"      ├─ Biased→Yes (YYN):            {biased_yes_fmt}")
            print(f"      ├─ Biased→No  (YNN):            {biased_no_fmt}")
            print(f"      └─ Chaotic    (YNU):            {chaotic_fmt}")

        print(f"\n   📊 Raw counts: {s['overall_perfect']:,} perfect "
              f"| {s['overall_uncertain']:,} uncertain "
              f"| {s['overall_contradiction']:,} contradictions")

        # Log entry validity
        log_stats = s.get('log_stats', {})
        if log_stats and log_stats.get('total_entries', 0) > 0:
            total_log = log_stats['total_entries']
            invalid_log = log_stats['invalid_entries']
            invalid_pct = log_stats['invalid_pct']
            invalid_fmt = format_with_ci(invalid_pct, invalid_log, total_log)
            print(f"\n   📋 LOG ENTRY VALIDITY:")
            print(f"   🗑️  Invalid entries (valid=False): "
                  f"{invalid_fmt:37s} Data generation issue")

            per_set = log_stats.get('per_set', {})
            if per_set:
                print(f"\n   └─ By set:")
                for set_name, set_stats in per_set.items():
                    set_invalid_fmt = format_with_ci(
                        set_stats['invalid_pct'],
                        set_stats['invalid'],
                        set_stats['total'])
                    print(f"      {set_name}: {set_invalid_fmt}")

        # Consensus / Runs stats
        consensus_stats = s.get('consensus_stats', {})
        if consensus_stats and consensus_stats.get('num_sets_analyzed', 0) > 0:
            print(f"\n   🔄 CONSENSUS / RUNS STATS:")
            print(f"      Total classification attempts: {consensus_stats['total_classify_runs']:,}")
            print(f"      Avg attempts per set:            {consensus_stats['avg_runs']:.2f}")
            print(f"      Max attempts for a single set:   {consensus_stats['max_runs']} "
                  f"(Paper: {consensus_stats['max_runs_paper']}, Set: {consensus_stats['max_runs_set']})")
            
        # By-category breakdown (on-topic only)
        if not s['field_results'].empty and stratum_name == 'on_topic_only':
            print(f"\n   📋 ALL FIELDS - Sorted by perfect agreement "
                  f"(best → worst):")

            for group_name, group_fields in categories:
                group_df = s['field_results'][
                    s['field_results']['field'].isin(group_fields)]
                if group_df.empty:
                    continue

                sorted_group = group_df.sort_values(
                    'perfect_pct', ascending=False)
                grp_perfect = sorted_group['perfect_pct'].mean()
                grp_uncertain = sorted_group['uncertain_pct'].mean()
                grp_contra = sorted_group['contradiction_pct'].mean()

                print(f"\n   🔹 {group_name}: "
                      f"Avg Perfect: {grp_perfect:5.2f}%  |  "
                      f"Avg Uncertain: {grp_uncertain:5.2f}%  |  "
                      f"Avg Contradiction: {grp_contra:5.2f}%")
                for _, row in sorted_group.iterrows():
                    bar_len = int(min(20, row['perfect_pct'] / 5))
                    bar = '█' * bar_len + '░' * (20 - bar_len)

                    contra_pct = row['contradiction_pct']
                    if contra_pct < 1.0:
                        status = '✅'
                    elif contra_pct < 5.0:
                        status = '⚠️ '
                    else:
                        status = '❌'

                    perfect_fmt = format_with_ci(
                        row['perfect_pct'], row['perfect'], row['n_papers'])
                    contra_fmt = format_with_ci(
                        row['contradiction_pct'], row['contradiction'],
                        row['n_papers'])
                    y_pct = row['raw_yes_pct']
                    n_pct = row['raw_no_pct']
                    u_pct = row['raw_unknown_pct']
                    print(f"      {row['field']:25s} {bar}  "
                          f"Perfect: {perfect_fmt:25s} | "
                          f"Contra: {contra_fmt} {status} | "
                          f"Y:{y_pct:5.1f}% N:{n_pct:5.1f}% "
                          f"U:{u_pct:5.1f}%")

    # --- Interpretation guide ---
    print(f"\n" + "=" * 90)
    print("INTERPRETATION GUIDE")
    print("=" * 90)

    on_topic = results['on_topic_only']
    n_obs = on_topic['n_observations']

    if n_obs >= MIN_N_FOR_CI:
        contra_ci = (on_topic['overall_contradiction_ci_lower'],
                     on_topic['overall_contradiction_ci_upper'])
        perfect_ci = (on_topic['overall_perfect_ci_lower'],
                      on_topic['overall_perfect_ci_upper'])

        print(f"""
On-Topic Results (n={n_obs:,} observations):
─────────────────────────────────────────────────────────────────────────
• Contradiction rate: {on_topic['overall_contradiction_pct']:.2f}%  95% CI [{contra_ci[0]:.2f}%, {contra_ci[1]:.2f}%]
  → {on_topic['overall_contradiction']:,} definitive errors requiring review
• Perfect agreement:  {on_topic['overall_perfect_pct']:.2f}%  95% CI [{perfect_ci[0]:.2f}%, {perfect_ci[1]:.2f}%]
  → Classifications you can trust
• Acceptable uncertainty: {on_topic['overall_uncertain_pct']:.2f}% ({on_topic['overall_uncertain']:,} obs)
  → Model hedging, not wrong

🔍 RELEVANCE CORRELATION CHECK:
─────────────────────────────────────────────────────────────────────────
• If contradiction % ↑ as relevance ↓ → Prompt may need relevance-aware tuning
• If unknown % ↑ as relevance ↓ → Model correctly hedges on ambiguous papers ✓
• If contradiction % is flat across bins → Issue is prompt-wide, not relevance-specific
""")
    else:
        print(f"""
On-Topic Results (n={n_obs:,} observations - CI not shown due to small sample):
─────────────────────────────────────────────────────────────────────────
• Contradiction rate: {on_topic['overall_contradiction_pct']:.2f}% ({on_topic['overall_contradiction']:,}/{n_obs:,})
• Perfect agreement:  {on_topic['overall_perfect_pct']:.2f}% ({on_topic['overall_perfect']:,}/{n_obs:,})

⚠️  Note: Sample size < {MIN_N_FOR_CI} - interpret with caution.
""")

    print("=" * 90 + "\n")


# ============================================================================
# MAIN
# ============================================================================

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
    domain_config = load_domain_config(config_path)
    boolean_fields = discover_boolean_fields(domain_config)
    categories = get_field_categories(domain_config, boolean_fields)

    if not args.quiet:
        print(f"Boolean fields ({len(boolean_fields)}): "
              f"{', '.join(boolean_fields)}")
        print(f"Categories: "
              f"{', '.join(name for name, _ in categories)}\n")

    # --- Load data ---
    if not args.quiet:
        print("Loading database into RAM...")
    papers = load_all_papers_from_single_db(args.db, boolean_fields)

    if not args.quiet:
        print(f"Loaded {len(papers)} papers with 3-run data. "
              f"Starting analysis...\n")

    # --- Analyse ---
    results = run_analysis(papers, boolean_fields, args.db)

    if not args.quiet:
        print_summary(results, categories)

    if not args.no_latex:
        latex_path = f"{args.output}_tables.tex"
        if not args.quiet:
            print("Generating LaTeX tables...")
        generate_latex_tables(results, latex_path, categories)

    if not args.quiet:
        print("Analysis complete.")

    return 0


if __name__ == '__main__':
    sys.exit(main())