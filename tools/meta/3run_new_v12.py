#!/usr/bin/env python3
"""
consistency_3run_simple.py
==========================
3-run agreement analysis for ResearchParça v1.2+ using simple, interpretable logic.

Updated for SINGLE DATABASE format where all 3 runs are stored in set_1_*, set_2_*, set_3_* columns.
NOW INCLUDES: Invalid log entry statistics (entries marked with valid=False)

Agreement categories:
- ✅ Perfect: All 3 runs agree (YYY/NNN/UUU)
- ⚠️  Acceptable: No Yes↔No conflict, but not all identical (e.g., YYU, YUU)
- ❌ Contradiction: At least one Yes AND one No among the 3 runs (definitive error)

This directly answers: "How often does the model contradict itself on definitive claims?"

Usage:
    python consistency_3run_simple.py \
        --db data/db.sqlite \
        --output results.csv
"""

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
import numpy as np
import pandas as pd
from scipy import stats  # For Wilson interval z-value


# ============================================================================
# CONFIGURATION
# ============================================================================
BOOLEAN_FIELDS = [
    # Main classification fields
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    
    # Feature fields (13 boolean)
    'tracks', 'holes', 'bare_pcb_other',
    'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
    'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic',
    
    # Technique fields (9 boolean)
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

# Minimum sample size to display confidence intervals (below this, show counts only)
MIN_N_FOR_CI = 100

# Log columns to check for invalid entries
SET_LOG_COLUMNS = ['set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']


# ============================================================================
# STATISTICAL HELPERS
# ============================================================================

def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate Wilson score interval for a proportion.
    More accurate than Wald interval, especially for small n or extreme proportions.
    """
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
    """Format percentage with optional confidence interval."""
    if total < min_n:
        return f"{pct:.1f}% ({count:,}  /  {total:,})"
    
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.1f}% [{lower:.2f}%, {upper:.2f}%] ({count:,}/{total:,})"


# ============================================================================
# DATA LOADING (UPDATED FOR SINGLE DB)
# ============================================================================

def load_all_papers_from_single_db(db_path: str) -> Dict[int, Dict[int, Dict]]:
    """
    Load ALL papers from a SINGLE database with 3-run format.
    
    Returns:
        Dict mapping paper_id -> {set_num: {field: encoded_value}}
        where set_num is 1, 2, or 3
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    papers = {}
    for row in rows:
        paper_id = row['id']
        
        # Convert sqlite3.Row to dict for .get() access
        row_dict = dict(row)
        
        # Load data for each of the 3 sets
        sets_data = {}
        for set_num in [1, 2, 3]:
            prefix = f'set_{set_num}_last_llm_'
            
            # Parse JSON fields for this set
            try:
                features_str = row_dict.get(f'{prefix}features')
                features = json.loads(features_str) if features_str else {}
            except (json.JSONDecodeError, TypeError):
                features = {}
            
            try:
                technique_str = row_dict.get(f'{prefix}technique')
                technique = json.loads(technique_str) if technique_str else {}
            except (json.JSONDecodeError, TypeError):
                technique = {}
            
            # Encode: 2=Yes, 1=No, 0=Unknown
            encoded = {}
            
            # Direct boolean columns for this set
            for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
                val = row_dict.get(f'{prefix}{field}')
                encoded[field] = 2 if val == 1 else (1 if val == 0 else 0)
            
            # Feature fields for this set
            for field in JSON_FEATURE_FIELDS:
                val = features.get(field)
                encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
            # Technique fields for this set
            for field in JSON_TECHNIQUE_FIELDS:
                val = technique.get(field)
                encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            
            sets_data[set_num] = encoded
        
        papers[paper_id] = sets_data
    
    return papers


def count_invalid_log_entries(db_path: str, paper_ids: List[int]) -> Dict:
    """
    Count invalid log entries (valid=False) across all 3 set logs.
    
    Returns:
        Dict with total_entries, invalid_entries, invalid_pct, and per-set breakdown
    """
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
    """
    Classify agreement type for 3 runs.
    
    Encoding: 2=Yes, 1=No, 0=Unknown
    
    Returns:
        'perfect' = All 3 identical (YYY/NNN/UUU)
        'uncertain' = No Yes↔No conflict, but not all identical (YYU/YUU/NUU/etc.)
        'contradiction_biased_yes' = 2 Yes, 1 No (Y Y N) - systematic bias toward Yes
        'contradiction_biased_no' = 1 Yes, 2 No (Y N N) - systematic bias toward No  
        'contradiction_chaotic' = 1 Yes, 1 No, 1 Unknown (Y N U) - random/inconsistent
    """
    counts = Counter(values)
    
    if len(counts) == 1:
        return 'perfect'
    
    has_yes = counts.get(2, 0) > 0
    has_no = counts.get(1, 0) > 0
    has_unknown = counts.get(0, 0) > 0
    
    if has_yes and has_no:
        yes_count = counts.get(2, 0)
        no_count = counts.get(1, 0)
        unknown_count = counts.get(0, 0)
        
        # Chaotic: exactly 1 of each (Y, N, U)
        if yes_count == 1 and no_count == 1 and unknown_count == 1:
            return 'contradiction_chaotic'
        # Biased toward Yes: 2 Yes, 1 No
        elif yes_count == 2 and no_count == 1:
            return 'contradiction_biased_yes'
        # Biased toward No: 1 Yes, 2 No
        elif yes_count == 1 and no_count == 2:
            return 'contradiction_biased_no'
        # Fallback for other combos (shouldn't occur with 3 runs)
        else:
            return 'contradiction_chaotic'
    
    return 'uncertain'

def analyze_field_agreement(papers: Dict[int, Dict[int, Dict]], field: str, 
                           paper_ids: List[int]) -> Dict:
    """Analyze agreement for a single field across 3 runs."""
    perfect_count = 0
    uncertain_count = 0
    contradiction_biased_yes_count = 0
    contradiction_biased_no_count = 0
    contradiction_chaotic_count = 0
    
    for paper_id in paper_ids:
        values = [papers[paper_id][set_num].get(field, 0) for set_num in [1, 2, 3]]
        agreement = classify_3run_agreement(values)
        
        if agreement == 'perfect':
            perfect_count += 1
        elif agreement == 'uncertain':
            uncertain_count += 1
        elif agreement == 'contradiction_biased_yes':
            contradiction_biased_yes_count += 1
        elif agreement == 'contradiction_biased_no':
            contradiction_biased_no_count += 1
        elif agreement == 'contradiction_chaotic':
            contradiction_chaotic_count += 1
    
    total = len(paper_ids)
    
    # Calculate CIs for each metric
    return {
        'field': field,
        'n_papers': total,
        'n_observations': total,
        'perfect': perfect_count,
        'perfect_pct': (perfect_count / total * 100) if total > 0 else 0,
        'perfect_ci_lower': wilson_score_interval(perfect_count, total)[0],
        'perfect_ci_upper': wilson_score_interval(perfect_count, total)[1],
        'uncertain': uncertain_count,
        'uncertain_pct': (uncertain_count / total * 100) if total > 0 else 0,
        'uncertain_ci_lower': wilson_score_interval(uncertain_count, total)[0],
        'uncertain_ci_upper': wilson_score_interval(uncertain_count, total)[1],
        # NEW: Biased/Chaotic breakdown
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
        # Keep aggregate contradiction for backward compatibility
        'contradiction': contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count,
        'contradiction_pct': ((contradiction_biased_yes_count + contradiction_biased_no_count + contradiction_chaotic_count) / total * 100) if total > 0 else 0,
    }


def analyze_stratum(papers: Dict[int, Dict[int, Dict]], paper_ids: List[int], 
                   fields: List[str], stratum_name: str, db_path: str) -> Dict:
    """Run full agreement analysis on a stratum of papers."""
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
            'log_stats': {
                'total_entries': 0,
                'invalid_entries': 0,
                'invalid_pct': 0,
                'per_set': {}
            }
        }
    
    field_results = []
    for field in fields:
        result = analyze_field_agreement(papers, field, paper_ids)
        field_results.append(result)
    
    results_df = pd.DataFrame(field_results)
    
    # Overall metrics (aggregate across all fields)
    overall_perfect = results_df['perfect'].sum()
    overall_uncertain = results_df['uncertain'].sum()
    overall_contradiction = results_df['contradiction'].sum()
    overall_contradiction_biased_yes = results_df['contradiction_biased_yes'].sum()
    overall_contradiction_biased_no = results_df['contradiction_biased_no'].sum()
    overall_contradiction_chaotic = results_df['contradiction_chaotic'].sum()
    total_observations = len(paper_ids) * len(fields)
    
    # Calculate overall CIs
    overall_perfect_ci = wilson_score_interval(overall_perfect, total_observations)
    overall_uncertain_ci = wilson_score_interval(overall_uncertain, total_observations)
    overall_contradiction_ci = wilson_score_interval(overall_contradiction, total_observations)
    
    # === NEW: Count invalid log entries ===
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
        'log_stats': log_stats  # === NEW ===
    }


def run_analysis(papers: Dict[int, Dict[int, Dict]], fields: List[str], db_path: str) -> Dict:
    """Run stratified 3-run agreement analysis."""
    print(f"\nAnalyzing {len(fields)} fields across 3 runs...\n")
    
    all_paper_ids = list(papers.keys())
    
    # Stratify by off-topic status (from set 1)
    on_topic_ids = []
    off_topic_ids = []
    for paper_id in all_paper_ids:
        offtopic_val = papers[paper_id][1].get('is_offtopic', 0)
        if offtopic_val == 2:  # Yes, off-topic
            off_topic_ids.append(paper_id)
        else:
            on_topic_ids.append(paper_id)
    
    print(f"  Stratification: {len(on_topic_ids)} on-topic, {len(off_topic_ids)} off-topic")
    
    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids
    }
    
    results = {}
    for stratum_name, stratum_ids in strata.items():
        results[stratum_name] = analyze_stratum(papers, stratum_ids, fields, stratum_name, db_path)
    
    return results


# ============================================================================
# OUTPUT
# ============================================================================

def print_summary(results: Dict):
    """Print human-readable summary with confidence intervals."""
    print("\n" + "="*90)
    print("3-RUN AGREEMENT ANALYSIS - SUMMARY")
    print("(Simple logic: Perfect/Uncertain/Contradiction | Wilson 95% CIs where n≥100)")
    print("="*90)
    
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        if s['n_papers'] == 0:
            continue
        
        print(f"\n📊 {stratum_name.upper().replace('_', ' ')}")
        print(f"   Sample: {s['n_papers']:,} papers × {s['n_fields']:,} fields = {s['n_observations']:,} observations")
        
        perfect_fmt = format_with_ci(s['overall_perfect_pct'], s['overall_perfect'], s['n_observations'])
        uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], s['overall_uncertain'], s['n_observations'])
        contradiction_fmt = format_with_ci(s['overall_contradiction_pct'], s['overall_contradiction'], s['n_observations'])
        
        print(f"   ✅ Perfect (YYY/NNN/UUU):      {perfect_fmt:45s} Trust")
        print(f"   ⚠️  Uncertain (no Y↔N):         {uncertain_fmt:45s} Acceptable")
        # In print_summary(), replace the contradiction line with:
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

        print(f"   ❌ Contradiction (Y+N present): {contradiction_fmt:45s} Review needed")
        if contradiction_total > 0:  # Only show breakdown if there are contradictions
            print(f"      ├─ Biased→Yes (YYN): {biased_yes_fmt}")
            print(f"      ├─ Biased→No  (YNN): {biased_no_fmt}")
            print(f"      └─ Chaotic  (YNU): {chaotic_fmt}")

        print(f"\n   📊 Raw counts: {s['overall_perfect']:,} perfect | {s['overall_uncertain']:,} uncertain | {s['overall_contradiction']:,} contradictions")
        
        # === NEW: Invalid Log Entry Statistics ===
        log_stats = s.get('log_stats', {})
        if log_stats and log_stats.get('total_entries', 0) > 0:
            print(f"\n   📋 LOG ENTRY VALIDITY:")
            total_log = log_stats['total_entries']
            invalid_log = log_stats['invalid_entries']
            invalid_pct = log_stats['invalid_pct']
            invalid_fmt = format_with_ci(invalid_pct, invalid_log, total_log)
            print(f"   🗑️  Invalid entries (valid=False): {invalid_fmt:45s} Data quality issue")
            
            # Per-set breakdown
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
        
        if not s['field_results'].empty:
            print(f"\n   📋 BY CATEGORY:")
            
            main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
            technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                               'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                               'dl_other', 'hybrid', 'available_dataset']
            
            for cat_name, cat_fields in [
                ('Main Classification', main_fields),
                ('Features', [f for f in s['field_results']['field'].unique() 
                             if f not in main_fields + ['is_offtopic'] + technique_fields]),
                ('Techniques', technique_fields)
            ]:
                cat_df = s['field_results'][s['field_results']['field'].isin(cat_fields)]
                if cat_df.empty:
                    continue
                
                cat_perfect = cat_df['perfect_pct'].mean()
                cat_contra = cat_df['contradiction_pct'].mean()
                cat_n = cat_df['n_papers'].iloc[0] if len(cat_df) > 0 else 0
                worst = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
                
                worst_contra_fmt = format_with_ci(
                    worst['contradiction_pct'], 
                    worst['contradiction'], 
                    worst['n_papers']
                )
                
                print(f"   ┌─ {cat_name}:")
                print(f"   │  Sample: {cat_n:,} papers | Avg Perfect: {cat_perfect:.1f}%  |  Avg Contradiction: {cat_contra:.1f}%")
                print(f"   │  Worst field: {worst['field']} → {worst_contra_fmt}")
        
        if stratum_name == 'on_topic_only' and not s['field_results'].empty:
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
                
                print(f"\n   {group_name}:")
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
                    
                    print(f"      {row['field']:25s} {bar}  Perfect: {perfect_fmt:25s} | Contra: {contra_fmt} {status}")

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
• Contradiction rate: {on_topic['overall_contradiction_pct']:.1f}%  95% CI [{contra_ci[0]:.2f}%, {contra_ci[1]:.2f}%]
  → {on_topic['overall_contradiction']:,} definitive errors requiring review
• Perfect agreement:  {on_topic['overall_perfect_pct']:.1f}%  95% CI [{perfect_ci[0]:.2f}%, {perfect_ci[1]:.2f}%]
  → Classifications you can trust
• Acceptable uncertainty: {on_topic['overall_uncertain_pct']:.1f}% ({on_topic['overall_uncertain']:,} obs)
  → Model hedging, not wrong
""")
        
        # === NEW: Invalid Log Entry Interpretation ===
        log_stats = on_topic.get('log_stats', {})
        if log_stats and log_stats.get('total_entries', 0) > 0:
            invalid_pct = log_stats['invalid_pct']
            invalid_entries = log_stats['invalid_entries']
            total_entries = log_stats['total_entries']
            
            print(f"""• Invalid log entries:  {invalid_pct:.1f}% ({invalid_entries:,}/{total_entries:,})
  → Entries marked valid=False due to malformed/missing data
  → Check invalidate_bogus_log_entries.py for details
─────────────────────────────────────────────────────────────────────────
""")
    else:
        print(f"""
On-Topic Results (n={n_obs:,} observations - CI not shown due to small sample):
─────────────────────────────────────────────────────────────────────────
• Contradiction rate: {on_topic['overall_contradiction_pct']:.1f}% ({on_topic['overall_contradiction']:,}/{n_obs:,})
• Perfect agreement:  {on_topic['overall_perfect_pct']:.1f}% ({on_topic['overall_perfect']:,}/{n_obs:,})
• Acceptable uncertainty: {on_topic['overall_uncertain_pct']:.1f}% ({on_topic['overall_uncertain']:,}/{n_obs:,})

⚠️  Note: Sample size < {MIN_N_FOR_CI} - confidence intervals not displayed.
   Interpret percentages with caution; collect more data for reliable inference.
─────────────────────────────────────────────────────────────────────────
""")
    
    print("="*90 + "\n")


def save_results(results: Dict, output_path: str):
    """Save results to CSV and JSON with CI columns."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    for stratum_name, stratum_data in results.items():
        if stratum_data['n_papers'] == 0:
            continue
        
        # Save field results CSV
        field_csv = output.with_suffix(f'.{stratum_name}.agreement.csv')
        stratum_data['field_results'].to_csv(field_csv, index=False, float_format='%.4f')
        print(f"✓ Agreement results ({stratum_name}) saved to: {field_csv}")
        
        # === NEW: Save log stats to separate CSV ===
        log_stats = stratum_data.get('log_stats', {})
        if log_stats and log_stats.get('total_entries', 0) > 0:
            log_csv = output.with_suffix(f'.{stratum_name}.log_validity.csv')
            log_rows = []
            
            # Overall row
            log_rows.append({
                'scope': 'overall',
                'total_entries': log_stats['total_entries'],
                'invalid_entries': log_stats['invalid_entries'],
                'invalid_pct': log_stats['invalid_pct']
            })
            
            # Per-set rows
            for set_name, set_stats in log_stats.get('per_set', {}).items():
                log_rows.append({
                    'scope': set_name,
                    'total_entries': set_stats['total'],
                    'invalid_entries': set_stats['invalid'],
                    'invalid_pct': set_stats['invalid_pct']
                })
            
            log_df = pd.DataFrame(log_rows)
            log_df.to_csv(log_csv, index=False, float_format='%.4f')
            print(f"✓ Log validity stats ({stratum_name}) saved to: {log_csv}")
    
    # Save summary JSON with explicit type conversion
    summary_json = output.with_suffix('.summary.json')
    
    # Build summary with native Python types only
    summary_data = {}
    for stratum_name, stratum_data in results.items():
        summary_data[stratum_name] = {
            'n_papers': int(stratum_data['n_papers']),
            'n_fields': int(stratum_data['n_fields']),
            'n_observations': int(stratum_data['n_observations']),
            'overall_perfect': int(stratum_data['overall_perfect']),
            'overall_perfect_pct': float(stratum_data['overall_perfect_pct']) if stratum_data['overall_perfect_pct'] is not None else None,
            'overall_perfect_ci_95': [
                float(stratum_data['overall_perfect_ci_lower']),
                float(stratum_data['overall_perfect_ci_upper'])
            ],
            'overall_uncertain': int(stratum_data['overall_uncertain']),
            'overall_uncertain_pct': float(stratum_data['overall_uncertain_pct']) if stratum_data['overall_uncertain_pct'] is not None else None,
            'overall_uncertain_ci_95': [
                float(stratum_data['overall_uncertain_ci_lower']),
                float(stratum_data['overall_uncertain_ci_upper'])
            ],
            'overall_contradiction': int(stratum_data['overall_contradiction']),
            'overall_contradiction_pct': float(stratum_data['overall_contradiction_pct']) if stratum_data['overall_contradiction_pct'] is not None else None,
            'overall_contradiction_ci_95': [
                float(stratum_data['overall_contradiction_ci_lower']),
                float(stratum_data['overall_contradiction_ci_upper'])
            ],
            # === NEW: Log validity stats ===
            'log_validity': {
                'total_entries': int(stratum_data['log_stats']['total_entries']),
                'invalid_entries': int(stratum_data['log_stats']['invalid_entries']),
                'invalid_pct': float(stratum_data['log_stats']['invalid_pct']),
                'per_set': {
                    k: {
                        'total': int(v['total']),
                        'invalid': int(v['invalid']),
                        'invalid_pct': float(v['invalid_pct'])
                    }
                    for k, v in stratum_data['log_stats'].get('per_set', {}).items()
                }
            } if stratum_data.get('log_stats') else None
        }
    
    with open(summary_json, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
    print(f"✓ Summary saved to: {summary_json}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='3-run agreement analysis for ResearchParça v1.2+')
    parser.add_argument('--db', required=True, help='Path to single database with 3-run format')
    parser.add_argument('-o', '--output', default='agreement_3run_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    args = parser.parse_args()
    
    if not Path(args.db).exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    
    if not args.quiet:
        print(f"ResearchParça 3-Run Agreement Analysis (Single DB Format + Wilson CIs)")
        print(f"Database: {args.db}")
    
    # Load data from SINGLE database
    if not args.quiet:
        print(f"\nLoading database into RAM...")
    papers = load_all_papers_from_single_db(args.db)
    
    if not args.quiet:
        print(f"✓ Loaded {len(papers)} papers with 3-run data. Starting analysis...\n")
    
    # Run analysis
    results = run_analysis(papers, BOOLEAN_FIELDS, args.db)
    
    if not args.quiet:
        print_summary(results)
    
    save_results(results, args.output)
    
    if not args.quiet:
        print("✓ Analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())