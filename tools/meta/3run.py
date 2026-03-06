#!/usr/bin/env python3
"""
consistency_3run_simple.py
==========================
3-run agreement analysis for ResearchParça using simple, interpretable logic.

Agreement categories:
- ✅ Perfect: All 3 runs agree (YYY/NNN/UUU)
- ⚠️ Acceptable: No Yes↔No conflict, but not all identical (e.g., YYU, YUU)
- ❌ Contradiction: At least one Yes AND one No among the 3 runs (definitive error)

This directly answers: "How often does the model contradict itself on definitive claims?"

Usage:
    python consistency_3run_simple.py \
        --db1 run1.sqlite --db2 run2.sqlite --db3 run3.sqlite \
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


# ============================================================================
# STATISTICAL HELPERS
# ============================================================================

def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate Wilson score interval for a proportion.
    More accurate than Wald interval, especially for small n or extreme proportions.
    
    Args:
        successes: Number of "success" events (e.g., contradictions)
        n: Total number of observations
        confidence: Confidence level (default 0.95 for 95% CI)
    
    Returns:
        Tuple of (lower_bound_pct, upper_bound_pct) as percentages
    """
    if n == 0:
        return 0.0, 100.0
    
    z = stats.norm.ppf((1 + confidence) / 2)  # e.g., 1.96 for 95% CI
    p_hat = successes / n
    
    # Wilson score interval formula
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2*n)) / denominator
    margin = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*n)) / n) / denominator
    
    lower = max(0, (centre - margin) * 100)
    upper = min(100, (centre + margin) * 100)
    return lower, upper


def format_with_ci(pct: float, count: int, total: int, min_n: int = MIN_N_FOR_CI) -> str:
    """
    Format percentage with optional confidence interval.
    
    Args:
        pct: Percentage value
        count: Number of events (numerator)
        total: Total observations (denominator)
        min_n: Minimum n to show CI (below this, show count only)
    
    Returns:
        Formatted string, e.g., "0.6% [0.5%, 0.63%] (n=52,893)" or "0.6% (n=45)"
    """
    if total < min_n:
        return f"{pct:.1f}% ({count:,}  /  {total:,})"
    
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.1f}% [{lower:.2f}%, {upper:.2f}%] ({count:,}/{total:,})"

# ============================================================================
# DATA LOADING
# ============================================================================

def load_all_papers_from_db(db_path: str) -> Dict[int, Dict]:
    """Load ALL papers from a database into memory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    papers = {}
    for row in rows:
        paper_id = row['id']
        
        try:
            features = json.loads(row['features']) if row['features'] else {}
        except (json.JSONDecodeError, TypeError):
            features = {}
        
        try:
            technique = json.loads(row['technique']) if row['technique'] else {}
        except (json.JSONDecodeError, TypeError):
            technique = {}
        
        # Encode: 2=Yes, 1=No, 0=Unknown
        encoded = {}
        
        # Direct boolean columns
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            val = row[field]
            encoded[field] = 2 if val == 1 else (1 if val == 0 else 0)
        
        # Feature fields
        for field in JSON_FEATURE_FIELDS:
            val = features.get(field)
            encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
        
        # Technique fields
        for field in JSON_TECHNIQUE_FIELDS:
            val = technique.get(field)
            encoded[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
        
        papers[paper_id] = encoded
    
    return papers


def load_three_databases(db_paths: List[str]) -> List[Dict[int, Dict]]:
    """Load papers from all three databases."""
    print(f"Loading {len(db_paths)} databases into RAM...")
    all_papers = []
    for db_path in db_paths:
        print(f"  Loading {Path(db_path).name}...", end='\r')
        papers = load_all_papers_from_db(db_path)
        all_papers.append(papers)
        print(f"  Loaded {Path(db_path).name}: {len(papers)} papers")
    return all_papers


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
        'contradiction' = At least one Yes AND one No among the 3 runs
    """
    counts = Counter(values)
    
    if len(counts) == 1:
        return 'perfect'
    
    has_yes = counts.get(2, 0) > 0
    has_no = counts.get(1, 0) > 0
    
    if has_yes and has_no:
        return 'contradiction'
    
    return 'uncertain'


def analyze_field_agreement(all_papers: List[Dict[int, Dict]], field: str, 
                           paper_ids: List[int]) -> Dict:
    """Analyze agreement for a single field across 3 runs."""
    perfect_count = 0
    uncertain_count = 0
    contradiction_count = 0
    
    for paper_id in paper_ids:
        values = [all_papers[run][paper_id].get(field, 0) for run in range(3)]
        agreement = classify_3run_agreement(values)
        
        if agreement == 'perfect':
            perfect_count += 1
        elif agreement == 'uncertain':
            uncertain_count += 1
        else:
            contradiction_count += 1
    
    total = len(paper_ids)
    
    # Calculate CIs for each metric
    perfect_ci = wilson_score_interval(perfect_count, total)
    uncertain_ci = wilson_score_interval(uncertain_count, total)
    contradiction_ci = wilson_score_interval(contradiction_count, total)
    
    return {
        'field': field,
        'n_papers': total,
        'n_observations': total,
        'perfect': perfect_count,
        'perfect_pct': (perfect_count / total * 100) if total > 0 else 0,
        'perfect_ci_lower': perfect_ci[0],
        'perfect_ci_upper': perfect_ci[1],
        'uncertain': uncertain_count,
        'uncertain_pct': (uncertain_count / total * 100) if total > 0 else 0,
        'uncertain_ci_lower': uncertain_ci[0],
        'uncertain_ci_upper': uncertain_ci[1],
        'contradiction': contradiction_count,
        'contradiction_pct': (contradiction_count / total * 100) if total > 0 else 0,
        'contradiction_ci_lower': contradiction_ci[0],
        'contradiction_ci_upper': contradiction_ci[1],
    }


def analyze_stratum(all_papers: List[Dict[int, Dict]], paper_ids: List[int], 
                   fields: List[str], stratum_name: str) -> Dict:
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
            'overall_contradiction_ci': (0, 100)
        }
    
    field_results = []
    for field in fields:
        result = analyze_field_agreement(all_papers, field, paper_ids)
        field_results.append(result)
    
    results_df = pd.DataFrame(field_results)
    
    # Overall metrics (aggregate across all fields)
    overall_perfect = results_df['perfect'].sum()
    overall_uncertain = results_df['uncertain'].sum()
    overall_contradiction = results_df['contradiction'].sum()
    total_observations = len(paper_ids) * len(fields)
    
    # Calculate overall CIs
    overall_perfect_ci = wilson_score_interval(overall_perfect, total_observations)
    overall_uncertain_ci = wilson_score_interval(overall_uncertain, total_observations)
    overall_contradiction_ci = wilson_score_interval(overall_contradiction, total_observations)
    
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
    }


def run_analysis(all_papers: List[Dict[int, Dict]], fields: List[str]) -> Dict:
    """Run stratified 3-run agreement analysis."""
    print(f"\nAnalyzing {len(fields)} fields across 3 runs...\n")
    
    all_paper_ids = list(all_papers[0].keys())
    
    # Stratify by off-topic status (from run 1)
    on_topic_ids = []
    off_topic_ids = []
    for paper_id in all_paper_ids:
        offtopic_val = all_papers[0][paper_id].get('is_offtopic', 0)
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
        results[stratum_name] = analyze_stratum(all_papers, stratum_ids, fields, stratum_name)
    
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
        
        # Format with CI or count-only based on sample size
        perfect_fmt = format_with_ci(s['overall_perfect_pct'], s['overall_perfect'], s['n_observations'])
        uncertain_fmt = format_with_ci(s['overall_uncertain_pct'], s['overall_uncertain'], s['n_observations'])
        contradiction_fmt = format_with_ci(s['overall_contradiction_pct'], s['overall_contradiction'], s['n_observations'])
        
        print(f"   ✅ Perfect (YYY/NNN/UUU):      {perfect_fmt:45s} Trust")
        print(f"   ⚠️  Uncertain (no Y↔N):         {uncertain_fmt:45s} Acceptable")
        print(f"   ❌ Contradiction (Y+N present): {contradiction_fmt:45s} Review needed")
        print(f"\n   📊 Raw counts: {s['overall_perfect']:,} perfect | {s['overall_uncertain']:,} uncertain | {s['overall_contradiction']:,} contradictions")
        
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
                
                # Format worst field with CI
                worst_contra_fmt = format_with_ci(
                    worst['contradiction_pct'], 
                    worst['contradiction'], 
                    worst['n_papers']
                )
                
                print(f"   ┌─ {cat_name}:")
                print(f"   │  Sample: {cat_n:,} papers | Avg Perfect: {cat_perfect:.1f}%  |  Avg Contradiction: {cat_contra:.1f}%")
                print(f"   │  Worst field: {worst['field']} → {worst_contra_fmt}")
        
        # Show fields grouped and sorted by perfect agreement (best → worst)
        if stratum_name == 'on_topic_only' and not s['field_results'].empty:
            print(f"\n   📋 ALL FIELDS - Sorted by perfect agreement (best → worst):")
            
            # Define field groups
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
                
                # Sort by perfect_pct descending (best first)
                sorted_group = group_df.sort_values('perfect_pct', ascending=False)
                
                print(f"\n   {group_name}:")
                for _, row in sorted_group.iterrows():
                    # Bar represents PERFECT agreement (visual reliability indicator)
                    bar_len = int(min(20, row['perfect_pct'] / 5))  # 100% = 20 blocks
                    bar = '█' * bar_len + '░' * (20 - bar_len)
                    
                    # Status emoji based on CONTRADICTION rate (actionable risk indicator)
                    contra_pct = row['contradiction_pct']
                    if contra_pct < 1.0:
                        status = '✅'  # Excellent: <1% contradictions
                    elif contra_pct < 5.0:
                        status = '⚠️ '  # Watch: 1-5% contradictions
                    else:
                        status = '❌'  # Concerning: ≥5% contradictions
                    
                    # Format with CI
                    perfect_fmt = format_with_ci(row['perfect_pct'], row['perfect'], row['n_papers'])
                    contra_fmt = format_with_ci(row['contradiction_pct'], row['contradiction'], row['n_papers'])
                    
                    # Status emoji appears NEXT TO contradiction stats (where it matters)
                    print(f"      {row['field']:25s} {bar}  Perfect: {perfect_fmt:25s} | Contra: {contra_fmt} {status}")

    # Interpretation with CI context
    print(f"\n" + "="*90)
    print("INTERPRETATION GUIDE")
    print("="*90)
    
    on_topic = results['on_topic_only']
    n_obs = on_topic['n_observations']
    
    # Only show CI interpretation if sample is large enough
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

📌 Why This Is Better Than Tri-State α:
─────────────────────────────────────────────────────────────────────────
1. No conflating "I don't know" with "I'm wrong"
2. Directly answers: "How many classifications need human review?"
3. Actionable thresholds: <5% = excellent, 5-10% = acceptable, >10% = concerning
4. Preserves the value of Unknown as a valid, honest response
5. Confidence intervals quantify uncertainty in the observed rates

📌 Actionable Thresholds (with statistical context):
─────────────────────────────────────────────────────────────────────────
• < 5% contradictions:  ✅ Excellent - minimal review needed
  (If CI upper bound <5%, you can be confident it's truly excellent)
• 5-10% contradictions: ⚠️  Acceptable - review high-contradiction fields  
  (If CI spans 5-10%, consider collecting more data for precision)
• > 10% contradictions: ❌ Concerning - consider prompt engineering or
                           manual review of affected fields
  (If CI lower bound >10%, the problem is statistically confirmed)
─────────────────────────────────────────────────────────────────────────
""")
    else:
        # Fallback for small samples
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
        }
    
    with open(summary_json, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
    print(f"✓ Summary saved to: {summary_json}")
# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='3-run agreement analysis for ResearchParça')
    parser.add_argument('--db1', required=True, help='Path to first database')
    parser.add_argument('--db2', required=True, help='Path to second database')
    parser.add_argument('--db3', required=True, help='Path to third database')
    parser.add_argument('-o', '--output', default='agreement_3run_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    args = parser.parse_args()
    
    db_paths = [args.db1, args.db2, args.db3]
    for db in db_paths:
        if not Path(db).exists():
            print(f"Error: Database not found: {db}", file=sys.stderr)
            sys.exit(1)
    
    if not args.quiet:
        print(f"ResearchParça 3-Run Agreement Analysis (Simple Logic + Wilson CIs)")
        print(f"Databases: {', '.join(db_paths)}")
    
    # Load data
    all_papers = load_three_databases(db_paths)
    
    if not args.quiet:
        print(f"\n✓ All data loaded. Starting analysis...\n")
    
    # Run analysis
    results = run_analysis(all_papers, BOOLEAN_FIELDS)
    
    if not args.quiet:
        print_summary(results)
    
    save_results(results, args.output)
    
    if not args.quiet:
        print("✓ Analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())