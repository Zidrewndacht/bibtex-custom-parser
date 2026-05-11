
import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
import numpy as np
import pandas as pd
from scipy import stats

# ============================================================================
# CONFIGURATION
# ============================================================================
BOOLEAN_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    'tracks', 'holes', 'bare_pcb_other',
    'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
    'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic',
    'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
    'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
    'dl_other', 'hybrid', 'available_dataset'
]

JSON_FEATURE_FIELDS = {
    'tracks', 'holes', 'bare_pcb_other',
    'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
    'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic'
}

JSON_TECHNIQUE_FIELDS = {
    'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
    'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
    'dl_other', 'hybrid', 'available_dataset'
}

MIN_N_FOR_CI = 100
SET_LOG_COLUMNS = ['set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']

# NEW: Relevance bin configuration (0-10 integer scale)
RELEVANCE_BINS = [
    (0, 1, "Very Low (0-1)"),
    (2, 3, "Low (2-3)"),
    (4, 5, "Medium (4-5)"),
    (6, 7, "High (6-7)"),
    (8, 10, "Very High (8-10)")
]


# ============================================================================
# STATISTICAL HELPERS
# ============================================================================

def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
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


def format_with_ci(pct: float, count: int, total: int, min_n: int = MIN_N_FOR_CI) -> str:
    if total < min_n:
        return f"{pct:.2f}% ({count:,})"
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"   


def escape_latex_percent(text: str) -> str:
    return text.replace('%', '\\%')


def bin_relevance_score(relevance: Optional[int]) -> str:
    """
    Bin a relevance score (0-10) into one of 5 categories.
    Returns bin label string.
    """
    if relevance is None:
        return "Unknown"
    for low, high, label in RELEVANCE_BINS:
        if low <= relevance <= high:
            return label
    return "Unknown"


# ============================================================================
# DATA LOADING
# ============================================================================

def load_all_papers_from_single_db(db_path: str) -> Dict[int, Dict[int, Dict]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    papers = {}
    for row in rows:
        paper_id = row['id']
        row_dict = dict(row)
        
        sets_data = {}
        for set_num in [1, 2, 3]:
            prefix = f'set_{set_num}_last_llm_'
            
            try:
                features_str = row_dict.get(f'{prefix}features')
                features = json.loads(features_str) if features_str else {}
                if features is None: features = {}
            except (json.JSONDecodeError, TypeError):
                features = {}
            
            try:
                technique_str = row_dict.get(f'{prefix}technique')
                technique = json.loads(technique_str) if technique_str else {}
                if technique is None: technique = {}
            except (json.JSONDecodeError, TypeError):
                technique = {}
            
            encoded = {}
            
            # Direct boolean columns
            for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
                val = row_dict.get(f'{prefix}{field}')
                encoded[field] = 2 if val == 1 else (1 if val == 0 else 0)
            
            # Feature fields
            for field in JSON_FEATURE_FIELDS:
                val = features.get(field)
                encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
            # Technique fields
            for field in JSON_TECHNIQUE_FIELDS:
                val = technique.get(field)
                encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
            # NEW: Store relevance score for this set
            rel_val = row_dict.get(f'{prefix}relevance')
            encoded['_relevance'] = rel_val if isinstance(rel_val, int) else None
            
            sets_data[set_num] = encoded
        
        papers[paper_id] = sets_data
    
    return papers


def count_invalid_log_entries(db_path: str, paper_ids: List[int]) -> Dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    total_entries = 0
    invalid_entries = 0
    per_set_stats = {}
    
    for log_col in SET_LOG_COLUMNS:
        set_total = 0
        set_invalid = 0
        
        for paper_id in paper_ids:
            cursor.execute(f"SELECT {log_col} FROM papers WHERE id = ?", (paper_id,))
            row = cursor.fetchone()
            
            if row and row[log_col]:
                try:
                    log = json.loads(row[log_col])
                    for entry in log:
                        set_total += 1
                        if not entry.get('valid', True):
                            set_invalid += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        
        per_set_stats[log_col] = {
            'total': set_total,
            'invalid': set_invalid,
            'invalid_pct': (set_invalid / set_total * 100) if set_total > 0 else 0
        }
        
        total_entries += set_total
        invalid_entries += set_invalid
    
    conn.close()
    
    return {
        'total_entries': total_entries,
        'invalid_entries': invalid_entries,
        'invalid_pct': (invalid_entries / total_entries * 100) if total_entries > 0 else 0,
        'per_set': per_set_stats
    }


# ============================================================================
# 3-RUN AGREEMENT LOGIC
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
    

def analyze_field_agreement(papers: Dict[int, Dict[int, Dict]], field: str,
                           paper_ids: List[int]) -> Dict:
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


def analyze_stratum(papers: Dict[int, Dict[int, Dict]], paper_ids: List[int], 
                   fields: List[str], stratum_name: str, db_path: str) -> Dict:
    print(f"  Analyzing {stratum_name} ({len(paper_ids)} papers)...")
    
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
            'log_stats': {'total_entries': 0, 'invalid_entries': 0, 'invalid_pct': 0, 'per_set': {}}
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

    log_stats = count_invalid_log_entries(db_path, paper_ids)
    
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
        'log_stats': log_stats
    }


def run_analysis(papers: Dict[int, Dict[int, Dict]], fields: List[str], db_path: str) -> Dict:
    """Run stratified 3-run agreement analysis with relevance bins."""
    print(f"\nAnalyzing {len(fields)} fields across 3 runs...\n")
    
    all_paper_ids = list(papers.keys())
    
    # Stratify by off-topic status (from set 1)
    on_topic_ids = []
    off_topic_ids = []
    for paper_id in all_paper_ids:
        offtopic_val = papers[paper_id][1].get('is_offtopic', 0)
        if offtopic_val == 2:
            off_topic_ids.append(paper_id)
        else:
            on_topic_ids.append(paper_id)
    
    print(f"  Stratification: {len(on_topic_ids)} on-topic, {len(off_topic_ids)} off-topic")
    
    # NEW: Stratify on-topic papers by relevance bin (using set_1 relevance)
    relevance_strata = {}
    for low, high, label in RELEVANCE_BINS:
        relevance_strata[f"relevance_{label.replace(' ', '_').replace('(', '').replace(')', '')}"] = [
            pid for pid in on_topic_ids
            if papers[pid][1].get('_relevance') is not None 
            and low <= papers[pid][1]['_relevance'] <= high
        ]
    
    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids,
        **{f"on_topic_{label.replace(' ', '_').replace('(', '').replace(')', '')}": ids 
           for label, ids in [(lbl, relevance_strata[key]) for key, lbl in 
                             [(k, k.replace('relevance_', '').replace('_', ' ')) for k in relevance_strata.keys()]]}
    }
    
    # Cleaner relevance strata naming
    relevance_strata_clean = {}
    for low, high, label in RELEVANCE_BINS:
        key = f"relevance_{label.replace(' ', '_').replace('(', '').replace(')', '').replace('-', '_')}"
        relevance_strata_clean[key] = [
            pid for pid in on_topic_ids
            if papers[pid][1].get('_relevance') is not None 
            and low <= papers[pid][1]['_relevance'] <= high
        ]
    
    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids,
        **{f"on_topic_{key}": ids for key, ids in relevance_strata_clean.items()}
    }
    
    results = {}
    for stratum_name, stratum_ids in strata.items():
        results[stratum_name] = analyze_stratum(papers, stratum_ids, fields, stratum_name, db_path)
    
    return results

# ============================================================================
# LATEX TABLE GENERATION
# ============================================================================
def escape_latex_underscores(text: str) -> str:
    """Escape underscores for LaTeX."""
    return text.replace('_', '\\_')

def generate_latex_tables(results: Dict, output_path: str):
    """Generate LaTeX tables for Elsevier two-column template."""
    tables = []
    
    # Extract counts for headers
    on_topic_n = results['on_topic_only']['n_observations']
    off_topic_n = results['off_topic_only']['n_observations']
    all_papers_n = results['all_papers']['n_observations']
    
    # =========================================================================
    # TABLE 1: OVERVIEW (Perfect/Uncertain/Contradiction only)
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
\\textbf{{Perfect (YYY/NNN/UUU)}} & {ot_p / on_topic_n * 100:.2f}\\% ({ot_p:,}) & {off_p / off_topic_n * 100:.2f}\\% ({off_p:,}) & {all_p / all_papers_n * 100:.2f}\\% ({all_p:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_perfect_ci_lower']:.2f}\\%, {results['all_papers']['overall_perfect_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Uncertain (no Y+N)}} & {ot_u / on_topic_n * 100:.2f}\\% ({ot_u:,}) & {off_u / off_topic_n * 100:.2f}\\% ({off_u:,}) & {all_u / all_papers_n * 100:.2f}\\% ({all_u:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_uncertain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Contradictions (Y+N present)}} & {ot_c / on_topic_n * 100:.2f}\\% ({ot_c:,}) & {off_c / off_topic_n * 100:.2f}\\% ({off_c:,}) & {all_c / all_papers_n * 100:.2f}\\% ({all_c:,}) \\\\
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
\\textbf{{Biased Certain (YYU/NNU)}} & {ot_ubc / on_topic_n * 100:.2f}\\% ({ot_ubc:,}) & {off_ubc / off_topic_n * 100:.2f}\\% ({off_ubc:,}) & {all_ubc / all_papers_n * 100:.2f}\\% ({all_ubc:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{results['on_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['off_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{results['all_papers']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} \\\\[6pt]
\\textbf{{Biased Uncertain (YUU/NUU)}} & {ot_ubu / on_topic_n * 100:.2f}\\% ({ot_ubu:,}) & {off_ubu / off_topic_n * 100:.2f}\\% ({off_ubu:,}) & {all_ubu / all_papers_n * 100:.2f}\\% ({all_ubu:,}) \\\\
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

    # Precompute CIs
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
\\textbf{{Biased Yes (YYN)}} & {ot_cby / on_topic_n * 100:.2f}\\% ({ot_cby:,}) & {off_cby / off_topic_n * 100:.2f}\\% ({off_cby:,}) & {all_cby / all_papers_n * 100:.2f}\\% ({all_cby:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cby_ci[0]:.2f}\\%, {ot_cby_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cby_ci[0]:.2f}\\%, {off_cby_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cby_ci[0]:.2f}\\%, {all_cby_ci[1]:.2f}\\%]}} \\\\[6pt]
\\textbf{{Biased No (YNN)}} & {ot_cbn / on_topic_n * 100:.2f}\\% ({ot_cbn:,}) & {off_cbn / off_topic_n * 100:.2f}\\% ({off_cbn:,}) & {all_cbn / all_papers_n * 100:.2f}\\% ({all_cbn:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cbn_ci[0]:.2f}\\%, {ot_cbn_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cbn_ci[0]:.2f}\\%, {off_cbn_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cbn_ci[0]:.2f}\\%, {all_cbn_ci[1]:.2f}\\%]}} \\\\[6pt]
\\textbf{{Chaotic (YNU)}} & {ot_cch / on_topic_n * 100:.2f}\\% ({ot_cch:,}) & {off_cch / off_topic_n * 100:.2f}\\% ({off_cch:,}) & {all_cch / all_papers_n * 100:.2f}\\% ({all_cch:,}) \\\\
\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{ot_cch_ci[0]:.2f}\\%, {ot_cch_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{off_cch_ci[0]:.2f}\\%, {off_cch_ci[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{all_cch_ci[0]:.2f}\\%, {all_cch_ci[1]:.2f}\\%]}} \\\\
\\hline
\\end{{tabular*}}
\\end{{table*}}
"""
    tables.append(("Contradictions", table3))
    
    # =========================================================================
    # TABLE 4: BY RELEVANCE SCORE (ON-TOPIC ONLY) - BINS AS COLUMNS
    # =========================================================================
    # Exact keys as generated by run_analysis
    relevance_keys = [
        ("2--3", "on_topic_relevance_Low_2_3"),
        ("4--5", "on_topic_relevance_Medium_4_5"),
        ("6--7", "on_topic_relevance_High_6_7"),
        ("8--10", "on_topic_relevance_Very_High_8_10")
    ]
    
    # Collect data safely
    bin_data = []
    for col_label, key in relevance_keys:
        s = results.get(key)
        if s and s['n_observations'] > 0:
            n = s['n_observations']
            p_pct, p_cnt = s['overall_perfect_pct'], s['overall_perfect']
            u_pct, u_cnt = s['overall_uncertain_pct'], s['overall_uncertain']
            c_pct, c_cnt = s['overall_contradiction_pct'], s['overall_contradiction']
            bin_data.append({
                'p': f"{p_pct:.2f}\\% ({p_cnt:,})", 'p_ci': wilson_score_interval(p_cnt, n),
                'u': f"{u_pct:.2f}\\% ({u_cnt:,})", 'u_ci': wilson_score_interval(u_cnt, n),
                'c': f"{c_pct:.2f}\\% ({c_cnt:,})", 'c_ci': wilson_score_interval(c_cnt, n)
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
    # Perfect Row
    table4 += "\\textbf{Perfect} "
    for d in bin_data: table4 += f"& {d['p']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data: table4 += f"& \\textit{{\\footnotesize [{d['p_ci'][0]:.2f}\\%, {d['p_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\[6pt]\n"
    
    # Uncertain Row
    table4 += "\\textbf{Uncertain} "
    for d in bin_data: table4 += f"& {d['u']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data: table4 += f"& \\textit{{\\footnotesize [{d['u_ci'][0]:.2f}\\%, {d['u_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\[6pt]\n"
    
    # Contradiction Row
    table4 += "\\textbf{Contradiction} "
    for d in bin_data: table4 += f"& {d['c']} "
    table4 += "\\\\\n\\quad \\textit{{\\footnotesize 95\\% CI}} "
    for d in bin_data: table4 += f"& \\textit{{\\footnotesize [{d['c_ci'][0]:.2f}\\%, {d['c_ci'][1]:.2f}\\%]}} "
    table4 += "\\\\\n"
    
    table4 += """\\hline
\\end{tabular*}
\\end{table*}
"""
    tables.append(("By Relevance", table4))
    
    # =========================================================================
    # TABLE 5: BY CATEGORY (ON-TOPIC ONLY)
    # =========================================================================
    on_topic = results['on_topic_only']
    field_results = on_topic['field_results']
    
    if not field_results.empty:
        main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
        technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                          'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                          'dl_other', 'hybrid', 'available_dataset']
        feature_fields = [f for f in field_results['field'].unique() 
                         if f not in main_fields + ['is_offtopic'] + technique_fields]
        
        categories = [
            ('Main classification', main_fields),
            ('Features', feature_fields),
            ('Techniques', technique_fields)
        ]
        
        table5_rows = []
        for idx, (cat_name, cat_fields) in enumerate(categories):
            cat_df = field_results[field_results['field'].isin(cat_fields)]
            if cat_df.empty:
                continue
            
            cat_perfect = cat_df['perfect_pct'].mean()
            cat_uncertain = cat_df['uncertain_pct'].mean()
            cat_contra = cat_df['contradiction_pct'].mean()
            
            cat_n_papers = len(cat_fields) * on_topic['n_papers']
            cat_perfect_count = int(round(cat_perfect * cat_n_papers / 100))
            cat_uncertain_count = int(round(cat_uncertain * cat_n_papers / 100))
            cat_contra_count = int(round(cat_contra * cat_n_papers / 100))
            
            most_contra = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
            contra_field = escape_latex_underscores(most_contra['field'])
            
            # Category name row
            table5_rows.append(f"\\textbf{{{cat_name}}} & & & \\\\")
            
            # Overall row
            table5_rows.append(f"\\textbf{{\\quad Overall ({cat_n_papers:,} samples)}} & {cat_perfect_count:,} ({cat_perfect:.2f}\\%) & {cat_uncertain_count:,} ({cat_uncertain:.2f}\\%) & {cat_contra_count:,} ({cat_contra:.2f}\\%) \\\\")
            table5_rows.append(f"\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{wilson_score_interval(cat_perfect_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_perfect_count, cat_n_papers)[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{wilson_score_interval(cat_uncertain_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_uncertain_count, cat_n_papers)[1]:.2f}\\%]}} & \\textit{{\\footnotesize [{wilson_score_interval(cat_contra_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_contra_count, cat_n_papers)[1]:.2f}\\%]}} \\\\[6pt]")
            
            # Most contradictory row
            table5_rows.append(f"\\textbf{{\\quad Most contradictory: \\texttt{{{contra_field}}} ({most_contra['n_papers']:,} samples)}} & {most_contra['perfect']:,} ({most_contra['perfect_pct']:.2f}\\%) & {most_contra['uncertain']:,} ({most_contra['uncertain_pct']:.2f}\\%) & {most_contra['contradiction']:,} ({most_contra['contradiction_pct']:.2f}\\%) \\\\")
            table5_rows.append(f"\\quad \\textit{{\\footnotesize 95\\% CI}} & \\textit{{\\footnotesize [{most_contra['perfect_ci_lower']:.2f}\\%, {most_contra['perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{most_contra['uncertain_ci_lower']:.2f}\\%, {most_contra['uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\footnotesize [{most_contra['contradiction_ci_lower']:.2f}\\%, {most_contra['contradiction_ci_upper']:.2f}\\%]}} \\\\")
            
            if idx < len(categories) - 1:
                table5_rows.append("\\midrule")
        
        caption_text = f"Agreement by Category (On-Topic Papers Only) -- Total classification decisions: {on_topic['n_observations']:,} ({on_topic['n_papers']:,} papers $\\times$ {on_topic['n_fields']:,} fields)."
        
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
    # WRITE ALL TABLES TO SINGLE TEX FILE
    # =========================================================================
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("% 3-Run Agreement Analysis Tables\n")
        f.write("% Generated for Elsevier two-column template\n")
        f.write("% Requires: booktabs package for \\toprule, \\midrule, \\bottomrule\n")
        for table_name, table_content in tables:
            f.write(f"% ===== {table_name} =====\n")
            f.write(table_content)
            f.write("\n")
    print(f"  LaTeX tables saved to: {output_path}")
    
# ============================================================================
# OUTPUT
# ============================================================================

def print_summary(results: Dict):
    """Print human-readable summary with confidence intervals."""
    print("\n" + "="*90)
    print("3-RUN AGREEMENT ANALYSIS - SUMMARY")
    print("(Simple logic: Perfect/Uncertain/Contradiction | Wilson 95% CIs where n≥100)")
    print("="*90)
    
    # Print relevance-stratified results first (most actionable for prompt tuning)
    print(f"\n🎯 BY RELEVANCE SCORE (On-Topic Papers Only)")
    print(f"   Testing: Does lower relevance correlate with higher uncertainty/contradiction?")
    print("-"*90)
    
    for low, high, label in RELEVANCE_BINS:
        key = f"on_topic_relevance_{label.replace(' ', '_').replace('(', '').replace(')', '').replace('-', '_')}"
        if key not in results or results[key]['n_papers'] == 0:
            continue
        
        s = results[key]
        n_obs = s['n_observations']
        
        print(f"\n   📊 {label} (n={s['n_papers']:,} papers × {s['n_fields']:,} fields = {n_obs:,} obs)")
        
        # Raw response distribution
        print(f"      Raw responses: ✅Yes {s['overall_raw_yes_pct']:.1f}% | ❌No {s['overall_raw_no_pct']:.1f}% | ❓Unknown {s['overall_raw_unknown_pct']:.1f}%")
        
        perfect_fmt = format_with_ci(s['overall_perfect_pct'], s['overall_perfect'], n_obs)
        uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], s['overall_uncertain'], n_obs)
        contradiction_fmt = format_with_ci(s['overall_contradiction_pct'], s['overall_contradiction'], n_obs)
        
        print(f"      ✅ Perfect:          {perfect_fmt}")
        print(f"      ⚠️  Uncertain:        {uncertain_fmt}")
        print(f"      ❌ Contradiction:    {contradiction_fmt}")
        
    # Print other strata
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        if s['n_papers'] == 0:
            continue
        
        print(f"\n📊 {stratum_name.upper().replace('_', ' ')}")
        print(f"   Sample: {s['n_papers']:,} papers × {s['n_fields']:,} fields = {s['n_observations']:,} observations")
        
        print(f"\n   📊 Raw Response Distribution (n={s['overall_raw_total']:,} individual classifications):")
        print(f"      ✅ Yes:     {s['overall_raw_yes']:,} ({s['overall_raw_yes_pct']:.2f}%)")
        print(f"      ❌ No:      {s['overall_raw_no']:,} ({s['overall_raw_no_pct']:.2f}%)")
        print(f"      ❓ Unknown: {s['overall_raw_unknown']:,} ({s['overall_raw_unknown_pct']:.2f}%)")
        
        perfect_fmt = format_with_ci(s['overall_perfect_pct'], s['overall_perfect'], s['n_observations'])
        uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], s['overall_uncertain'], s['n_observations'])
        contradiction_fmt = format_with_ci(s['overall_contradiction_pct'], s['overall_contradiction'], s['n_observations'])
        
        print(f"\n   ✅ Perfect (YYY/NNN/UUU):          {perfect_fmt:40s} Trust")
        
        uncertain_total = s['overall_uncertain']
        biased_certain = s.get('overall_uncertain_biased_certain', 0)
        biased_uncertain = s.get('overall_uncertain_biased_uncertain', 0)

        uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], uncertain_total, s['n_observations'])
        biased_certain_fmt = format_with_ci(
            (biased_certain / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
            biased_certain, s['n_observations']
        )
        biased_uncertain_fmt = format_with_ci(
            (biased_uncertain / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
            biased_uncertain, s['n_observations']
        )

        print(f"   ⚠️  Uncertain (no Y↔N):             {uncertain_fmt:40s} Acceptable")
        if uncertain_total > 0:
            print(f"      ├─ Biased→Certain   (YYU/NNU):  {biased_certain_fmt}")
            print(f"      └─ Biased→Uncertain (YUU/NUU):  {biased_uncertain_fmt}")
            
        contradiction_total = s['overall_contradiction']
        biased_yes = s.get('overall_contradiction_biased_yes', 0)
        biased_no = s.get('overall_contradiction_biased_no', 0)
        chaotic = s.get('overall_contradiction_chaotic', 0)

        biased_yes_fmt = format_with_ci(
            (biased_yes / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
            biased_yes, s['n_observations']
        )
        biased_no_fmt = format_with_ci(
            (biased_no / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
            biased_no, s['n_observations']
        )
        chaotic_fmt = format_with_ci(
            (chaotic / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
            chaotic, s['n_observations']
        )

        print(f"   ❌ Contradiction (Y+N present):    {contradiction_fmt:39s} Review needed")
        if contradiction_total > 0:
            print(f"      ├─ Biased→Yes (YYN):            {biased_yes_fmt}")
            print(f"      ├─ Biased→No  (YNN):            {biased_no_fmt}")
            print(f"      └─ Chaotic    (YNU):            {chaotic_fmt}")

        print(f"\n   📊 Raw counts: {s['overall_perfect']:,} perfect | {s['overall_uncertain']:,} uncertain | {s['overall_contradiction']:,} contradictions")
        
        # Log entry validity
        log_stats = s.get('log_stats', {})
        if log_stats and log_stats.get('total_entries', 0) > 0:
            print(f"\n   📋 LOG ENTRY VALIDITY:")
            total_log = log_stats['total_entries']
            invalid_log = log_stats['invalid_entries']
            invalid_pct = log_stats['invalid_pct']
            invalid_fmt = format_with_ci(invalid_pct, invalid_log, total_log)
            print(f"   🗑️  Invalid entries (valid=False): {invalid_fmt:37s} Data generation issue")
            
            per_set = log_stats.get('per_set', {})
            if per_set:
                print(f"\n   └─ By set:")
                for set_name, set_stats in per_set.items():
                    set_invalid_fmt = format_with_ci(
                        set_stats['invalid_pct'],
                        set_stats['invalid'],
                        set_stats['total']
                    )
                    print(f"      {set_name}: {set_invalid_fmt}")
        
        # By category breakdown
        if not s['field_results'].empty and stratum_name == 'on_topic_only':
            print(f"\n   📋 ALL FIELDS - Sorted by perfect agreement (best → worst):")
            
            GENERAL_FIELDS = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
            FEATURE_FIELDS = [
                'tracks', 'holes', 'bare_pcb_other',
                'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
                'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic'
            ]
            TECHNIQUE_FIELDS = [
                'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                'dl_other', 'hybrid', 'available_dataset'
            ]
            
            groups = [
                ('🔹 General / Main Classification', GENERAL_FIELDS),
                ('🔹 Features (PCB/Solder/PCBA)', FEATURE_FIELDS),
                ('🔹 Techniques / Methods', TECHNIQUE_FIELDS)
            ]
            
            for group_name, group_fields in groups:
                group_df = s['field_results'][s['field_results']['field'].isin(group_fields)]
                if group_df.empty:
                    continue
                
                sorted_group = group_df.sort_values('perfect_pct', ascending=False)
                grp_perfect = sorted_group['perfect_pct'].mean()
                grp_uncertain = sorted_group['uncertain_pct'].mean()
                grp_contra = sorted_group['contradiction_pct'].mean()
                
                print(f"\n   {group_name}: Avg Perfect: {grp_perfect:5.2f}%  |  Avg Uncertain: {grp_uncertain:5.2f}%  |  Avg Contradiction: {grp_contra:5.2f}%")
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
                    
                    perfect_fmt = format_with_ci(row['perfect_pct'], row['perfect'], row['n_papers'])
                    contra_fmt = format_with_ci(row['contradiction_pct'], row['contradiction'], row['n_papers'])
                    y_pct = row['raw_yes_pct']
                    n_pct = row['raw_no_pct']
                    u_pct = row['raw_unknown_pct']
                    print(f"      {row['field']:25s} {bar}  Perfect: {perfect_fmt:25s} | Contra: {contra_fmt} {status} | Y:{y_pct:5.1f}% N:{n_pct:5.1f}% U:{u_pct:5.1f}%")
    
    # Interpretation guide
    print(f"\n" + "="*90)
    print("INTERPRETATION GUIDE")
    print("="*90)
    
    on_topic = results['on_topic_only']
    n_obs = on_topic['n_observations']
    
    if n_obs >= MIN_N_FOR_CI:
        contra_ci = (on_topic['overall_contradiction_ci_lower'], on_topic['overall_contradiction_ci_upper'])
        perfect_ci = (on_topic['overall_perfect_ci_lower'], on_topic['overall_perfect_ci_upper'])
        
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
    
    print("="*90 + "\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='3-run agreement analysis for ResearchParca v1.2+')
    parser.add_argument('--db', required=True, help='Path to single database with 3-run format')
    parser.add_argument('-o', '--output', default='agreement_3run_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    parser.add_argument('--no-latex', action='store_true', help='Skip LaTeX table generation')
    args = parser.parse_args()
    
    if not Path(args.db).exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    
    if not args.quiet:
        print(f"ResearchParca 3-Run Agreement Analysis (Single DB Format + Wilson CIs)")
        print(f"Database: {args.db}")
    
    if not args.quiet:
        print(f"\nLoading database into RAM...")
    papers = load_all_papers_from_single_db(args.db)
    
    if not args.quiet:
        print(f"Loaded {len(papers)} papers with 3-run data. Starting analysis...\n")
    
    results = run_analysis(papers, BOOLEAN_FIELDS, args.db)
    
    if not args.quiet:
        print_summary(results)
    
    if not args.no_latex:
        latex_path = f"{args.output}_tables.tex"
        if not args.quiet:
            print(f"\nGenerating LaTeX tables...")
        generate_latex_tables(results, latex_path)
    
    if not args.quiet:
        print("Analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())










# import argparse
# import sqlite3
# import json
# import sys
# from pathlib import Path
# from typing import List, Dict, Tuple, Optional
# from collections import Counter
# import numpy as np
# import pandas as pd
# from scipy import stats  # For Wilson interval z-value

# # ============================================================================
# # CONFIGURATION
# # ============================================================================
# BOOLEAN_FIELDS = [
#     # Main classification fields
#     'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    
#     # Feature fields (13 boolean)
#     'tracks', 'holes', 'bare_pcb_other',
#     'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
#     'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic',
    
#     # Technique fields (9 boolean)
#     'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
#     'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
#     'dl_other', 'hybrid', 'available_dataset'
# ]

# JSON_FEATURE_FIELDS = {
#     'tracks', 'holes', 'bare_pcb_other',
#     'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
#     'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic'
# }

# JSON_TECHNIQUE_FIELDS = {
#     'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
#     'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
#     'dl_other', 'hybrid', 'available_dataset'
# }

# # Relevance score configuration
# RELEVANCE_COLUMN = 'Relevance'  # Column name in papers table
# RELEVANCE_BINS = [
#     ('high_relevance', 0.75, 1.0),    # [min, max] inclusive
#     ('medium_relevance', 0.50, 0.74),
#     ('low_relevance', 0.0, 0.49),
# ]
# RELEVANCE_MIN_PAPERS = 20  # Skip bins with fewer papers than this

# # Minimum sample size to display confidence intervals (below this, show counts only)
# MIN_N_FOR_CI = 100

# # Log columns to check for invalid entries
# SET_LOG_COLUMNS = ['set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']


# # ============================================================================
# # STATISTICAL HELPERS
# # ============================================================================

# def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
#     """
#     Calculate Wilson score interval for a proportion.
#     More accurate than Wald interval, especially for small n or extreme proportions.
#     """
#     if n == 0:
#         return 0.0, 100.0
    
#     z = stats.norm.ppf((1 + confidence) / 2)
#     p_hat = successes / n
    
#     denominator = 1 + z**2 / n
#     centre = (p_hat + z**2 / (2*n)) / denominator
#     margin = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*n)) / n) / denominator
    
#     lower = max(0, (centre - margin) * 100)
#     upper = min(100, (centre + margin) * 100)
#     return lower, upper


# def format_with_ci(pct: float, count: int, total: int, min_n: int = MIN_N_FOR_CI) -> str:
#     """Format percentage with optional confidence interval."""
#     if total < min_n:
#         return f"{pct:.2f}% ({count:,})"
#     lower, upper = wilson_score_interval(count, total)
#     return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"   

# def escape_latex_percent(text: str) -> str:
#     """Escape % characters for LaTeX."""
#     return text.replace('%', '\\%')


# # ============================================================================
# # DATA LOADING (UPDATED FOR SINGLE DB)
# # ============================================================================

# def load_all_papers_from_single_db(db_path: str) -> Dict[int, Dict[int, Dict]]:
#     """
#     Load ALL papers from a SINGLE database with 3-run format.
    
#     Returns:
#         Dict mapping paper_id -> {set_num: {field: encoded_value}}
#         where set_num is 1, 2, or 3
#     """
#     conn = sqlite3.connect(db_path)
#     conn.row_factory = sqlite3.Row
#     cursor = conn.cursor()
#     cursor.execute("SELECT * FROM papers ORDER BY id")
#     rows = cursor.fetchall()
#     conn.close()
    
#     papers = {}
#     for row in rows:
#         paper_id = row['id']
        
#         # Convert sqlite3.Row to dict for .get() access
#         row_dict = dict(row)
        
#         # Load data for each of the 3 sets
#         sets_data = {}
#         for set_num in [1, 2, 3]:
#             prefix = f'set_{set_num}_last_llm_'
            
#             # Parse JSON fields for this set
#             try:
#                 features_str = row_dict.get(f'{prefix}features')
#                 features = json.loads(features_str) if features_str else {}
#                 if features is None: features = {}  # <-- Catches the '"null"' JSON string case
#             except (json.JSONDecodeError, TypeError):
#                 features = {}
            
#             try:
#                 technique_str = row_dict.get(f'{prefix}technique')
#                 technique = json.loads(technique_str) if technique_str else {}
#                 if technique is None: technique = {}  # <-- Same for technique
#             except (json.JSONDecodeError, TypeError):
#                 technique = {}
            
#             # Encode: 2=Yes, 1=No, 0=Unknown
#             encoded = {}
            
#             # Direct boolean columns for this set
#             for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
#                 val = row_dict.get(f'{prefix}{field}')
#                 encoded[field] = 2 if val == 1 else (1 if val == 0 else 0)
            
#             # Feature fields for this set
#             for field in JSON_FEATURE_FIELDS:
#                 val = features.get(field)
#                 encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
#             # Technique fields for this set
#             for field in JSON_TECHNIQUE_FIELDS:
#                 val = technique.get(field)
#                 encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
#             sets_data[set_num] = encoded
        
#         papers[paper_id] = sets_data
    
#     return papers


# def count_invalid_log_entries(db_path: str, paper_ids: List[int]) -> Dict:
#     """
#     Count invalid log entries (valid=False) across all 3 set logs.
    
#     Returns:
#         Dict with total_entries, invalid_entries, invalid_pct, and per-set breakdown
#     """
#     conn = sqlite3.connect(db_path)
#     conn.row_factory = sqlite3.Row
#     cursor = conn.cursor()
    
#     total_entries = 0
#     invalid_entries = 0
#     per_set_stats = {}
    
#     for log_col in SET_LOG_COLUMNS:
#         set_total = 0
#         set_invalid = 0
        
#         for paper_id in paper_ids:
#             cursor.execute(f"SELECT {log_col} FROM papers WHERE id = ?", (paper_id,))
#             row = cursor.fetchone()
            
#             if row and row[log_col]:
#                 try:
#                     log = json.loads(row[log_col])
#                     for entry in log:
#                         set_total += 1
#                         if not entry.get('valid', True):
#                             set_invalid += 1
#                 except (json.JSONDecodeError, TypeError):
#                     pass
        
#         per_set_stats[log_col] = {
#             'total': set_total,
#             'invalid': set_invalid,
#             'invalid_pct': (set_invalid / set_total * 100) if set_total > 0 else 0
#         }
        
#         total_entries += set_total
#         invalid_entries += set_invalid
    
#     conn.close()
    
#     return {
#         'total_entries': total_entries,
#         'invalid_entries': invalid_entries,
#         'invalid_pct': (invalid_entries / total_entries * 100) if total_entries > 0 else 0,
#         'per_set': per_set_stats
#     }


# # ============================================================================
# # 3-RUN AGREEMENT LOGIC
# # ============================================================================
# def classify_3run_agreement(values: List[int]) -> str:
#     """
#     Classify agreement type for 3 runs.
#     Encoding: 2=Yes, 1=No, 0=Unknown
#     Returns:
#     'perfect' = All 3 identical (YYY/NNN/UUU)
#     'uncertain_biased_certain' = 2 same value, 1 unknown (YYU/NNU patterns)
#     'uncertain_biased_uncertain' = 1 value, 2 unknown (YUU/NUU patterns)
#     'contradiction_biased_yes' = 2 Yes, 1 No (Y Y N)
#     'contradiction_biased_no' = 1 Yes, 2 No (Y N N)
#     'contradiction_chaotic' = 1 Yes, 1 No, 1 Unknown (Y N U)
#     """
#     counts = Counter(values)
    
#     # Perfect: all 3 identical
#     if len(counts) == 1:
#         return 'perfect'
    
#     has_yes = counts.get(2, 0) > 0
#     has_no = counts.get(1, 0) > 0
    
#     # Contradiction: has both Yes and No
#     if has_yes and has_no:
#         yes_count = counts.get(2, 0)
#         no_count = counts.get(1, 0)
#         unknown_count = counts.get(0, 0)
        
#         if yes_count == 1 and no_count == 1 and unknown_count == 1:
#             return 'contradiction_chaotic'
#         elif yes_count == 2 and no_count == 1:
#             return 'contradiction_biased_yes'
#         elif yes_count == 1 and no_count == 2:
#             return 'contradiction_biased_no'
#         else:
#             return 'contradiction_chaotic'
    
#     # No Y-N conflict: uncertain subtypes
#     known_count = counts.get(2, 0) + counts.get(1, 0)
    
#     if known_count == 2:
#         return 'uncertain_biased_certain'
#     else:  # known_count == 1
#         return 'uncertain_biased_uncertain'
    
# def analyze_field_agreement(papers: Dict[int, Dict[int, Dict]], field: str,
#                            paper_ids: List[int]) -> Dict:
#     """Analyze agreement for a single field across 3 runs."""
#     perfect_count = 0
#     uncertain_biased_certain_count = 0
#     uncertain_biased_uncertain_count = 0
#     contradiction_biased_yes_count = 0
#     contradiction_biased_no_count = 0
#     contradiction_chaotic_count = 0
    
#     # NEW: Raw response counters
#     raw_yes = 0
#     raw_no = 0
#     raw_unknown = 0
    
#     for paper_id in paper_ids:
#         values = [papers[paper_id][set_num].get(field, 0) for set_num in [1, 2, 3]]
        
#         # Count raw responses across all 3 runs
#         raw_yes += values.count(2)
#         raw_no += values.count(1)
#         raw_unknown += values.count(0)
        
#         agreement = classify_3run_agreement(values)
        
#         if agreement == 'perfect':
#             perfect_count += 1
#         elif agreement == 'uncertain_biased_certain':
#             uncertain_biased_certain_count += 1
#         elif agreement == 'uncertain_biased_uncertain':
#             uncertain_biased_uncertain_count += 1
#         elif agreement == 'contradiction_biased_yes':
#             contradiction_biased_yes_count += 1
#         elif agreement == 'contradiction_biased_no':
#             contradiction_biased_no_count += 1
#         elif agreement == 'contradiction_chaotic':
#             contradiction_chaotic_count += 1
    
#     total = len(paper_ids)
#     raw_total = total * 3
    
#     # Calculate CIs for each metric
#     return {
#         'field': field,
#         'n_papers': total,
#         'n_observations': total,
        
#         # NEW: Raw distribution
#         'raw_total': raw_total,
#         'raw_yes': raw_yes,
#         'raw_yes_pct': (raw_yes / raw_total * 100) if raw_total > 0 else 0,
#         'raw_no': raw_no,
#         'raw_no_pct': (raw_no / raw_total * 100) if raw_total > 0 else 0,
#         'raw_unknown': raw_unknown,
#         'raw_unknown_pct': (raw_unknown / raw_total * 100) if raw_total > 0 else 0,
        
#         'perfect': perfect_count,
#         'perfect_pct': (perfect_count / total * 100) if total > 0 else 0,
#         'perfect_ci_lower': wilson_score_interval(perfect_count, total)[0],
#         'perfect_ci_upper': wilson_score_interval(perfect_count, total)[1],
        
#         # Uncertain breakdown (NEW)
#         'uncertain_biased_certain': uncertain_biased_certain_count,
#         'uncertain_biased_certain_pct': (uncertain_biased_certain_count / total * 100) if total > 0 else 0,
#         'uncertain_biased_certain_ci_lower': wilson_score_interval(uncertain_biased_certain_count, total)[0],
#         'uncertain_biased_certain_ci_upper': wilson_score_interval(uncertain_biased_certain_count, total)[1],
        
#         'uncertain_biased_uncertain': uncertain_biased_uncertain_count,
#         'uncertain_biased_uncertain_pct': (uncertain_biased_uncertain_count / total * 100) if total > 0 else 0,
#         'uncertain_biased_uncertain_ci_lower': wilson_score_interval(uncertain_biased_uncertain_count, total)[0],
#         'uncertain_biased_uncertain_ci_upper': wilson_score_interval(uncertain_biased_uncertain_count, total)[1],
        
#         # Total uncertain (for backward compatibility)
#         'uncertain': uncertain_biased_certain_count + uncertain_biased_uncertain_count,
#         'uncertain_pct': ((uncertain_biased_certain_count + uncertain_biased_uncertain_count) / total * 100) if total > 0 else 0,
#         'uncertain_ci_lower': wilson_score_interval(
#             uncertain_biased_certain_count + uncertain_biased_uncertain_count, total)[0],
#         'uncertain_ci_upper': wilson_score_interval(
#             uncertain_biased_certain_count + uncertain_biased_uncertain_count, total)[1],
        
#         # Contradiction breakdown (existing)
#         'contradiction_biased_yes': contradiction_biased_yes_count,
#         'contradiction_biased_yes_pct': (contradiction_biased_yes_count / total * 100) if total > 0 else 0,
#         'contradiction_biased_yes_ci_lower': wilson_score_interval(contradiction_biased_yes_count, total)[0],
#         'contradiction_biased_yes_ci_upper': wilson_score_interval(contradiction_biased_yes_count, total)[1],
        
#         'contradiction_biased_no': contradiction_biased_no_count,
#         'contradiction_biased_no_pct': (contradiction_biased_no_count / total * 100) if total > 0 else 0,
#         'contradiction_biased_no_ci_lower': wilson_score_interval(contradiction_biased_no_count, total)[0],
#         'contradiction_biased_no_ci_upper': wilson_score_interval(contradiction_biased_no_count, total)[1],
        
#         'contradiction_chaotic': contradiction_chaotic_count,
#         'contradiction_chaotic_pct': (contradiction_chaotic_count / total * 100) if total > 0 else 0,
#         'contradiction_chaotic_ci_lower': wilson_score_interval(contradiction_chaotic_count, total)[0],
#         'contradiction_chaotic_ci_upper': wilson_score_interval(contradiction_chaotic_count, total)[1],
        
#         # Total contradiction
#         'contradiction': contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count,
#         'contradiction_pct': ((contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count) / total * 100) if total > 0 else 0,
#         'contradiction_ci_lower': wilson_score_interval(
#             contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count, total)[0],
#         'contradiction_ci_upper': wilson_score_interval(
#             contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count, total)[1],
#     }

# def analyze_stratum(papers: Dict[int, Dict[int, Dict]], paper_ids: List[int], 
#                    fields: List[str], stratum_name: str, db_path: str) -> Dict:
#     """Run full agreement analysis on a stratum of papers."""
#     print(f"  Analyzing {stratum_name} ({len(paper_ids)} papers)...")
    
#     if len(paper_ids) == 0:
#         return {
#             'stratum': stratum_name,
#             'n_papers': 0,
#             'n_fields': len(fields),
#             'n_observations': 0,
#             'field_results': pd.DataFrame(),
#             'overall_perfect_pct': 0,
#             'overall_contradiction_pct': 0,
#             'overall_perfect_ci': (0, 100),
#             'overall_contradiction_ci': (0, 100),
#             # NEW: Raw distribution defaults
#             'overall_raw_yes': 0, 'overall_raw_yes_pct': 0,
#             'overall_raw_no': 0, 'overall_raw_no_pct': 0,
#             'overall_raw_unknown': 0, 'overall_raw_unknown_pct': 0,
#             'overall_raw_total': 0,
#             'log_stats': {
#                 'total_entries': 0,
#                 'invalid_entries': 0,
#                 'invalid_pct': 0,
#                 'per_set': {}
#             }
#         }
    
#     field_results = []
#     for field in fields:
#         result = analyze_field_agreement(papers, field, paper_ids)
#         field_results.append(result)
    
#     results_df = pd.DataFrame(field_results)
    
#     # Overall metrics (aggregate across all fields)
#     overall_perfect = results_df['perfect'].sum()
#     overall_uncertain = results_df['uncertain'].sum()
#     overall_contradiction = results_df['contradiction'].sum()
#     overall_contradiction_biased_yes = results_df['contradiction_biased_yes'].sum()
#     overall_contradiction_biased_no = results_df['contradiction_biased_no'].sum()
#     overall_contradiction_chaotic = results_df['contradiction_chaotic'].sum()
#     total_observations = len(paper_ids) * len(fields)
    
#     # Calculate overall CIs
#     overall_perfect_ci = wilson_score_interval(overall_perfect, total_observations)
#     overall_uncertain_ci = wilson_score_interval(overall_uncertain, total_observations)
#     overall_contradiction_ci = wilson_score_interval(overall_contradiction, total_observations)
#     # In analyze_stratum(), add these aggregations:
#     overall_uncertain_biased_certain = results_df['uncertain_biased_certain'].sum()
#     overall_uncertain_biased_uncertain = results_df['uncertain_biased_uncertain'].sum()
#     overall_uncertain = overall_uncertain_biased_certain + overall_uncertain_biased_uncertain

#     # Calculate CIs
#     overall_uncertain_biased_certain_ci = wilson_score_interval(overall_uncertain_biased_certain, total_observations)
#     overall_uncertain_biased_uncertain_ci = wilson_score_interval(overall_uncertain_biased_uncertain, total_observations)

#     # NEW: Aggregate raw counts across fields
#     overall_raw_yes = results_df['raw_yes'].sum()
#     overall_raw_no = results_df['raw_no'].sum()
#     overall_raw_unknown = results_df['raw_unknown'].sum()
#     overall_raw_total = results_df['raw_total'].sum()

#     # === NEW: Count invalid log entries ===
#     log_stats = count_invalid_log_entries(db_path, paper_ids)
    
#     return {
#         'stratum': stratum_name,
#         'n_papers': len(paper_ids),
#         'n_fields': len(fields),
#         'n_observations': total_observations,
#         'field_results': results_df,
#         'overall_perfect': overall_perfect,
#         'overall_perfect_pct': (overall_perfect / total_observations * 100) if total_observations > 0 else 0,
#         'overall_perfect_ci_lower': overall_perfect_ci[0],
#         'overall_perfect_ci_upper': overall_perfect_ci[1],
            
#         'overall_uncertain_biased_certain': overall_uncertain_biased_certain,
#         'overall_uncertain_biased_certain_pct': (overall_uncertain_biased_certain / total_observations * 100) if total_observations > 0 else 0,
#         'overall_uncertain_biased_certain_ci_lower': overall_uncertain_biased_certain_ci[0],
#         'overall_uncertain_biased_certain_ci_upper': overall_uncertain_biased_certain_ci[1],
        
#         'overall_uncertain_biased_uncertain': overall_uncertain_biased_uncertain,
#         'overall_uncertain_biased_uncertain_pct': (overall_uncertain_biased_uncertain / total_observations * 100) if total_observations > 0 else 0,
#         'overall_uncertain_biased_uncertain_ci_lower': overall_uncertain_biased_uncertain_ci[0],
#         'overall_uncertain_biased_uncertain_ci_upper': overall_uncertain_biased_uncertain_ci[1],
        
#         'overall_uncertain': overall_uncertain,
#         'overall_uncertain_pct': (overall_uncertain / total_observations * 100) if total_observations > 0 else 0,
#         'overall_uncertain_ci_lower': overall_uncertain_ci[0],
#         'overall_uncertain_ci_upper': overall_uncertain_ci[1],
#         'overall_contradiction': overall_contradiction,
#         'overall_contradiction_pct': (overall_contradiction / total_observations * 100) if total_observations > 0 else 0,
#         'overall_contradiction_ci_lower': overall_contradiction_ci[0],
#         'overall_contradiction_ci_upper': overall_contradiction_ci[1],
#         'overall_contradiction_biased_yes': overall_contradiction_biased_yes,
#         'overall_contradiction_biased_no': overall_contradiction_biased_no,
#         'overall_contradiction_chaotic': overall_contradiction_chaotic,
        
#         # NEW: Raw distribution aggregation
#         'overall_raw_yes': overall_raw_yes,
#         'overall_raw_yes_pct': (overall_raw_yes / overall_raw_total * 100) if overall_raw_total > 0 else 0,
#         'overall_raw_no': overall_raw_no,
#         'overall_raw_no_pct': (overall_raw_no / overall_raw_total * 100) if overall_raw_total > 0 else 0,
#         'overall_raw_unknown': overall_raw_unknown,
#         'overall_raw_unknown_pct': (overall_raw_unknown / overall_raw_total * 100) if overall_raw_total > 0 else 0,
#         'overall_raw_total': overall_raw_total,
        
#         'log_stats': log_stats
#     }

# # ============================================================================
# # CONFIGURATION (ADD THESE)
# # ============================================================================
# # ... existing config ...

# # Relevance score configuration
# RELEVANCE_COLUMN = 'relevance_score'  # Column name in papers table
# RELEVANCE_BINS = [
#     ('high_relevance', 0.75, 1.0),    # [min, max] inclusive
#     ('medium_relevance', 0.50, 0.74),
#     ('low_relevance', 0.0, 0.49),
# ]
# RELEVANCE_MIN_PAPERS = 20  # Skip bins with fewer papers than this

# # ============================================================================
# # DATA LOADING HELPERS (ADD THESE)
# # ============================================================================

# def load_relevance_scores(db_path: str, paper_ids: List[int]) -> Dict[int, Optional[float]]:
#     """
#     Load relevance scores for given paper IDs.
#     Returns dict mapping paper_id -> score (or None if missing/invalid).
#     """
#     conn = sqlite3.connect(db_path)
#     conn.row_factory = sqlite3.Row
#     cursor = conn.cursor()
    
#     scores = {}
#     placeholders = ','.join('?' * len(paper_ids))
#     cursor.execute(f"SELECT id, {RELEVANCE_COLUMN} FROM papers WHERE id IN ({placeholders})", paper_ids)
    
#     for row in cursor.fetchall():
#         paper_id = row['id']
#         score = row[RELEVANCE_COLUMN]
#         # Handle NULL, NaN, or out-of-range values
#         if score is None or (isinstance(score, float) and np.isnan(score)):
#             scores[paper_id] = None
#         else:
#             # Normalize to 0-1 if needed (assume 0-100 scale detected)
#             if isinstance(score, (int, float)) and score > 1.0:
#                 score = score / 100.0
#             scores[paper_id] = max(0.0, min(1.0, float(score)))
    
#     conn.close()
#     return scores


# def bin_papers_by_relevance(paper_ids: List[int], scores: Dict[int, Optional[float]]) -> Dict[str, List[int]]:
#     """
#     Bin papers into relevance categories based on configured thresholds.
#     Papers with None/invalid scores are excluded from relevance analysis.
#     """
#     bins = {bin_name: [] for bin_name, _, _ in RELEVANCE_BINS}
#     bins['unknown_relevance'] = []
    
#     for paper_id in paper_ids:
#         score = scores.get(paper_id)
#         if score is None:
#             bins['unknown_relevance'].append(paper_id)
#             continue
        
#         placed = False
#         for bin_name, min_score, max_score in RELEVANCE_BINS:
#             if min_score <= score <= max_score:
#                 bins[bin_name].append(paper_id)
#                 placed = True
#                 break
#         if not placed:
#             bins['unknown_relevance'].append(paper_id)
    
#     # Filter out bins with too few papers
#     return {k: v for k, v in bins.items() if len(v) >= RELEVANCE_MIN_PAPERS or k == 'unknown_relevance'}


# # ============================================================================
# # ANALYSIS (UPDATE run_analysis)
# # ============================================================================

# def run_analysis(papers: Dict[int, Dict[int, Dict]], fields: List[str], db_path: str) -> Dict:
#     """Run stratified 3-run agreement analysis."""
#     print(f"\nAnalyzing {len(fields)} fields across 3 runs...\n")
    
#     all_paper_ids = list(papers.keys())
    
#     # Stratify by off-topic status (from set 1)
#     on_topic_ids = []
#     off_topic_ids = []
#     for paper_id in all_paper_ids:
#         offtopic_val = papers[paper_id][1].get('is_offtopic', 0)
#         if offtopic_val == 2:  # Yes, off-topic
#             off_topic_ids.append(paper_id)
#         else:
#             on_topic_ids.append(paper_id)
    
#     print(f"  Stratification: {len(on_topic_ids)} on-topic, {len(off_topic_ids)} off-topic")
    
#     strata = {
#         'all_papers': all_paper_ids,
#         'on_topic_only': on_topic_ids,
#         'off_topic_only': off_topic_ids
#     }
    
#     # === NEW: Relevance-based stratification (on-topic only) ===
#     print(f"\n  Loading relevance scores for relevance stratification...")
#     relevance_scores = load_relevance_scores(db_path, on_topic_ids)
#     relevance_bins = bin_papers_by_relevance(on_topic_ids, relevance_scores)
    
#     for bin_name, bin_ids in relevance_bins.items():
#         if bin_name != 'unknown_relevance':
#             print(f"    {bin_name}: {len(bin_ids)} papers")
    
#     # Add relevance bins to strata (only if they have sufficient papers)
#     for bin_name, bin_ids in relevance_bins.items():
#         if len(bin_ids) >= RELEVANCE_MIN_PAPERS or bin_name == 'unknown_relevance':
#             strata[f'relevance_{bin_name}'] = bin_ids
    
#     results = {}
#     for stratum_name, stratum_ids in strata.items():
#         results[stratum_name] = analyze_stratum(papers, stratum_ids, fields, stratum_name, db_path)
    
#     return results
# # ============================================================================
# # LATEX TABLE GENERATION
# # ============================================================================
# def escape_latex_underscores(text: str) -> str:
#     """Escape underscores for LaTeX."""
#     return text.replace('_', '\\_')

# def generate_latex_tables(results: Dict, output_path: str):
#     """Generate LaTeX tables for Elsevier two-column template."""
#     tables = []
    
#     # Extract counts for headers
#     on_topic_n = results['on_topic_only']['n_observations']
#     off_topic_n = results['off_topic_only']['n_observations']
#     all_papers_n = results['all_papers']['n_observations']
    
#     # =========================================================================
#     # TABLE 1: OVERVIEW (Perfect/Uncertain/Contradiction only)
#     # =========================================================================
#     table1 = f"""
# \\begin{{table*}}[t]
# \\centering
# \\caption{{3-Run Agreement Analysis Overview. Count of classification decisions for each set is in the (parentheses). \\newline95\\% Wilson confidence intervals are in the \textit{{[italicized brackets]}}.}}
# \\label{{tab:agreement_overview}}
# \\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
# \\hline
# \\textbf{{Metric}} & \\textbf{{On-topic (n={on_topic_n:,})}} & \\textbf{{Off-topic (n={off_topic_n:,})}} & \\textbf{{All papers (n={all_papers_n:,})}} \\\\
# \\hline
# Paper count & {results['on_topic_only']['n_papers']:,} & {results['off_topic_only']['n_papers']:,} & {results['all_papers']['n_papers']:,} \\\\
# \\hline
# Perfect (YYY/NNN/UUU) & {results['on_topic_only']['overall_perfect']:,} ({results['on_topic_only']['overall_perfect_pct']:.2f}\\%) & {results['off_topic_only']['overall_perfect']:,} ({results['off_topic_only']['overall_perfect_pct']:.2f}\\%) & {results['all_papers']['overall_perfect']:,} ({results['all_papers']['overall_perfect_pct']:.2f}\\%) \\\\
# & \\textit{{\\small[{results['on_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['off_topic_only']['overall_perfect_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['all_papers']['overall_perfect_ci_lower']:.2f}\\%, {results['all_papers']['overall_perfect_ci_upper']:.2f}\\%]}} \\\\[6pt]
# Uncertain (no Y+N) & {results['on_topic_only']['overall_uncertain']:,} ({results['on_topic_only']['overall_uncertain_pct']:.2f}\\%) & {results['off_topic_only']['overall_uncertain']:,} ({results['off_topic_only']['overall_uncertain_pct']:.2f}\\%) & {results['all_papers']['overall_uncertain']:,} ({results['all_papers']['overall_uncertain_pct']:.2f}\\%) \\\\
# & \\textit{{\\small[{results['on_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['off_topic_only']['overall_uncertain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['all_papers']['overall_uncertain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_ci_upper']:.2f}\\%]}} \\\\[6pt]
# Contradictions (Y+N present) & {results['on_topic_only']['overall_contradiction']:,} ({results['on_topic_only']['overall_contradiction_pct']:.2f}\\%) & {results['off_topic_only']['overall_contradiction']:,} ({results['off_topic_only']['overall_contradiction_pct']:.2f}\\%) & {results['all_papers']['overall_contradiction']:,} ({results['all_papers']['overall_contradiction_pct']:.2f}\\%) \\\\
# & \\textit{{\\small[{results['on_topic_only']['overall_contradiction_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_contradiction_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['off_topic_only']['overall_contradiction_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_contradiction_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['all_papers']['overall_contradiction_ci_lower']:.2f}\\%, {results['all_papers']['overall_contradiction_ci_upper']:.2f}\\%]}} \\\\
# \\hline
# \\end{{tabular*}}
# \\end{{table*}}
# """
#     tables.append(("Overview", table1))
    
#     # =========================================================================
#     # TABLE 2: UNCERTAINTY BREAKDOWN (NEW - like contradictions table)
#     # =========================================================================
#     table2 = f"""
# \\begin{{table*}}[t]
# \\centering
# \\caption{{Uncertainty Types Breakdown. Count of classification decisions for each set is in the (parentheses). \\newline95\\% Wilson confidence intervals are in the \textit{{[italicized brackets]}}.}}
# \\label{{tab:uncertainty}}
# \\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
# \\hline
# \\textbf{{Type}} & \\textbf{{On-topic (n={on_topic_n:,})}} & \\textbf{{Off-topic (n={off_topic_n:,})}} & \\textbf{{All papers (n={all_papers_n:,})}} \\\\
# \\hline
# Biased Certain (YYU/NNU) & {results['on_topic_only']['overall_uncertain_biased_certain']:,} ({results['on_topic_only']['overall_uncertain_biased_certain_pct']:.2f}\\%) & {results['off_topic_only']['overall_uncertain_biased_certain']:,} ({results['off_topic_only']['overall_uncertain_biased_certain_pct']:.2f}\\%) & {results['all_papers']['overall_uncertain_biased_certain']:,} ({results['all_papers']['overall_uncertain_biased_certain_pct']:.2f}\\%) \\\\
# & \\textit{{\\small[{results['on_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['off_topic_only']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['all_papers']['overall_uncertain_biased_certain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_biased_certain_ci_upper']:.2f}\\%]}} \\\\[6pt]
# Biased Uncertain (YUU/NUU) & {results['on_topic_only']['overall_uncertain_biased_uncertain']:,} ({results['on_topic_only']['overall_uncertain_biased_uncertain_pct']:.2f}\\%) & {results['off_topic_only']['overall_uncertain_biased_uncertain']:,} ({results['off_topic_only']['overall_uncertain_biased_uncertain_pct']:.2f}\\%) & {results['all_papers']['overall_uncertain_biased_uncertain']:,} ({results['all_papers']['overall_uncertain_biased_uncertain_pct']:.2f}\\%) \\\\
# & \\textit{{\\small[{results['on_topic_only']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['on_topic_only']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['off_topic_only']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['off_topic_only']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{results['all_papers']['overall_uncertain_biased_uncertain_ci_lower']:.2f}\\%, {results['all_papers']['overall_uncertain_biased_uncertain_ci_upper']:.2f}\\%]}} \\\\
# \\hline
# \\end{{tabular*}}
# \\end{{table*}}
# """
#     tables.append(("Uncertainty", table2))
    
#     # =========================================================================
#     # TABLE 3: CONTRADICTIONS BREAKDOWN
#     # =========================================================================
#     table3 = f"""
# \\begin{{table*}}[t]
# \\centering
# \\caption{{Contradiction Types Breakdown. Count of classification decisions for each set is in the (parentheses). \\newline95\\% Wilson confidence intervals are in the \textit{{[italicized brackets]}}.}}
# \\label{{tab:contradictions}}
# \\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
# \\hline
# \\textbf{{Type}} & \\textbf{{On-topic (n={on_topic_n:,})}} & \\textbf{{Off-topic (n={off_topic_n:,})}} & \\textbf{{All papers (n={all_papers_n:,})}} \\\\
# \\hline
# Biased Yes (YYN) & {results['on_topic_only']['overall_contradiction_biased_yes']:,} ({results['on_topic_only']['overall_contradiction_biased_yes'] / on_topic_n * 100:.2f}\\%) & {results['off_topic_only']['overall_contradiction_biased_yes']:,} ({results['off_topic_only']['overall_contradiction_biased_yes'] / off_topic_n * 100:.2f}\\%) & {results['all_papers']['overall_contradiction_biased_yes']:,} ({results['all_papers']['overall_contradiction_biased_yes'] / all_papers_n * 100:.2f}\\%) \\\\
# & \\textit{{\\small[{wilson_score_interval(results['on_topic_only']['overall_contradiction_biased_yes'], on_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['on_topic_only']['overall_contradiction_biased_yes'], on_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['off_topic_only']['overall_contradiction_biased_yes'], off_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['off_topic_only']['overall_contradiction_biased_yes'], off_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['all_papers']['overall_contradiction_biased_yes'], all_papers_n)[0]:.2f}\\%, {wilson_score_interval(results['all_papers']['overall_contradiction_biased_yes'], all_papers_n)[1]:.2f}\\%]}} \\\\[6pt]
# Biased No (YNN) & {results['on_topic_only']['overall_contradiction_biased_no']:,} ({results['on_topic_only']['overall_contradiction_biased_no'] / on_topic_n * 100:.2f}\\%) & {results['off_topic_only']['overall_contradiction_biased_no']:,} ({results['off_topic_only']['overall_contradiction_biased_no'] / off_topic_n * 100:.2f}\\%) & {results['all_papers']['overall_contradiction_biased_no']:,} ({results['all_papers']['overall_contradiction_biased_no'] / all_papers_n * 100:.2f}\\%) \\\\
# & \\textit{{\\small[{wilson_score_interval(results['on_topic_only']['overall_contradiction_biased_no'], on_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['on_topic_only']['overall_contradiction_biased_no'], on_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['off_topic_only']['overall_contradiction_biased_no'], off_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['off_topic_only']['overall_contradiction_biased_no'], off_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['all_papers']['overall_contradiction_biased_no'], all_papers_n)[0]:.2f}\\%, {wilson_score_interval(results['all_papers']['overall_contradiction_biased_no'], all_papers_n)[1]:.2f}\\%]}} \\\\[6pt]
# Chaotic (YNU) & {results['on_topic_only']['overall_contradiction_chaotic']:,} ({results['on_topic_only']['overall_contradiction_chaotic'] / on_topic_n * 100:.2f}\\%) & {results['off_topic_only']['overall_contradiction_chaotic']:,} ({results['off_topic_only']['overall_contradiction_chaotic'] / off_topic_n * 100:.2f}\\%) & {results['all_papers']['overall_contradiction_chaotic']:,} ({results['all_papers']['overall_contradiction_chaotic'] / all_papers_n * 100:.2f}\\%) \\\\
# & \\textit{{\\small[{wilson_score_interval(results['on_topic_only']['overall_contradiction_chaotic'], on_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['on_topic_only']['overall_contradiction_chaotic'], on_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['off_topic_only']['overall_contradiction_chaotic'], off_topic_n)[0]:.2f}\\%, {wilson_score_interval(results['off_topic_only']['overall_contradiction_chaotic'], off_topic_n)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(results['all_papers']['overall_contradiction_chaotic'], all_papers_n)[0]:.2f}\\%, {wilson_score_interval(results['all_papers']['overall_contradiction_chaotic'], all_papers_n)[1]:.2f}\\%]}} \\\\
# \\hline
# \\end{{tabular*}}
# \\end{{table*}}
# """
#     tables.append(("Contradictions", table3))
#         # =========================================================================
#     # TABLE 4: BY CATEGORY (ON-TOPIC ONLY) - Format consistency only
#     # =========================================================================
#     on_topic = results['on_topic_only']
#     field_results = on_topic['field_results']
    
#     if not field_results.empty:
#         main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
#         technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
#                           'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
#                           'dl_other', 'hybrid', 'available_dataset']
#         feature_fields = [f for f in field_results['field'].unique() 
#                          if f not in main_fields + ['is_offtopic'] + technique_fields]
        
#         categories = [
#             ('Main classification', main_fields),
#             ('Features', feature_fields),
#             ('Techniques', technique_fields)
#         ]
        
#         table4_rows = []
#         for idx, (cat_name, cat_fields) in enumerate(categories):
#             cat_df = field_results[field_results['field'].isin(cat_fields)]
#             if cat_df.empty:
#                 continue
            
#             cat_perfect = cat_df['perfect_pct'].mean()
#             cat_uncertain = cat_df['uncertain_pct'].mean()
#             cat_contra = cat_df['contradiction_pct'].mean()
            
#             # Calculate counts for category averages
#             cat_n_papers = len(cat_fields) * on_topic['n_papers']
#             cat_perfect_count = int(round(cat_perfect * cat_n_papers / 100))
#             cat_uncertain_count = int(round(cat_uncertain * cat_n_papers / 100))
#             cat_contra_count = int(round(cat_contra * cat_n_papers / 100))
            
#             # Find notable fields
#             best = cat_df.loc[cat_df['perfect_pct'].idxmax()]
#             most_uncertain = cat_df.loc[cat_df['uncertain_pct'].idxmax()]
#             most_contra = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
            
#             # Escape underscores in field names for LaTeX
#             best_field = escape_latex_underscores(best['field'])
#             uncertain_field = escape_latex_underscores(most_uncertain['field'])
#             contra_field = escape_latex_underscores(most_contra['field'])
            
#             # Category name row
#             table4_rows.append(f"\\textbf{{{cat_name}}} & & & \\\\")
            
#             # Overall row with CI (Denominator moved to label)
#             table4_rows.append(f"\\quad Overall (n={cat_n_papers:,}) & {cat_perfect_count:,} ({cat_perfect:.2f}\\%) & {cat_uncertain_count:,} ({cat_uncertain:.2f}\\%) & {cat_contra_count:,} ({cat_contra:.2f}\\%) \\\\")
#             table4_rows.append(f"\\quad & \\textit{{\\small[{wilson_score_interval(cat_perfect_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_perfect_count, cat_n_papers)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(cat_uncertain_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_uncertain_count, cat_n_papers)[1]:.2f}\\%]}} & \\textit{{\\small[{wilson_score_interval(cat_contra_count, cat_n_papers)[0]:.2f}\\%, {wilson_score_interval(cat_contra_count, cat_n_papers)[1]:.2f}\\%]}} \\\\[6pt]")
            
#             # Best perfect row with CI - KEEP COMMENTED (Updated format for consistency)
#             table4_rows.append(f"%\\quad Best perfect: \\texttt{{{best_field}}} (n={best['n_papers']:,}) & {best['perfect']:,} ({best['perfect_pct']:.2f}\\%) & {best['uncertain']:,} ({best['uncertain_pct']:.2f}\\%) & {best['contradiction']:,} ({best['contradiction_pct']:.2f}\\%) \\\\")
#             table4_rows.append(f"%\\quad & \\textit{{\\small[{best['perfect_ci_lower']:.2f}\\%, {best['perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{best['uncertain_ci_lower']:.2f}\\%, {best['uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{best['contradiction_ci_lower']:.2f}\\%, {best['contradiction_ci_upper']:.2f}\\%]}} \\\\[6pt]")
            
#             # Most uncertain row with CI - KEEP COMMENTED (Updated format for consistency)
#             table4_rows.append(f"%\\quad Most uncertain: \\texttt{{{uncertain_field}}} (n={most_uncertain['n_papers']:,}) & {most_uncertain['perfect']:,} ({most_uncertain['perfect_pct']:.2f}\\%) & {most_uncertain['uncertain']:,} ({most_uncertain['uncertain_pct']:.2f}\\%) & {most_uncertain['contradiction']:,} ({most_uncertain['contradiction_pct']:.2f}\\%) \\\\")
#             table4_rows.append(f"%\\quad & \\textit{{\\small[{most_uncertain['perfect_ci_lower']:.2f}\\%, {most_uncertain['perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{most_uncertain['uncertain_ci_lower']:.2f}\\%, {most_uncertain['uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{most_uncertain['contradiction_ci_lower']:.2f}\\%, {most_uncertain['contradiction_ci_upper']:.2f}\\%]}} \\\\[6pt]")
            
#             # Most contradictory row with CI (Denominator moved to label)
#             table4_rows.append(f"\\quad Most contradictory: \\texttt{{{contra_field}}} (n={most_contra['n_papers']:,}) & {most_contra['perfect']:,} ({most_contra['perfect_pct']:.2f}\\%) & {most_contra['uncertain']:,} ({most_contra['uncertain_pct']:.2f}\\%) & {most_contra['contradiction']:,} ({most_contra['contradiction_pct']:.2f}\\%) \\\\")
#             table4_rows.append(f"\\quad & \\textit{{\\small[{most_contra['perfect_ci_lower']:.2f}\\%, {most_contra['perfect_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{most_contra['uncertain_ci_lower']:.2f}\\%, {most_contra['uncertain_ci_upper']:.2f}\\%]}} & \\textit{{\\small[{most_contra['contradiction_ci_lower']:.2f}\\%, {most_contra['contradiction_ci_upper']:.2f}\\%]}} \\\\")
            
#             # Add midrule between categories
#             if idx < len(categories) - 1:
#                 table4_rows.append("\\midrule")
        
#         caption_text = f"Agreement by Category (On-Topic Papers Only) -- Total classification decisions: {on_topic['n_observations']:,} ({on_topic['n_papers']:,} papers $\\times$ {on_topic['n_fields']:,} fields)."
        
#         table4 = f"""
# \\begin{{table*}}[t]
# \\centering
# \\caption{{{caption_text}}}
# \\label{{tab:by_category}}
# \\begin{{tabular*}}{{\\textwidth}}{{@{{\\extracolsep{{\\fill}}}}lccc@{{}}}}
# \\hline
# & \\textbf{{Perfect}} & \\textbf{{Uncertain}} & \\textbf{{Contradiction}} \\\\
# \\hline
# {chr(10).join(table4_rows)}
# \\hline
# \\end{{tabular*}}
# \\end{{table*}}
# """
#         tables.append(("By Category", table4))
    
#     # =========================================================================
#     # TABLE 5: LOG ENTRIES (SINGLE COLUMN, CI IN SAME ROW)
#     # =========================================================================
#     log_stats = results['on_topic_only'].get('log_stats', {})
#     if log_stats and log_stats.get('total_entries', 0) > 0:
#         ci_lower = wilson_score_interval(log_stats['invalid_entries'], log_stats['total_entries'])[0]
#         ci_upper = wilson_score_interval(log_stats['invalid_entries'], log_stats['total_entries'])[1]
#         table5 = f"""
# \\begin{{table}}[t]
# \\centering
# \\caption{{Log Entry Validity Statistics}}
# \\label{{tab:log_entries}}
# \\begin{{tabular*}}{{\\columnwidth}}{{@{{\\extracolsep{{\\fill}}}}lc@{{}}}}
# \\hline
# \\textbf{{Metric}} & \\textbf{{Value}} \\\\
# \\hline
# Total entries & {log_stats['total_entries']:,} \\\\
# Invalid entries (valid=False) & {log_stats['invalid_entries']:,} ({log_stats['invalid_pct']:.2f}\\%) \\textit{{\\small[{ci_lower:.2f}\\%, {ci_upper:.2f}\\%]}} \\\\
# \\hline
# \\end{{tabular*}}
# \\end{{table}}
# """
#         tables.append(("Log Entries", table5))
    
#     # =========================================================================
#     # WRITE ALL TABLES TO SINGLE TEX FILE
#     # =========================================================================
#     with open(output_path, 'w', encoding='utf-8') as f:
#         f.write("% 3-Run Agreement Analysis Tables\n")
#         f.write("% Generated for Elsevier two-column template\n")
#         f.write("% Requires: booktabs package for \\toprule, \\midrule, \\bottomrule\n")
#         for table_name, table_content in tables:
#             f.write(f"% ===== {table_name} =====\n")
#             f.write(table_content)
#             f.write("\n")
#     print(f"  LaTeX tables saved to: {output_path}")

# # ============================================================================
# # OUTPUT
# # ============================================================================

# def print_summary(results: Dict):
#     """Print human-readable summary with confidence intervals."""
#     print("\n" + "="*90)
#     print("3-RUN AGREEMENT ANALYSIS - SUMMARY")
#     print("(Simple logic: Perfect/Uncertain/Contradiction | Wilson 95% CIs where n≥100)")
#     print("="*90)
    
#     for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
#         s = results[stratum_name]
#         if s['n_papers'] == 0:
#             continue
        
#         print(f"\n📊 {stratum_name.upper().replace('_', ' ')}")
#         print(f"   Sample: {s['n_papers']:,} papers × {s['n_fields']:,} fields = {s['n_observations']:,} observations")
        
#         # NEW: Raw response distribution
#         print(f"\n   📊 Raw Response Distribution (n={s['overall_raw_total']:,} individual classifications):")
#         print(f"      ✅ Yes:     {s['overall_raw_yes']:,} ({s['overall_raw_yes_pct']:.2f}%)")
#         print(f"      ❌ No:      {s['overall_raw_no']:,} ({s['overall_raw_no_pct']:.2f}%)")
#         print(f"      ❓ Unknown: {s['overall_raw_unknown']:,} ({s['overall_raw_unknown_pct']:.2f}%)")
        
#         perfect_fmt = format_with_ci(s['overall_perfect_pct'], s['overall_perfect'], s['n_observations'])
#         uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], s['overall_uncertain'], s['n_observations'])
#         contradiction_fmt = format_with_ci(s['overall_contradiction_pct'], s['overall_contradiction'], s['n_observations'])
        
#         print(f"\n   ✅ Perfect (YYY/NNN/UUU):          {perfect_fmt:40s} Trust")
        
#         uncertain_total = s['overall_uncertain']
#         biased_certain = s.get('overall_uncertain_biased_certain', 0)
#         biased_uncertain = s.get('overall_uncertain_biased_uncertain', 0)

#         uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], uncertain_total, s['n_observations'])
#         biased_certain_fmt = format_with_ci(
#             (biased_certain / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
#             biased_certain, s['n_observations']
#         )
#         biased_uncertain_fmt = format_with_ci(
#             (biased_uncertain / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
#             biased_uncertain, s['n_observations']
#         )

#         print(f"   ⚠️  Uncertain (no Y↔N):             {uncertain_fmt:40s} Acceptable")
#         if uncertain_total > 0:
#             print(f"      ├─ Biased→Certain   (YYU/NNU):  {biased_certain_fmt}")
#             print(f"      └─ Biased→Uncertain (YUU/NUU):  {biased_uncertain_fmt}")
            
            
#         contradiction_total = s['overall_contradiction']
#         biased_yes = s.get('overall_contradiction_biased_yes', 0)
#         biased_no = s.get('overall_contradiction_biased_no', 0)
#         chaotic = s.get('overall_contradiction_chaotic', 0)

#         biased_yes_fmt = format_with_ci(
#             (biased_yes / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
#             biased_yes, s['n_observations']
#         )
#         biased_no_fmt = format_with_ci(
#             (biased_no / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
#             biased_no, s['n_observations']
#         )
#         chaotic_fmt = format_with_ci(
#             (chaotic / s['n_observations'] * 100) if s['n_observations'] > 0 else 0,
#             chaotic, s['n_observations']
#         )

#         print(f"   ❌ Contradiction (Y+N present):    {contradiction_fmt:39s} Review needed")
#         if contradiction_total > 0:  # Only show breakdown if there are contradictions
#             print(f"      ├─ Biased→Yes (YYN):            {biased_yes_fmt}")
#             print(f"      ├─ Biased→No  (YNN):            {biased_no_fmt}")
#             print(f"      └─ Chaotic    (YNU):            {chaotic_fmt}")

#         print(f"\n   📊 Raw counts: {s['overall_perfect']:,} perfect | {s['overall_uncertain']:,} uncertain | {s['overall_contradiction']:,} contradictions")
        
#         # === NEW: Invalid Log Entry Statistics ===
#         log_stats = s.get('log_stats', {})
#         if log_stats and log_stats.get('total_entries', 0) > 0:
#             print(f"\n   📋 LOG ENTRY VALIDITY:")
#             total_log = log_stats['total_entries']
#             invalid_log = log_stats['invalid_entries']
#             invalid_pct = log_stats['invalid_pct']
#             invalid_fmt = format_with_ci(invalid_pct, invalid_log, total_log)
#             print(f"   🗑️  Invalid entries (valid=False): {invalid_fmt:37s} Data generation issue")
            
#             # Per-set breakdown
#             per_set = log_stats.get('per_set', {})
#             if per_set:
#                 print(f"\n   └─ By set:")
#                 for set_name, set_stats in per_set.items():
#                     set_invalid_fmt = format_with_ci(
#                         set_stats['invalid_pct'],
#                         set_stats['invalid'],
#                         set_stats['total']
#                     )
#                     print(f"      {set_name}: {set_invalid_fmt}")
        
#         if not s['field_results'].empty:
#             print(f"\n   📋 BY CATEGORY:")
            
#             main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
#             technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
#                             'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
#                             'dl_other', 'hybrid', 'available_dataset']
            
#             for cat_name, cat_fields in [
#                 ('Main Classification', main_fields),
#                 ('Features', [f for f in s['field_results']['field'].unique() 
#                             if f not in main_fields + ['is_offtopic'] + technique_fields]),
#                 ('Techniques', technique_fields)
#             ]:
#                 cat_df = s['field_results'][s['field_results']['field'].isin(cat_fields)]
#                 if cat_df.empty:
#                     continue
                
#                 cat_perfect = cat_df['perfect_pct'].mean()
#                 cat_uncertain = cat_df['uncertain_pct'].mean()  # NEW: average uncertain
#                 cat_contra = cat_df['contradiction_pct'].mean()
                
#                 # Best field by perfect agreement, worst by contradiction
#                 best = cat_df.loc[cat_df['perfect_pct'].idxmax()]
#                 worst = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
                
#                 best_perfect_fmt = format_with_ci(best['perfect_pct'], best['perfect'], best['n_papers'])
#                 worst_contra_fmt = format_with_ci(worst['contradiction_pct'], worst['contradiction'], worst['n_papers'])
                
#                 print(f"   ┌─ {cat_name}:\n   ├─  Avg Perfect:                  {cat_perfect:5.2f}%\n   ├─  Avg Uncertain:                {cat_uncertain:5.2f}% \n   ├─  Avg Contradiction:            {cat_contra:5.2f}%")
#                 print(f"   ├─  Best:   {best['field']:20s} → {best_perfect_fmt:30s} \n   └─  Worst:   {worst['field']:20s} → {worst_contra_fmt}")

#         if stratum_name == 'on_topic_only' and not s['field_results'].empty:
#             print(f"\n   📋 ALL FIELDS - Sorted by perfect agreement (best → worst):")
            
#             GENERAL_FIELDS = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
#             FEATURE_FIELDS = [
#                 'tracks', 'holes', 'bare_pcb_other',
#                 'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
#                 'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic'
#             ]
#             TECHNIQUE_FIELDS = [
#                 'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
#                 'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
#                 'dl_other', 'hybrid', 'available_dataset'
#             ]
            
#             groups = [
#                 ('🔹 General / Main Classification', GENERAL_FIELDS),
#                 ('🔹 Features (PCB/Solder/PCBA)', FEATURE_FIELDS),
#                 ('🔹 Techniques / Methods', TECHNIQUE_FIELDS)
#             ]
            
#             for group_name, group_fields in groups:
#                 group_df = s['field_results'][s['field_results']['field'].isin(group_fields)]
#                 if group_df.empty:
#                     continue
                
#                 sorted_group = group_df.sort_values('perfect_pct', ascending=False)
                
#                 # Calculate group averages including uncertain
#                 grp_perfect = sorted_group['perfect_pct'].mean()
#                 grp_uncertain = sorted_group['uncertain_pct'].mean()  # NEW
#                 grp_contra = sorted_group['contradiction_pct'].mean()
                
#                 print(f"\n   {group_name}: Avg Perfect: {grp_perfect:5.2f}%  |  Avg Uncertain: {grp_uncertain:5.2f}%  |  Avg Contradiction: {grp_contra:5.2f}%")  # UPDATED
#                 for _, row in sorted_group.iterrows():
#                     bar_len = int(min(20, row['perfect_pct'] / 5))
#                     bar = '█' * bar_len + '░' * (20 - bar_len)
                    
#                     contra_pct = row['contradiction_pct']
#                     if contra_pct < 1.0:
#                         status = '✅'
#                     elif contra_pct < 5.0:
#                         status = '⚠️ '
#                     else:
#                         status = '❌'
                    
#                     perfect_fmt = format_with_ci(row['perfect_pct'], row['perfect'], row['n_papers'])
#                     contra_fmt = format_with_ci(row['contradiction_pct'], row['contradiction'], row['n_papers'])
                    
#                     # NEW: Append raw Y/N/U percentages to per-field output
#                     y_pct = row['raw_yes_pct']
#                     n_pct = row['raw_no_pct']
#                     u_pct = row['raw_unknown_pct']
#                     print(f"      {row['field']:25s} {bar}  Perfect: {perfect_fmt:25s} | Contra: {contra_fmt} {status} | Y:{y_pct:5.1f}% N:{n_pct:5.1f}% U:{u_pct:5.1f}%")

#             # === NEW: Relevance Score Breakdown ===
#     relevance_strata = {k: v for k, v in results.items() if k.startswith('relevance_')}
#     if relevance_strata:
#         print(f"\n📊 RELEVANCE SCORE BREAKDOWN (On-Topic Papers Only)")
#         print(f"   {'Relevance Bin':<20} {'Papers':>8} {'Perfect%':>10} {'Uncertain%':>12} {'Contradict%':>13}")
#         print(f"   {'-'*20} {'-'*8} {'-'*10} {'-'*12} {'-'*13}")
        
#         # Sort by relevance tier (high → low → unknown)
#         sort_order = ['relevance_high_relevance', 'relevance_medium_relevance', 
#                      'relevance_low_relevance', 'relevance_unknown_relevance']
        
#         for stratum_key in sort_order:
#             if stratum_key not in relevance_strata:
#                 continue
#             s = relevance_strata[stratum_key]
#             bin_name = stratum_key.replace('relevance_', '').replace('_', ' ').title()
            
#             perfect_ci = wilson_score_interval(s['overall_perfect'], s['n_observations'])
#             contra_ci = wilson_score_interval(s['overall_contradiction'], s['n_observations'])
            
#             print(f"   {bin_name:<20} {s['n_papers']:>8,} "
#                   f"{s['overall_perfect_pct']:>9.2f}% [{perfect_ci[0]:.1f}-{perfect_ci[1]:.1f}] "
#                   f"{s['overall_uncertain_pct']:>11.2f}% "
#                   f"{s['overall_contradiction_pct']:>12.2f}% [{contra_ci[0]:.1f}-{contra_ci[1]:.1f}]")
        
#         # Quick insight
#         high = relevance_strata.get('relevance_high_relevance')
#         low = relevance_strata.get('relevance_low_relevance')
#         if high and low and high['n_observations'] >= MIN_N_FOR_CI and low['n_observations'] >= MIN_N_FOR_CI:
#             high_contra = high['overall_contradiction_pct']
#             low_contra = low['overall_contradiction_pct']
#             diff = abs(high_contra - low_contra)
#             if diff > 5.0:
#                 direction = "worse" if low_contra > high_contra else "better"
#                 print(f"\n   ⚠️  Insight: Contradiction rate is {diff:.1f}pp {direction} on low-relevance papers")
#                 print(f"      → Consider prompt tuning or filtering for low-relevance inputs")

#     print(f"\n" + "="*90)
#     print("INTERPRETATION GUIDE")
#     print("="*90)
    
#     on_topic = results['on_topic_only']
#     n_obs = on_topic['n_observations']
    
#     if n_obs >= MIN_N_FOR_CI:
#         contra_ci = (on_topic['overall_contradiction_ci_lower'], on_topic['overall_contradiction_ci_upper'])
#         perfect_ci = (on_topic['overall_perfect_ci_lower'], on_topic['overall_perfect_ci_upper'])
        
#         print(f"""
# On-Topic Results (n={n_obs:,} observations):
# ─────────────────────────────────────────────────────────────────────────
# • Contradiction rate: {on_topic['overall_contradiction_pct']:.2f}%  95% CI [{contra_ci[0]:.2f}%, {contra_ci[1]:.2f}%]
#   → {on_topic['overall_contradiction']:,} definitive errors requiring review
# • Perfect agreement:  {on_topic['overall_perfect_pct']:.2f}%  95% CI [{perfect_ci[0]:.2f}%, {perfect_ci[1]:.2f}%]
#   → Classifications you can trust
# • Acceptable uncertainty: {on_topic['overall_uncertain_pct']:.2f}% ({on_topic['overall_uncertain']:,} obs)
#   → Model hedging, not wrong
  
# 📌 Why This Is Better Than Tri-State α:
# ─────────────────────────────────────────────────────────────────────────
# 1. No conflating "I don't know" with "I'm wrong"
# 2. Directly answers: "How many classifications need human review?"
# 3. Actionable thresholds: <5% = excellent, 5-10% = acceptable, >10% = concerning
# 4. Preserves the value of Unknown as a valid, honest response
# 5. Confidence intervals quantify uncertainty in the observed rates

# 📌 Actionable Thresholds (with statistical context):
# ─────────────────────────────────────────────────────────────────────────
# • < 5% contradictions:  ✅ Excellent - minimal review needed
#   (If CI upper bound <5%, you can be confident it's truly excellent)
# • 5-10% contradictions: ⚠️  Acceptable - review high-contradiction fields  
#   (If CI spans 5-10%, consider collecting more data for precision)
# • > 10% contradictions: ❌ Concerning - consider prompt engineering or
#                            manual review of affected fields
#   (If CI lower bound >10%, the problem is statistically confirmed)
# """)
        
#         # === NEW: Invalid Log Entry Interpretation ===
#         log_stats = on_topic.get('log_stats', {})
#         if log_stats and log_stats.get('total_entries', 0) > 0:
#             invalid_pct = log_stats['invalid_pct']
#             invalid_entries = log_stats['invalid_entries']
#             total_entries = log_stats['total_entries']
            
#             print(f"""• Invalid log entries:  {invalid_pct:.2f}% ({invalid_entries:,}/{total_entries:,})
#   → Entries marked valid=False due to malformed/missing data
#   → Check invalidate_bogus_log_entries.py for details
# ─────────────────────────────────────────────────────────────────────────
# """)
#     else:
#         print(f"""
# On-Topic Results (n={n_obs:,} observations - CI not shown due to small sample):
# ─────────────────────────────────────────────────────────────────────────
# • Contradiction rate: {on_topic['overall_contradiction_pct']:.2f}% ({on_topic['overall_contradiction']:,}/{n_obs:,})
# • Perfect agreement:  {on_topic['overall_perfect_pct']:.2f}% ({on_topic['overall_perfect']:,}/{n_obs:,})
# • Acceptable uncertainty: {on_topic['overall_uncertain_pct']:.2f}% ({on_topic['overall_uncertain']:,}/{n_obs:,})

# ⚠️  Note: Sample size < {MIN_N_FOR_CI} - confidence intervals not displayed.
#    Interpret percentages with caution; collect more data for reliable inference.
# ─────────────────────────────────────────────────────────────────────────
# """)

    
#     print("="*90 + "\n")


# # ============================================================================
# # MAIN
# # ============================================================================

# def main():
#     parser = argparse.ArgumentParser(description='3-run agreement analysis for ResearchParca v1.2+')
#     parser.add_argument('--db', required=True, help='Path to single database with 3-run format')
#     parser.add_argument('-o', '--output', default='agreement_3run_results', help='Output path prefix')
#     parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
#     parser.add_argument('--no-latex', action='store_true', help='Skip LaTeX table generation')
#     args = parser.parse_args()
    
#     if not Path(args.db).exists():
#         print(f"Error: Database not found: {args.db}", file=sys.stderr)
#         sys.exit(1)
    
#     if not args.quiet:
#         print(f"ResearchParca 3-Run Agreement Analysis (Single DB Format + Wilson CIs)")
#         print(f"Database: {args.db}")
    
#     if not args.quiet:
#         print(f"\nLoading database into RAM...")
#     papers = load_all_papers_from_single_db(args.db)
    
#     if not args.quiet:
#         print(f"Loaded {len(papers)} papers with 3-run data. Starting analysis...\n")
    
#     results = run_analysis(papers, BOOLEAN_FIELDS, args.db)
    
#     if not args.quiet:
#         print_summary(results)
    
#     if not args.no_latex:
#         latex_path = f"{args.output}_tables.tex"
#         if not args.quiet:
#             print(f"\nGenerating LaTeX tables...")
#         generate_latex_tables(results, latex_path)
    
#     if not args.quiet:
#         print("Analysis complete.")
    
#     return 0


# if __name__ == '__main__':
#     sys.exit(main())

