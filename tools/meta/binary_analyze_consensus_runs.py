#!/usr/bin/env python3
"""
consistency_binary_only.py
==========================
Sanity check: Measure classification consistency using ONLY binary (Yes/No) data.
All Unknown values are excluded from the analysis entirely.

This answers: "When the model DOES make a definitive claim, how consistent is it?"

Expected runtime: ~5-15 seconds for 1000 papers × 27 fields × 3 databases.

Usage:
    python consistency_binary_only.py \
        --db1 run1.sqlite --db2 run2.sqlite --db3 run3.sqlite \
        --output binary_results.csv
"""

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np
import pandas as pd
import krippendorff


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
        
        # Encode: 1=No, 2=Yes, 0=Unknown (we'll filter out 0s later)
        encoded = {}
        
        # Direct boolean columns
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            val = row[field]
            if val == 1:
                encoded[field] = 2  # Yes
            elif val == 0:
                encoded[field] = 1  # No
            else:
                encoded[field] = 0  # Unknown
        
        # Feature fields
        for field in JSON_FEATURE_FIELDS:
            val = features.get(field)
            if val == 1 or val is True:
                encoded[field] = 2
            elif val == 0 or val is False:
                encoded[field] = 1
            else:
                encoded[field] = 0
        
        # Technique fields
        for field in JSON_TECHNIQUE_FIELDS:
            val = technique.get(field)
            if val == 1 or val is True:
                encoded[field] = 2
            elif val == 0 or val is False:
                encoded[field] = 1
            else:
                encoded[field] = 0
        
        papers[paper_id] = encoded
    
    return papers


def load_all_databases(db_paths: List[str]) -> List[Dict[int, Dict]]:
    """Load all papers from all databases into memory."""
    print(f"Loading {len(db_paths)} databases into RAM...")
    all_papers = []
    for db_path in db_paths:
        print(f"  Loading {Path(db_path).name}...", end='\r')
        papers = load_all_papers_from_db(db_path)
        all_papers.append(papers)
        print(f"  Loaded {Path(db_path).name}: {len(papers)} papers")
    return all_papers


# ============================================================================
# BINARY-ONLY METRICS
# ============================================================================

def extract_binary_only_matrix(all_papers: List[Dict[int, Dict]], paper_ids: List[int], field: str) -> Tuple[np.ndarray, int]:
    """
    Extract a matrix containing ONLY papers where ALL 3 runs gave a definitive answer (Yes/No).
    
    Returns:
        matrix: (n_binary_papers, 3) with values in {1, 2} (No/Yes)
        n_excluded: Number of papers excluded due to Unknown in any run
    """
    binary_rows = []
    n_excluded = 0
    
    for paper_id in paper_ids:
        values = [all_papers[run][paper_id].get(field, 0) for run in range(len(all_papers))]
        
        # Check if ALL runs are definitive (no Unknown = 0)
        if all(v != 0 for v in values):
            binary_rows.append(values)
        else:
            n_excluded += 1
    
    if len(binary_rows) == 0:
        return np.array([]).reshape(0, 3), n_excluded
    
    return np.array(binary_rows, dtype=int), n_excluded


def compute_binary_krippendorff_alpha(data_matrix: np.ndarray) -> float:
    """Compute Krippendorff's Alpha for binary nominal data."""
    if data_matrix.shape[0] < 2:
        return np.nan
    unique_values = np.unique(data_matrix)
    if len(unique_values) < 2:
        return 1.0  # Perfect agreement (no variance)
    try:
        return krippendorff.alpha(
            reliability_data=data_matrix.T,
            level_of_measurement='nominal'
        )
    except ValueError:
        return 1.0


def compute_binary_percent_agreement(data_matrix: np.ndarray) -> float:
    """Compute percent agreement for binary data."""
    if data_matrix.shape[0] == 0:
        return np.nan
    agreement = np.all(data_matrix == data_matrix[:, [0]], axis=1)
    return np.mean(agreement)


def compute_binary_disagreement_type(data_matrix: np.ndarray) -> Dict:
    """
    Analyze disagreement types for binary data.
    
    Since this is binary-only (1=No, 2=Yes), all disagreements are Yes↔No conflicts.
    """
    if data_matrix.shape[0] == 0 or data_matrix.shape[1] < 2:
        return {'total_pairs': 0, 'disagreements': 0, 'disagreement_rate': 0}
    
    n_papers, n_raters = data_matrix.shape
    total_pairs = 0
    disagreements = 0
    
    for i in range(n_papers):
        values = data_matrix[i]
        for a in range(n_raters):
            for b in range(a + 1, n_raters):
                if values[a] != values[b]:
                    disagreements += 1
                total_pairs += 1
    
    return {
        'total_pairs': total_pairs,
        'disagreements': disagreements,
        'disagreement_rate': (disagreements / total_pairs * 100) if total_pairs > 0 else 0
    }


# ============================================================================
# ANALYSIS
# ============================================================================

def analyze_field_binary(all_papers: List[Dict[int, Dict]], paper_ids: List[int], field: str) -> Dict:
    """Analyze a single field using binary-only data."""
    matrix, n_excluded = extract_binary_only_matrix(all_papers, paper_ids, field)
    
    if matrix.shape[0] == 0:
        return {
            'field': field,
            'binary_alpha': np.nan,
            'binary_percent_agreement': np.nan,
            'n_binary_papers': 0,
            'n_excluded_unknown': n_excluded,
            'disagreement_rate': np.nan,
            '_matrix': matrix
        }
    
    alpha = compute_binary_krippendorff_alpha(matrix)
    pct_agree = compute_binary_percent_agreement(matrix)
    disagreement = compute_binary_disagreement_type(matrix)
    
    return {
        'field': field,
        'binary_alpha': alpha,
        'binary_percent_agreement': pct_agree,
        'n_binary_papers': matrix.shape[0],
        'n_excluded_unknown': n_excluded,
        'disagreement_rate': disagreement['disagreement_rate'],
        '_matrix': matrix
    }


def run_binary_analysis(all_papers: List[Dict[int, Dict]], fields: List[str]) -> Dict:
    """Run binary-only analysis across all fields."""
    print(f"\nAnalyzing {len(fields)} fields (binary-only, Unknown excluded)...\n")
    
    # Get paper IDs
    all_paper_ids = list(all_papers[0].keys())
    
    # Stratify by off-topic (using first run only, same as main analysis)
    on_topic_ids = []
    off_topic_ids = []
    for paper_id in all_paper_ids:
        offtopic_val = all_papers[0][paper_id].get('is_offtopic', 0)
        if offtopic_val == 2:  # Yes, off-topic
            off_topic_ids.append(paper_id)
        else:
            on_topic_ids.append(paper_id)
    
    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids
    }
    
    results = {}
    for stratum_name, stratum_ids in strata.items():
        print(f"  Analyzing {stratum_name} ({len(stratum_ids)} total papers)...")
        field_results = []
        
        for field in fields:
            result = analyze_field_binary(all_papers, stratum_ids, field)
            field_results.append(result)
        
        results_df = pd.DataFrame([
            {k: v for k, v in r.items() if k != '_matrix'}
            for r in field_results
        ])
        
        # Calculate overall metrics (mean of field alphas, weighted by binary paper count)
        valid_alphas = results_df[results_df['binary_alpha'].notna()]
        if len(valid_alphas) > 0:
            # Weighted mean by number of binary papers
            overall_alpha = np.average(
                valid_alphas['binary_alpha'],
                weights=valid_alphas['n_binary_papers']
            )
        else:
            overall_alpha = np.nan
        
        # Overall exclusion rate
        total_excluded = results_df['n_excluded_unknown'].sum()
        total_observations = len(stratum_ids) * len(fields)
        exclusion_rate = (total_excluded / total_observations * 100) if total_observations > 0 else 0
        
        # Binary paper coverage
        total_binary = results_df['n_binary_papers'].sum()
        binary_coverage = (total_binary / total_observations * 100) if total_observations > 0 else 0
        
        results[stratum_name] = {
            'n_total_papers': len(stratum_ids),
            'overall_binary_alpha': overall_alpha,
            'overall_percent_agreement': results_df['binary_percent_agreement'].mean(),
            'field_results': results_df,
            'exclusion_rate': exclusion_rate,
            'binary_coverage': binary_coverage,
            'total_binary_observations': total_binary,
            'total_excluded_observations': total_excluded
        }
    
    return results


# ============================================================================
# OUTPUT
# ============================================================================

def print_summary(results: Dict):
    """Print human-readable summary."""
    print("\n" + "="*70)
    print("BINARY-ONLY CONSISTENCY ANALYSIS - SUMMARY")
    print("(Unknown values excluded - measures consistency of definitive claims only)")
    print("="*70)
    
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        
        print(f"\n📊 {stratum_name.upper().replace('_', ' ')} ({s['n_total_papers']} total papers)")
        print(f"   Binary Krippendorff's α: {s['overall_binary_alpha']:.3f}")
        print(f"   Binary Percent Agreement: {s['overall_percent_agreement']*100:.1f}%")
        print(f"   Data coverage: {s['binary_coverage']:.1f}% definitive, {s['exclusion_rate']:.1f}% excluded (Unknown)")
        print(f"   Total observations: {s['total_binary_observations']} binary, {s['total_excluded_observations']} excluded")
        
        if not s['field_results'].empty:
            print(f"   Per-field α range: [{s['field_results']['binary_alpha'].min():.3f}, "
                  f"{s['field_results']['binary_alpha'].max():.3f}]")
        
        # Show fields sorted by binary alpha
        if stratum_name == 'on_topic_only' and not s['field_results'].empty:
            print(f"\n📋 ALL FIELDS - Binary-only consistency (sorted by α, best → worst):")
            sorted_fields = s['field_results'].sort_values('binary_alpha', ascending=False)
            for _, row in sorted_fields.iterrows():
                if np.isnan(row['binary_alpha']):
                    continue
                alpha = row['binary_alpha']
                agree = row['binary_percent_agreement']*100
                n_binary = row['n_binary_papers']
                excl = row['n_excluded_unknown']
                disagree_rate = row['disagreement_rate']
                
                bar_len = int(max(0, min(20, (alpha + 1) * 10)))
                bar = '█' * bar_len + '░' * (20 - bar_len)
                
                print(f"   {row['field']:25s} α={alpha:6.3f} {bar}  agree={agree:5.1f}%  n={n_binary:4d}  excl={excl:4d}  disagree={disagree_rate:5.1f}%")
    
    # Comparison with full analysis
    print(f"\n" + "="*70)
    print("INTERPRETATION")
    print("="*70)
    
    on_topic_alpha = results['on_topic_only']['overall_binary_alpha']
    on_topic_coverage = results['on_topic_only']['binary_coverage']
    
    print(f"""
Key Insights:
─────────────────────────────────────────────────────────────────────────
1. Binary α = {on_topic_alpha:.3f} tells you: "When the model commits to Yes/No, 
   it agrees with itself {on_topic_alpha*100:.0f}% of the time (chance-corrected)"

2. Coverage = {on_topic_coverage:.1f}% tells you: "Only {on_topic_coverage:.0f}% of all 
   paper×field combinations got definitive answers; the rest were Unknown"

3. If Binary α >> Full α (from main analysis):
   → The model is consistent when it commits, but cautious (lots of Unknown)
   → Low full α is due to Unknown↔Unknown or Yes↔Unknown, not Yes↔No

4. If Binary α ≈ Full α:
   → Low consistency is due to genuine Yes↔No contradictions
   → The model is genuinely unstable on definitive claims

5. High exclusion rate ({results['on_topic_only']['exclusion_rate']:.1f}%):
   → Most fields are Unknown for most papers
   → This is EXPECTED for abstract-level classification of defect features
─────────────────────────────────────────────────────────────────────────
""")
    
    print("="*70 + "\n")


def save_results(results: Dict, output_path: str):
    """Save results to CSV and JSON."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    for stratum_name, stratum_data in results.items():
        # Save per-field results
        field_csv = output.with_suffix(f'.{stratum_name}.binary_fields.csv')
        stratum_data['field_results'].to_csv(field_csv, index=False, float_format='%.4f')
        print(f"✓ Binary field results ({stratum_name}) saved to: {field_csv}")
    
    # Save summary
    summary_json = output.with_suffix('.binary_summary.json')
    
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
            'n_total_papers': stratum_data['n_total_papers'],
            'overall_binary_alpha': convert(stratum_data['overall_binary_alpha']),
            'overall_percent_agreement': convert(stratum_data['overall_percent_agreement']),
            'binary_coverage_pct': convert(stratum_data['binary_coverage']),
            'exclusion_rate_pct': convert(stratum_data['exclusion_rate']),
            'total_binary_observations': stratum_data['total_binary_observations'],
            'total_excluded_observations': stratum_data['total_excluded_observations']
        }
    
    with open(summary_json, 'w') as f:
        json.dump(summary_data, f, indent=2)
    print(f"✓ Binary summary saved to: {summary_json}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Binary-only consistency analysis (Unknown excluded)')
    parser.add_argument('--db1', required=True, help='Path to first database')
    parser.add_argument('--db2', required=True, help='Path to second database')
    parser.add_argument('--db3', required=True, help='Path to third database')
    parser.add_argument('-o', '--output', default='binary_consistency_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    args = parser.parse_args()
    
    db_paths = [args.db1, args.db2, args.db3]
    for db in db_paths:
        if not Path(db).exists():
            print(f"Error: Database not found: {db}", file=sys.stderr)
            sys.exit(1)
    
    if not args.quiet:
        print(f"ResearchParça Binary-Only Consistency Analysis")
        print(f"Databases: {', '.join(db_paths)}")
    
    # Load all data into RAM
    all_papers = load_all_databases(db_paths)
    
    if not args.quiet:
        print(f"\n✓ All data loaded. Starting binary-only analysis...\n")
    
    # Run analysis
    results = run_binary_analysis(all_papers, BOOLEAN_FIELDS)
    
    if not args.quiet:
        print_summary(results)
    
    save_results(results, args.output)
    
    if not args.quiet:
        print("✓ Binary analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())