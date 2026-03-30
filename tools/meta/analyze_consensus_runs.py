#!/usr/bin/env python3
"""
consistency_analysis.py (FINAL v3 - With Fleiss' Kappa)
=======================================================
Standalone script for analyzing classification consistency across 3 independent 
ResearchParça runs on the same paper sample.

OPTIMIZATION: All data loaded into RAM upfront. Bootstrap CIs are optional.
Expected runtime: ~15-60 seconds for 1000 papers × 27 fields × 3 databases.

Uses textbook inter-rater reliability statistics for nominal/ordinal tri-state 
- Krippendorff's Alpha (nominal AND ordinal variants)
- Fleiss' Kappa (nominal only, optional via --fleiss flag)
- Percent Agreement (baseline, intuitive)
- Paper-level consistency distribution
- Disagreement breakdown (definitive errors vs. honest uncertainty)
- Stratified analysis (all papers, on-topic only, off-topic only)
- Bootstrap confidence intervals (fast, in-memory, optional)

Output: Clean summary metrics + full sorted field list

Usage:
    python consistency_analysis.py \
        --db1 run1.sqlite --db2 run2.sqlite --db3 run3.sqlite \
        --output results.csv [--no-bootstrap] [--fleiss]
"""

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import Counter
import numpy as np
import pandas as pd
import krippendorff  # pip install krippendorff


# ============================================================================
# CONFIGURATION: Fields to analyze (boolean/tri-state only)
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

# Fields stored in JSON columns
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
# DATA LOADING (ALL AT ONCE)
# ============================================================================

def load_all_papers_from_db(db_path: str) -> Dict[int, Dict]:
    """Load ALL papers from a database into memory at once."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    papers = {}
    for row in rows:
        paper_id = row['id']
        
        # Parse JSON columns
        try:
            features = json.loads(row['features']) if row['features'] else {}
        except (json.JSONDecodeError, TypeError):
            features = {}
        
        try:
            technique = json.loads(row['technique']) if row['technique'] else {}
        except (json.JSONDecodeError, TypeError):
            technique = {}
        
        # Encode all fields as 0/1/2 (Unknown/No/Yes) for nominal alpha
        encoded_nominal = {}
        # Encode as 1/2/3 (No/Unknown/Yes) for ordinal alpha
        encoded_ordinal = {}
        
        # Direct boolean columns
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            val = row[field]
            # Nominal: 0=Unknown, 1=No, 2=Yes
            encoded_nominal[field] = 2 if val == 1 else (1 if val == 0 else 0)
            # Ordinal: 1=No, 2=Unknown, 3=Yes
            encoded_ordinal[field] = 3 if val == 1 else (2 if val == 0 else 1)
        
        # Feature fields (from JSON)
        for field in JSON_FEATURE_FIELDS:
            val = features.get(field)
            encoded_nominal[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            encoded_ordinal[field] = 3 if val == 1 or val is True else (2 if val == 0 or val is False else 1)
        
        # Technique fields (from JSON)
        for field in JSON_TECHNIQUE_FIELDS:
            val = technique.get(field)
            encoded_nominal[field] = 2 if val == 1 or val is True else (1 if val == 0 or val is False else 0)
            encoded_ordinal[field] = 3 if val == 1 or val is True else (2 if val == 0 or val is False else 1)
        
        papers[paper_id] = {
            'nominal': encoded_nominal,
            'ordinal': encoded_ordinal
        }
    
    return papers


def load_all_databases(db_paths: List[str]) -> List[Dict[int, Dict]]:
    """Load all papers from all databases into memory."""
    print(f"Loading {len(db_paths)} databases into RAM...")
    all_papers = []
    for i, db_path in enumerate(db_paths):
        print(f"  Loading {Path(db_path).name}...", end='\r')
        papers = load_all_papers_from_db(db_path)
        all_papers.append(papers)
        print(f"  Loaded {Path(db_path).name}: {len(papers)} papers")
    return all_papers


# ============================================================================
# METRICS
# ============================================================================

def compute_krippendorff_alpha(data_matrix: np.ndarray, level: str = 'nominal') -> float:
    """Compute Krippendorff's Alpha for nominal or ordinal data."""
    if data_matrix.shape[0] < 2:
        return np.nan
    # Check if there's any variance in the data
    unique_values = np.unique(data_matrix)
    if len(unique_values) < 2:
        return 1.0  # Perfect agreement (no variance to measure)
    try:
        return krippendorff.alpha(
            reliability_data=data_matrix.T,
            level_of_measurement=level
        )
    except ValueError:
        return 1.0  # Perfect agreement fallback


def compute_fleiss_kappa(data_matrix: np.ndarray) -> float:
    """
    Compute Fleiss' Kappa for nominal data with multiple raters.
    
    Input: matrix of shape (items, raters) with nominal codes {0,1,2}
    Output: kappa coefficient (-1 to +1, where 1 = perfect agreement)
    
    Note: Fleiss' Kappa only supports nominal data, not ordinal.
    """
    if data_matrix.shape[0] < 2 or data_matrix.shape[1] < 2:
        return np.nan
    
    # Check if there's any variance in the data
    unique_values = np.unique(data_matrix)
    if len(unique_values) < 2:
        return 1.0  # Perfect agreement (no variance)
    
    n_items, n_raters = data_matrix.shape
    n_categories = 3  # 0=Unknown, 1=No, 2=Yes
    
    # Build count matrix: each row = counts of each category for that item
    # Format required for Fleiss' Kappa calculation
    count_matrix = np.zeros((n_items, n_categories), dtype=float)
    for i in range(n_items):
        for r in range(n_raters):
            category = int(data_matrix[i, r])
            if 0 <= category < n_categories:
                count_matrix[i, category] += 1
    
    # Fleiss' Kappa formula
    # p_bar = overall proportion of agreements
    # p_e = expected agreement by chance
    # kappa = (p_bar - p_e) / (1 - p_e)
    
    # Proportion of each category across all ratings
    n_total = n_items * n_raters
    p_j = np.sum(count_matrix, axis=0) / n_total  # Proportion of each category
    
    # Expected agreement by chance
    p_e = np.sum(p_j ** 2)
    
    # Observed agreement for each item
    p_i = (np.sum(count_matrix * (count_matrix - 1), axis=1) / (n_raters * (n_raters - 1)))
    p_bar = np.mean(p_i)
    
    # Fleiss' Kappa
    if p_e >= 1.0:
        return np.nan  # Can't compute kappa if chance agreement is 100%
    
    kappa = (p_bar - p_e) / (1 - p_e)
    return kappa


def compute_percent_agreement(data_matrix: np.ndarray) -> float:
    """Compute simple percent agreement: % of papers where all 3 runs agree."""
    if data_matrix.shape[0] == 0:
        return np.nan
    agreement = np.all(data_matrix == data_matrix[:, [0]], axis=1)
    return np.mean(agreement)


def compute_disagreement_breakdown(data_matrix: np.ndarray) -> Dict:
    """
    Analyze disagreement patterns for tri-state data.
    
    Encoding assumed: 1=No, 2=Unknown, 3=Yes (ordinal encoding)
    
    Returns breakdown of:
    - Yes↔No conflicts (definitive errors)
    - Yes/No↔Unknown (honest uncertainty)
    """
    if data_matrix.shape[0] == 0 or data_matrix.shape[1] < 2:
        return {'definitive_errors': 0, 'honest_uncertainty': 0, 'total_pairs': 0}
    
    n_papers, n_raters = data_matrix.shape
    definitive_errors = 0
    honest_uncertainty = 0
    total_pairs = 0
    
    # Compare all pairs of raters for each paper
    for i in range(n_papers):
        values = data_matrix[i]
        # Compare each unique pair of raters
        for a in range(n_raters):
            for b in range(a + 1, n_raters):
                val_a, val_b = values[a], values[b]
                if val_a != val_b:
                    total_pairs += 1
                    # Definitive error: 1↔3 (No↔Yes)
                    if (val_a == 1 and val_b == 3) or (val_a == 3 and val_b == 1):
                        definitive_errors += 1
                    # Honest uncertainty: 1↔2 or 2↔3 (No↔Unknown or Unknown↔Yes)
                    elif (val_a == 1 and val_b == 2) or (val_a == 2 and val_b == 1) or \
                         (val_a == 2 and val_b == 3) or (val_a == 3 and val_b == 2):
                        honest_uncertainty += 1
    
    return {
        'definitive_errors': definitive_errors,
        'honest_uncertainty': honest_uncertainty,
        'total_pairs': total_pairs
    }


def compute_paper_level_consistency(all_papers: List[Dict[int, Dict]], paper_ids: List[int], 
                                     fields: List[str], encoding: str = 'nominal') -> np.ndarray:
    """Compute per-paper consistency: % of fields where all 3 runs agreed."""
    n_fields = len(fields)
    paper_scores = np.zeros(len(paper_ids))
    
    for i, paper_id in enumerate(paper_ids):
        agreements = 0
        for field in fields:
            values = [all_papers[j][paper_id][encoding].get(field, 0) for j in range(len(all_papers))]
            if len(set(values)) == 1:  # All three identical
                agreements += 1
        paper_scores[i] = agreements / n_fields
    
    return paper_scores


def bootstrap_confidence_interval_fast(
    all_papers: List[Dict[int, Dict]],
    paper_ids: List[int],
    fields: List[str],
    n_boot: int = 1000,
    ci_level: float = 0.95,
    seed: Optional[int] = None,
    alpha_level: str = 'nominal'
) -> Tuple[float, Tuple[float, float]]:
    """
    Compute bootstrap CI for mean Krippendorff's Alpha (FAST, in-memory).
    """
    if seed is not None:
        np.random.seed(seed)
    
    n_papers = len(paper_ids)
    alphas = []
    
    for b in range(n_boot):
        # Resample paper indices with replacement
        boot_indices = np.random.choice(n_papers, size=n_papers, replace=True)
        boot_paper_ids = [paper_ids[i] for i in boot_indices]
        
        # Compute mean alpha for this bootstrap sample
        boot_alphas = []
        for field in fields:
            # Build matrix for this field from bootstrapped papers
            matrix = np.zeros((len(boot_paper_ids), 3), dtype=int)
            for i, pid in enumerate(boot_paper_ids):
                for j in range(len(all_papers)):
                    matrix[i, j] = all_papers[j][pid][alpha_level].get(field, 0)
            alpha = compute_krippendorff_alpha(matrix, level=alpha_level)
            if not np.isnan(alpha):
                boot_alphas.append(alpha)
        
        if len(boot_alphas) > 0:
            alphas.append(np.mean(boot_alphas))
    
    if len(alphas) == 0:
        return np.nan, (np.nan, np.nan)
    
    point_estimate = np.mean(alphas)
    lower = np.percentile(alphas, (1 - ci_level) / 2 * 100)
    upper = np.percentile(alphas, (1 + ci_level) / 2 * 100)
    
    return point_estimate, (lower, upper)


# ============================================================================
# STRATIFIED ANALYSIS
# ============================================================================
# Add this to analyze_stratum() function to show what's actually in the data:


def analyze_stratum(all_papers: List[Dict[int, Dict]], paper_ids: List[int], 
                   fields: List[str], stratum_name: str, 
                   n_bootstrap: int = 1000, use_bootstrap: bool = True,
                   compute_fleiss: bool = False) -> Dict:
    """Run full analysis on a specific stratum of papers."""
    print(f"  Analyzing {stratum_name} ({len(paper_ids)} papers)...")
    
    if len(paper_ids) == 0:
        return {
            'stratum': stratum_name,
            'n_papers': 0,
            'nominal_alpha': np.nan, 'ordinal_alpha': np.nan, 'fleiss_kappa': np.nan,
            'nominal_ci': (np.nan, np.nan), 'ordinal_ci': (np.nan, np.nan),
            'percent_agreement': np.nan,
            'field_results': pd.DataFrame(),
            'paper_scores_nominal': np.array([]),
            'disagreement_breakdown': {}
        }
    
    # Per-field analysis (ALL IN-MEMORY)
    field_results = []
    
    # NEW: Track value distributions for diagnostics
    value_distribution = {field: {'2': 0, '1': 0, '0': 0} for field in fields}  # Yes/No/Unknown counts
    
    for field in fields:
        # Build nominal matrix (0/1/2)
        nominal_matrix = np.zeros((len(paper_ids), 3), dtype=int)
        # Build ordinal matrix (1/2/3)
        ordinal_matrix = np.zeros((len(paper_ids), 3), dtype=int)
        
        for i, paper_id in enumerate(paper_ids):
            for j, db_papers in enumerate(all_papers):
                val = db_papers[paper_id]['nominal'].get(field, 0)
                nominal_matrix[i, j] = val
                ordinal_matrix[i, j] = db_papers[paper_id]['ordinal'].get(field, 0)
                
                # Track distribution (count unique values per run)
                value_distribution[field][str(val)] += 1
        
        nominal_alpha = compute_krippendorff_alpha(nominal_matrix, level='nominal')
        ordinal_alpha = compute_krippendorff_alpha(ordinal_matrix, level='ordinal')
        fleiss_k = compute_fleiss_kappa(nominal_matrix) if compute_fleiss else np.nan
        pct_agree = compute_percent_agreement(nominal_matrix)
        
        # NEW: Calculate % Unknown for this field
        total_values = len(paper_ids) * 3  # papers × runs
        unknown_count = value_distribution[field]['0']
        unknown_pct = (unknown_count / total_values * 100) if total_values > 0 else 0
        
        # Disagreement breakdown (using ordinal encoding for meaningful distances)
        breakdown = compute_disagreement_breakdown(ordinal_matrix)
        
        field_results.append({
            'field': field,
            'nominal_alpha': nominal_alpha,
            'ordinal_alpha': ordinal_alpha,
            'fleiss_kappa': fleiss_k,
            'percent_agreement': pct_agree,
            'n_papers': len(paper_ids),
            'unknown_pct': unknown_pct,  # NEW
            'definitive_errors': breakdown['definitive_errors'],
            'honest_uncertainty': breakdown['honest_uncertainty'],
            'total_pairs': breakdown['total_pairs'],
        })
    
    results_df = pd.DataFrame(field_results)
    
    # Overall alphas are MEAN of per-field alphas
    nominal_alphas = [r['nominal_alpha'] for r in field_results if not np.isnan(r['nominal_alpha'])]
    ordinal_alphas = [r['ordinal_alpha'] for r in field_results if not np.isnan(r['ordinal_alpha'])]
    fleiss_kappas = [r['fleiss_kappa'] for r in field_results if not np.isnan(r['fleiss_kappa'])]
    
    overall_nominal = np.mean(nominal_alphas) if len(nominal_alphas) > 0 else np.nan
    overall_ordinal = np.mean(ordinal_alphas) if len(ordinal_alphas) > 0 else np.nan
    overall_fleiss = np.mean(fleiss_kappas) if len(fleiss_kappas) > 0 else np.nan
    
    # Bootstrap CIs (optional)
    nominal_ci = (np.nan, np.nan)
    ordinal_ci = (np.nan, np.nan)
    if use_bootstrap and len(paper_ids) >= 10 and n_bootstrap > 0:
        print(f"    Bootstrapping {n_bootstrap} samples for confidence intervals...")
        _, nominal_ci = bootstrap_confidence_interval_fast(
            all_papers, paper_ids, fields, n_boot=n_bootstrap, alpha_level='nominal'
        )
        _, ordinal_ci = bootstrap_confidence_interval_fast(
            all_papers, paper_ids, fields, n_boot=n_bootstrap, alpha_level='ordinal'
        )
    
    # Overall percent agreement
    overall_pct = results_df['percent_agreement'].mean() if not results_df.empty else np.nan
    
    # Paper-level consistency (nominal encoding)
    print(f"    Computing paper-level consistency scores...")
    paper_scores = compute_paper_level_consistency(all_papers, paper_ids, fields, encoding='nominal')
    
    # Aggregate disagreement breakdown across all fields
    total_definitive = results_df['definitive_errors'].sum()
    total_uncertainty = results_df['honest_uncertainty'].sum()
    total_pairs = results_df['total_pairs'].sum()
    
    return {
        'stratum': stratum_name,
        'n_papers': len(paper_ids),
        'nominal_alpha': overall_nominal,
        'ordinal_alpha': overall_ordinal,
        'fleiss_kappa': overall_fleiss,
        'nominal_ci': nominal_ci,
        'ordinal_ci': ordinal_ci,
        'percent_agreement': overall_pct,
        'field_results': results_df,
        'paper_scores': paper_scores,
        'disagreement_breakdown': {
            'definitive_errors': total_definitive,
            'honest_uncertainty': total_uncertainty,
            'total_pairs': total_pairs,
            'definitive_pct': (total_definitive / total_pairs * 100) if total_pairs > 0 else 0,
            'uncertainty_pct': (total_uncertainty / total_pairs * 100) if total_pairs > 0 else 0
        }
    }


def run_stratified_analysis(all_papers: List[Dict[int, Dict]], fields: List[str], 
                           n_bootstrap: int = 1000, use_bootstrap: bool = True,
                           compute_fleiss: bool = False) -> Dict:
    """
    Run analysis stratified by off-topic status.
    
    NEW STRATIFICATION LOGIC:
    - on_topic_only: Papers where is_offtopic != Yes in AT LEAST ONE run
    - off_topic_only: Papers where is_offtopic == Yes in ALL 3 runs
    """
    print(f"Analyzing {len(fields)} fields...")
    
    # Get paper IDs from first database
    all_paper_ids = list(all_papers[0].keys())
    
    # NEW: Stratify by off-topic status across ALL 3 runs
    on_topic_ids = []
    off_topic_ids = []
    
    for paper_id in all_paper_ids:
        # Check is_offtopic status across all 3 runs
        # Encoding: 2=Yes (off-topic), 1=No (on-topic), 0=Unknown
        offtopic_values = [
            all_papers[run_idx][paper_id]['nominal'].get('is_offtopic', 0)
            for run_idx in range(len(all_papers))
        ]
        
        # "Always off-topic": All 3 runs say Yes (2)
        if all(val == 2 for val in offtopic_values):
            off_topic_ids.append(paper_id)
        # "On-topic at least once": At least one run says No (1) or Unknown (0)
        else:
            on_topic_ids.append(paper_id)
    
    print(f"  Stratification: {len(on_topic_ids)} on-topic (at least once), "
          f"{len(off_topic_ids)} always off-topic")
    
    strata = {
        'all_papers': all_paper_ids,
        'on_topic_only': on_topic_ids,
        'off_topic_only': off_topic_ids
    }
    
    results = {}
    for stratum_name, stratum_ids in strata.items():
        results[stratum_name] = analyze_stratum(
            all_papers, stratum_ids, fields, stratum_name, 
            n_bootstrap=n_bootstrap, use_bootstrap=use_bootstrap,
            compute_fleiss=compute_fleiss
        )
    
    return results

# ============================================================================
# OUTPUT
# ============================================================================

def format_ci(ci: Tuple[float, float]) -> str:
    """Format confidence interval for display."""
    if np.isnan(ci[0]) or np.isnan(ci[1]):
        return "[N/A, N/A]"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"

def print_summary(results: Dict, compute_fleiss: bool = False):
    """Print human-readable summary to console."""
    print("\n" + "="*70)
    print("CLASSIFICATION CONSISTENCY ANALYSIS - SUMMARY")
    print("="*70)
    
    for stratum_name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[stratum_name]
        if s['n_papers'] == 0:
            continue
            
        print(f"\n📊 {stratum_name.upper().replace('_', ' ')} ({s['n_papers']} papers)")
        print(f"   Nominal α (equal distances): {s['nominal_alpha']:.3f} {format_ci(s['nominal_ci'])}")
        print(f"   Ordinal α (Unknown intermediate): {s['ordinal_alpha']:.3f} {format_ci(s['ordinal_ci'])}")
        if compute_fleiss and not np.isnan(s['fleiss_kappa']):
            print(f"   Fleiss' κ (nominal only): {s['fleiss_kappa']:.3f}")
        print(f"   Percent Agreement: {s['percent_agreement']*100:.1f}%")
        
        if not s['field_results'].empty:
            # Group by category
            df = s['field_results']
            
            print(f"\n   📋 CONSISTENCY BY CATEGORY:")
            
            # Main classification fields
            main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
            main_df = df[df['field'].isin(main_fields)]
            if not main_df.empty:
                print(f"   ┌─ Main Classification ({len(main_df)} fields):")
                # In the category summary sections, replace the separate mean/range lines with:
                print(f"   │  Mean Nominal α: {main_df['nominal_alpha'].mean():.3f}  [Range: {main_df['nominal_alpha'].min():.3f}–{main_df['nominal_alpha'].max():.3f}]")
                print(f"   │  Mean Ordinal α: {main_df['ordinal_alpha'].mean():.3f}  [Range: {main_df['ordinal_alpha'].min():.3f}–{main_df['ordinal_alpha'].max():.3f}]")
                # Show weakest field by ordinal alpha
                weakest = main_df.loc[main_df['ordinal_alpha'].idxmin()]
                print(f"   │  Weakest: {weakest['field']} (Nominal α={weakest['nominal_alpha']:.3f}, Ordinal α={weakest['ordinal_alpha']:.3f})")
                print(f"   │  Mean % Unknown: {main_df['unknown_pct'].mean():.1f}%")
            
            # Feature fields
            feature_fields = [f for f in df['field'].unique() 
                            if f not in main_fields + ['is_offtopic'] + 
                            ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                             'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                             'dl_other', 'hybrid', 'available_dataset']]
            feature_df = df[df['field'].isin(feature_fields)]
            if not feature_df.empty:
                print(f"   ├─ Features ({len(feature_df)} fields):")
                # In the category summary sections, replace the separate mean/range lines with:
                print(f"   │  Mean Nominal α: {feature_df['nominal_alpha'].mean():.3f}  [Range: {feature_df['nominal_alpha'].min():.3f}–{feature_df['nominal_alpha'].max():.3f}]")
                print(f"   │  Mean Ordinal α: {feature_df['ordinal_alpha'].mean():.3f}  [Range: {feature_df['ordinal_alpha'].min():.3f}–{feature_df['ordinal_alpha'].max():.3f}]")
                weakest = feature_df.loc[feature_df['ordinal_alpha'].idxmin()]
                print(f"   │  Weakest: {weakest['field']} (Nominal α={weakest['nominal_alpha']:.3f}, Ordinal α={weakest['ordinal_alpha']:.3f})")
                print(f"   │  Mean % Unknown: {feature_df['unknown_pct'].mean():.1f}%")
            
            # Technique fields
            technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                               'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                               'dl_other', 'hybrid', 'available_dataset']
            technique_df = df[df['field'].isin(technique_fields)]
            if not technique_df.empty:
                print(f"   └─ Techniques ({len(technique_df)} fields):")
                # In the category summary sections, replace the separate mean/range lines with:
                print(f"      Mean Nominal α: {technique_df['nominal_alpha'].mean():.3f}  [Range: {technique_df['nominal_alpha'].min():.3f}–{technique_df['nominal_alpha'].max():.3f}]")
                print(f"      Mean Ordinal α: {technique_df['ordinal_alpha'].mean():.3f}  [Range: {technique_df['ordinal_alpha'].min():.3f}–{technique_df['ordinal_alpha'].max():.3f}]")
                weakest = technique_df.loc[technique_df['ordinal_alpha'].idxmin()]
                print(f"      Weakest: {weakest['field']} (Nominal α={weakest['nominal_alpha']:.3f}, Ordinal α={weakest['ordinal_alpha']:.3f})")
                print(f"      Mean % Unknown: {technique_df['unknown_pct'].mean():.1f}%")
        
        if len(s['paper_scores']) > 0:
            print(f"   Paper-level consistency: {np.mean(s['paper_scores'])*100:.1f}% (mean)")
            print(f"   Range: [{np.min(s['paper_scores'])*100:.1f}%, {np.max(s['paper_scores'])*100:.1f}%]")
        
        # Disagreement breakdown for on-topic (the important stratum)
        if stratum_name == 'on_topic_only' and s['disagreement_breakdown']['total_pairs'] > 0:
            bd = s['disagreement_breakdown']
            print(f"\n🔍 DISAGREEMENT BREAKDOWN - On-topic papers:")
            print(f"   Total rater pairs examined: {bd['total_pairs']:,}")
            print(f"   Yes↔No conflicts (definitive errors): {bd['definitive_errors']} ({bd['definitive_pct']:.1f}%)")
            print(f"   Yes/No↔Unknown (honest uncertainty): {bd['honest_uncertainty']} ({bd['uncertainty_pct']:.1f}%)")
            if bd['definitive_pct'] < 5:
                print(f"   ✓ Good: Most disagreements are uncertainty, not definitive errors")
            elif bd['definitive_pct'] < 15:
                print(f"   ⚠ Moderate: Some definitive errors mixed with uncertainty")
            else:
                print(f"   ✗ Concerning: High rate of definitive contradictions")
        
        # Show ALL fields sorted by ordinal alpha (best to worst) for on-topic, with BOTH metrics
        if stratum_name == 'on_topic_only' and not s['field_results'].empty:
            print(f"\n📋 ALL FIELDS - On-topic papers (grouped by category, sorted by ordinal α):")
            
            # Define field groups
            main_fields = ['is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
            technique_fields = ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                               'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                               'dl_other', 'hybrid', 'available_dataset']
            
            # Helper to print a grouped section with BOTH metrics
            def print_group(label, field_list, df):
                group_df = df[df['field'].isin(field_list)].sort_values('ordinal_alpha', ascending=False)
                if group_df.empty:
                    return
                print(f"\n   {label}:")
                for _, row in group_df.iterrows():
                    nominal = row['nominal_alpha']
                    ordinal = row['ordinal_alpha']
                    agree = row['percent_agreement']*100
                    unknown = row['unknown_pct']
                    # Visual bar for ordinal alpha (primary metric)
                    bar_len = int(max(0, min(20, (ordinal + 1) * 10)))
                    bar = '█' * bar_len + '░' * (20 - bar_len)
                    fleiss_str = f"  κ={row['fleiss_kappa']:.3f}" if compute_fleiss and not np.isnan(row['fleiss_kappa']) else ""
                    # Show both alphas, with fixed-width diff marker for alignment
                    diff = ordinal - nominal
                    if diff > 0.05:
                        diff_marker = " ↑"
                    elif diff < -0.05:
                        diff_marker = " ↓"
                    else:
                        diff_marker = "  "  # Two spaces to maintain column alignment
                    print(f"      {row['field']:25s} Nom.α={nominal:6.3f}  Ord.α={ordinal:6.3f}{diff_marker}{fleiss_str} {bar}  agree={agree:5.1f}%  ❔={unknown:5.1f}%")

            # Print each group
            print_group("┌─ Main Classification", main_fields, s['field_results'])
            print_group("├─ Features", [f for f in s['field_results']['field'].unique() 
                                      if f not in main_fields + ['is_offtopic'] + technique_fields], 
                       s['field_results'])
            print_group("└─ Techniques", technique_fields, s['field_results'])
    
    # Interpretation guide (use ordinal alpha for on-topic as it's more meaningful)
    print(f"\n📋 INTERPRETATION GUIDE")
    alpha = results['on_topic_only']['ordinal_alpha']
    if not np.isnan(alpha):
        if alpha >= 0.80:
            print(f"   ✓ Strong reliability (research-grade): α = {alpha:.3f}")
        elif alpha >= 0.67:
            print(f"   ⚠ Tentative conclusions acceptable: α = {alpha:.3f}")
        elif alpha >= 0.50:
            print(f"   ⚠ Limited reliability; use with caution: α = {alpha:.3f}")
        else:
            print(f"   ✗ Low reliability; classifications unstable: α = {alpha:.3f}")
    else:
        print(f"   ⚠ Insufficient on-topic papers for reliability assessment")
    
    print("="*70 + "\n")


def save_results(results: Dict, output_path: str, compute_fleiss: bool = False):
    """Save results to CSV and JSON files."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    for stratum_name, stratum_data in results.items():
        if stratum_data['n_papers'] == 0:
            continue
        field_csv = output.with_suffix(f'.{stratum_name}.fields.csv')
        # Sort by ordinal alpha descending for easier inspection
        sorted_df = stratum_data['field_results'].sort_values('ordinal_alpha', ascending=False)
        sorted_df.to_csv(field_csv, index=False, float_format='%.4f')
        print(f"✓ Per-field results ({stratum_name}, sorted by ordinal α) saved to: {field_csv}")
        
        if len(stratum_data['paper_scores']) > 0:
            paper_csv = output.with_suffix(f'.{stratum_name}.papers.csv')
            pd.DataFrame({'consistency_score': stratum_data['paper_scores']}).to_csv(
                paper_csv, index=False, float_format='%.4f')
            print(f"✓ Paper-level scores ({stratum_name}) saved to: {paper_csv}")
    
    # Save summary to JSON
    summary_json = output.with_suffix('.summary.json')
    def convert(obj):
        if isinstance(obj, (np.floating, float)):
            if np.isnan(obj): return None
            return float(obj)
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, dict): return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)): return [convert(v) for v in obj]
        return obj
    
    summary_data = {}
    for stratum_name, stratum_data in results.items():
        summary_data[stratum_name] = {
            'n_papers': stratum_data['n_papers'],
            'nominal_alpha': convert(stratum_data['nominal_alpha']),
            'ordinal_alpha': convert(stratum_data['ordinal_alpha']),
            'fleiss_kappa': convert(stratum_data['fleiss_kappa']) if compute_fleiss else None,
            'nominal_95_ci': convert(stratum_data['nominal_ci']),
            'ordinal_95_ci': convert(stratum_data['ordinal_ci']),
            'percent_agreement': convert(stratum_data['percent_agreement']),
            'paper_level_mean': convert(np.mean(stratum_data['paper_scores'])) if len(stratum_data['paper_scores']) > 0 else None,
            'paper_level_median': convert(np.median(stratum_data['paper_scores'])) if len(stratum_data['paper_scores']) > 0 else None,
            'disagreement_breakdown': convert(stratum_data['disagreement_breakdown'])
        }
        if not stratum_data['field_results'].empty:
            summary_data[stratum_name]['field_nominal_alpha_mean'] = convert(stratum_data['field_results']['nominal_alpha'].mean())
            summary_data[stratum_name]['field_ordinal_alpha_mean'] = convert(stratum_data['field_results']['ordinal_alpha'].mean())
            if compute_fleiss and 'fleiss_kappa' in stratum_data['field_results'].columns:
                summary_data[stratum_name]['field_fleiss_kappa_mean'] = convert(stratum_data['field_results']['fleiss_kappa'].mean())
    
    with open(summary_json, 'w') as f:
        json.dump(summary_data, f, indent=2)
    print(f"✓ Summary metrics saved to: {summary_json}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Analyze classification consistency across 3 ResearchParça runs')
    parser.add_argument('--db1', '--db-1', required=True, help='Path to first database')
    parser.add_argument('--db2', '--db-2', required=True, help='Path to second database')
    parser.add_argument('--db3', '--db-3', required=True, help='Path to third database')
    parser.add_argument('-o', '--output', default='consistency_results', help='Output path prefix')
    parser.add_argument('-b', '--bootstrap', type=int, default=1000, help='Number of bootstrap samples for CI (default: 1000)')
    parser.add_argument('--no-bootstrap', action='store_true', help='Skip bootstrap confidence interval calculation')
    parser.add_argument('--fleiss', action='store_true', help='Also compute Fleiss\' Kappa (nominal only, adds ~10-20s runtime)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for bootstrap (default: 42)')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    args = parser.parse_args()
    
    db_paths = [args.db1, args.db2, args.db3]
    for db in db_paths:
        if not Path(db).exists():
            print(f"Error: Database not found: {db}", file=sys.stderr)
            sys.exit(1)
    
    use_bootstrap = not args.no_bootstrap
    
    if not args.quiet:
        print(f"ResearchParça Consistency Analysis (FINAL v3 - With Fleiss' Kappa)")
        print(f"Databases: {', '.join(db_paths)}")
        print(f"Bootstrap: {'Enabled' if use_bootstrap else 'Disabled'}")
        if use_bootstrap:
            print(f"Bootstrap samples: {args.bootstrap}")
        print(f"Fleiss' Kappa: {'Enabled' if args.fleiss else 'Disabled'}")
    
    # LOAD ALL DATA INTO RAM UPFRONT
    all_papers = load_all_databases(db_paths)
    
    if not args.quiet:
        print(f"\n✓ All data loaded. Starting analysis (no further DB queries)...\n")
    
    # Run stratified analysis (ALL IN-MEMORY)
    results = run_stratified_analysis(all_papers, BOOLEAN_FIELDS, 
                                     n_bootstrap=args.bootstrap, use_bootstrap=use_bootstrap,
                                     compute_fleiss=args.fleiss)
    
    if not args.quiet:
        print_summary(results, compute_fleiss=args.fleiss)
    
    save_results(results, args.output, compute_fleiss=args.fleiss)
    
    if not args.quiet:
        print("✓ Analysis complete.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())