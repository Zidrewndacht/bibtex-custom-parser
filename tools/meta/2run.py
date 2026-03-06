#!/usr/bin/env python3
"""
consistency_2run.py
===================
Simplified 2-run agreement analysis for ResearchParça.

Measures what actually matters:
- YY/NN/UU = Perfect agreement (trust it)
- YU/NU = Acceptable uncertainty (model hedging)
- YN = Definitive contradiction (actual error - needs review)

Usage:
    python consistency_2run.py --db1 run1.sqlite --db2 run2.sqlite --output results.csv
"""

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple
import numpy as np
import pandas as pd


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


def load_two_databases(db1_path: str, db2_path: str) -> Tuple[Dict[int, Dict], Dict[int, Dict]]:
    """Load papers from both databases."""
    print(f"Loading databases into RAM...")
    papers1 = load_all_papers_from_db(db1_path)
    print(f"  Loaded {Path(db1_path).name}: {len(papers1)} papers")
    papers2 = load_all_papers_from_db(db2_path)
    print(f"  Loaded {Path(db2_path).name}: {len(papers2)} papers")
    return papers1, papers2


# ============================================================================
# AGREEMENT ANALYSIS
# ============================================================================

def classify_agreement(val1: int, val2: int) -> str:
    """
    Classify agreement type between two runs.
    
    Encoding: 2=Yes, 1=No, 0=Unknown
    
    Returns:
        'perfect' = YY, NN, or UU (both agree)
        'uncertain' = YU, UY, NU, UN (one definitive, one uncertain)
        'contradiction' = YN or NY (contradictory definitives)
    """
    if val1 == val2:
        return 'perfect'
    
    # Check for contradiction (Yes↔No)
    if (val1 == 2 and val2 == 1) or (val1 == 1 and val2 == 2):
        return 'contradiction'
    
    # Otherwise it's uncertainty (one is Unknown, other is Yes or No)
    return 'uncertain'


def analyze_field_agreement(papers1: Dict[int, Dict], papers2: Dict[int, Dict], 
                            field: str, paper_ids: List[int]) -> Dict:
    """Analyze agreement for a single field across two runs."""
    perfect_count = 0
    uncertain_count = 0
    contradiction_count = 0
    
    for paper_id in paper_ids:
        val1 = papers1[paper_id].get(field, 0)
        val2 = papers2[paper_id].get(field, 0)
        
        agreement = classify_agreement(val1, val2)
        if agreement == 'perfect':
            perfect_count += 1
        elif agreement == 'uncertain':
            uncertain_count += 1
        else:
            contradiction_count += 1
    
    total = len(paper_ids)
    return {
        'field': field,
        'n_papers': total,
        'perfect': perfect_count,
        'perfect_pct': (perfect_count / total * 100) if total > 0 else 0,
        'uncertain': uncertain_count,
        'uncertain_pct': (uncertain_count / total * 100) if total > 0 else 0,
        'contradiction': contradiction_count,
        'contradiction_pct': (contradiction_count / total * 100) if total > 0 else 0,
    }


def analyze_stratum(papers1: Dict[int, Dict], papers2: Dict[int, Dict], 
                   paper_ids: List[int], fields: List[str], stratum_name: str) -> Dict:
    """Run full agreement analysis on a stratum of papers."""
    print(f"  Analyzing {stratum_name} ({len(paper_ids)} papers)...")
    
    if len(paper_ids) == 0:
        return {
            'stratum': stratum_name,
            'n_papers': 0,
            'field_results': pd.DataFrame(),
            'overall_perfect_pct': 0,
            'overall_contradiction_pct': 0
        }
    
    field_results = []
    for field in fields:
        result = analyze_field_agreement(papers1, papers2, field, paper_ids)
        field_results.append(result)
    
    results_df = pd.DataFrame(field_results)
    
    # Overall metrics (weighted by paper count, which is constant per field)
    overall_perfect = results_df['perfect'].sum()
    overall_uncertain = results_df['uncertain'].sum()
    overall_contradiction = results_df['contradiction'].sum()
    total_observations = len(paper_ids) * len(fields)
    
    return {
        'stratum': stratum_name,
        'n_papers': len(paper_ids),
        'field_results': results_df,
        'overall_perfect': overall_perfect,
        'overall_perfect_pct': (overall_perfect / total_observations * 100) if total_observations > 0 else 0,
        'overall_uncertain': overall_uncertain,
        'overall_uncertain_pct': (overall_uncertain / total_observations * 100) if total_observations > 0 else 0,
        'overall_contradiction': overall_contradiction,
        'overall_contradiction_pct': (overall_contradiction / total_observations * 100) if total_observations > 0 else 0,
    }


def run_analysis(papers1: Dict[int, Dict], papers2: Dict[int, Dict], fields: List[str]) -> Dict:
    """Run stratified 2-run agreement analysis."""
    print(f"\nAnalyzing {len(fields)} fields across 2 runs...\n")
    
    # Get paper IDs (both DBs should have same papers)
    all_paper_ids = list(papers1.keys())
    
    # Stratify by off-topic status (from run 1)
    on_topic_ids = []
    off_topic_ids = []
    for paper_id in all_paper_ids:
        offtopic_val = papers1[paper_id].get('is_offtopic', 0)
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
        results[stratum_name] = analyze_stratum(papers1, papers2, stratum_ids, fields, stratum_name)
    
    return results


# ============================================================================
# OUTPUT
# ============================================================================

def print_summary(results: Dict):
    """Print human-readable summary."""
    print("\n" + "="*70)
    print("2-RUN AGREEMENT ANALYSIS - SUMMARY")
    print("="*70)
    
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        if s['n_papers'] == 0:
            continue
        
        print(f"\n📊 {stratum_name.upper().replace('_', ' ')} ({s['n_papers']} papers)")
        print(f"   Perfect agreement (YY/NN/UU):   {s['overall_perfect_pct']:5.1f}%  ✅ Trust")
        print(f"   Uncertain (YU/NU):              {s['overall_uncertain_pct']:5.1f}%  ⚠️  Acceptable")
        print(f"   Contradiction (YN):             {s['overall_contradiction_pct']:5.1f}%  ❌ Review needed")
        
        if not s['field_results'].empty:
            print(f"\n   📋 BY CATEGORY:")
            
            # Group by category
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
                worst = cat_df.loc[cat_df['contradiction_pct'].idxmax()]
                
                print(f"   ┌─ {cat_name}:")
                print(f"   │  Avg Perfect: {cat_perfect:.1f}%  |  Avg Contradiction: {cat_contra:.1f}%")
                print(f"   │  Worst field: {worst['field']} ({worst['contradiction_pct']:.1f}% contradictions)")
        
        # Show all fields sorted by contradiction rate (worst first)
        if stratum_name == 'on_topic_only' and not s['field_results'].empty:
            print(f"\n   📋 ALL FIELDS - Sorted by contradiction rate (worst → best):")
            sorted_fields = s['field_results'].sort_values('contradiction_pct', ascending=False)
            for _, row in sorted_fields.iterrows():
                # Visual bar for contradiction rate
                bar_len = int(min(20, row['contradiction_pct'] / 5))  # Scale: 5% = 1 bar
                bar = '█' * bar_len + '░' * (20 - bar_len)
                status = '❌' if row['contradiction_pct'] > 10 else ('⚠️' if row['contradiction_pct'] > 5 else '✅')
                print(f"      {row['field']:25s} {status} {bar}  {row['contradiction_pct']:5.1f}% contradict  |  {row['perfect_pct']:5.1f}% perfect")
    
    # Interpretation
    print(f"\n" + "="*70)
    print("INTERPRETATION GUIDE")
    print("="*70)
    
    contra = results['on_topic_only']['overall_contradiction_pct']
    print(f"""
On-Topic Contradiction Rate: {contra:.1f}%

📌 What This Means:
─────────────────────────────────────────────────────────────────────────
• {contra:.1f}% of all paper×field classifications have YN contradictions
  → These are **definitive errors** requiring human review

• The remaining {100-contra:.1f}% are either:
  → Perfect agreement ({results['on_topic_only']['overall_perfect_pct']:.1f}%): Trust the classification
  → Uncertain ({results['on_topic_only']['overall_uncertain_pct']:.1f}%): Model hedging, but not wrong

📌 Actionable Thresholds:
─────────────────────────────────────────────────────────────────────────
• < 5% contradictions:  ✅ Excellent - minimal review needed
• 5-10% contradictions: ⚠️  Acceptable - review high-contradiction fields
• > 10% contradictions: ❌ Concerning - consider prompt engineering or 
                           manual review of affected fields
─────────────────────────────────────────────────────────────────────────
""")
    
    print("="*70 + "\n")


def save_results(results: Dict, output_path: str):
    """Save results to CSV and JSON."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    for stratum_name, stratum_data in results.items():
        if stratum_data['n_papers'] == 0:
            continue
        
        # Save per-field results
        field_csv = output.with_suffix(f'.{stratum_name}.agreement.csv')
        stratum_data['field_results'].to_csv(field_csv, index=False, float_format='%.2f')
        print(f"✓ Agreement results ({stratum_name}) saved to: {field_csv}")
    
    # Save summary
    summary_json = output.with_suffix('.summary.json')
    
    def convert(obj):
        if isinstance(obj, (np.floating, float)):
            if np.isnan(obj): return None
            return float(obj)
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, dict): return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)): return [convert(v) for v in obj]
        return obj
    
    summary_data = {}
    for stratum_name, stratum_data in results.items():
        summary_data[stratum_name] = {
            'n_papers': stratum_data['n_papers'],
            'overall_perfect_pct': convert(stratum_data['overall_perfect_pct']),
            'overall_uncertain_pct': convert(stratum_data['overall_uncertain_pct']),
            'overall_contradiction_pct': convert(stratum_data['overall_contradiction_pct']),
        }
    
    with open(summary_json, 'w') as f:
        json.dump(summary_data, f, indent=2)
    print(f"✓ Summary saved to: {summary_json}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='2-run agreement analysis for ResearchParça')
    parser.add_argument('--db1', required=True, help='Path to first database')
    parser.add_argument('--db2', required=True, help='Path to second database')
    parser.add_argument('-o', '--output', default='agreement_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    args = parser.parse_args()
    
    db_paths = [args.db1, args.db2]
    for db in db_paths:
        if not Path(db).exists():
            print(f"Error: Database not found: {db}", file=sys.stderr)
            sys.exit(1)
    
    if not args.quiet:
        print(f"ResearchParça 2-Run Agreement Analysis")
        print(f"Databases: {', '.join(db_paths)}")
    
    # Load data
    papers1, papers2 = load_two_databases(args.db1, args.db2)
    
    if not args.quiet:
        print(f"\n✓ All data loaded. Starting analysis...\n")
    
    # Run analysis
    results = run_analysis(papers1, papers2, BOOLEAN_FIELDS)
    
    if not args.quiet:
        print_summary(results)
    
    save_results(results, args.output)
    
    if not args.quiet:
        print("✓ Analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())