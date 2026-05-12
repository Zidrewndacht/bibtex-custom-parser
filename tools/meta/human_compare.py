#!/usr/bin/env python3
# compare_user_vs_ai.py
# v1.2 - Human vs AI Main Set Comparison Script
# Compares a user-annotated DB against an AI-averaged DB.

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats

# ============================================================================
# CONFIGURATION
# ============================================================================
BOOLEAN_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray'
]

JSON_FEATURE_FIELDS = [
    'tracks', 'holes', 'bare_pcb_other',
    'solder_insufficient', 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
    'missing_component', 'wrong_component', 'orientation', 'component_other', 'cosmetic'
]

JSON_TECHNIQUE_FIELDS = [
    'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
    'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
    'dl_other', 'hybrid', 'available_dataset'
]

ALL_COMPARISON_FIELDS = BOOLEAN_FIELDS + JSON_FEATURE_FIELDS + JSON_TECHNIQUE_FIELDS

MIN_N_FOR_CI = 100

# ============================================================================
# STATISTICAL HELPERS
# ============================================================================

def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    if n == 0: return 0.0, 100.0
    z = stats.norm.ppf((1 + confidence) / 2)
    p_hat = successes / n
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2*n)) / denominator
    margin = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*n)) / n) / denominator
    return max(0, (centre - margin) * 100), min(100, (centre + margin) * 100)

def format_with_ci(pct: float, count: int, total: int, min_n: int = MIN_N_FOR_CI) -> str:
    if total < min_n: return f"{pct:.2f}% ({count:,})"
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"

def cohen_kappa_known_only(user_vals: List[int], ai_vals: List[int]) -> float:
    """Compute Cohen's Kappa only on cells where BOTH are Known (0 or 1). Ignores mutual Unknowns."""
    mask = [(u is not None) and (a is not None) for u, a in zip(user_vals, ai_vals)]
    u_known = [v for v, m in zip(user_vals, mask) if m]
    a_known = [v for v, m in zip(ai_vals, mask) if m]
    
    if len(u_known) < 2: return 0.0
    
    # Build confusion matrix
    matrix = np.zeros((2, 2))
    for u, a in zip(u_known, a_known):
        matrix[int(u)][int(a)] += 1
        
    total = matrix.sum()
    p0 = np.diag(matrix).sum() / total
    pe = (matrix.sum(axis=0) / total * matrix.sum(axis=1) / total).sum()
    
    return (p0 - pe) / (1 - pe) if pe < 1 else 1.0

# ============================================================================
# DATA LOADING
# ============================================================================

def load_main_set(db_path: str) -> Dict[int, Dict[str, Tuple]]:
    """Loads main set values and AI certainty map from DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    papers = {}
    for row in rows:
        r = dict(row)  # FIX: Convert Row to standard dict for safe .get() usage
        pid = r['id']
        data = {}
        
        # Load certainty map
        try:
            cert_map = json.loads(r.get('main_certainty')) if r.get('main_certainty') else {}
            if not isinstance(cert_map, dict): cert_map = {}
        except (json.JSONDecodeError, TypeError):
            cert_map = {}
            
        # Direct boolean fields
        for field in BOOLEAN_FIELDS:
            val = r.get(field)
            # Normalize: 1->1, 0->0, None->None
            data[field] = (val if val in (0, 1) else None, cert_map.get(field, 'solid'))
            
        # JSON fields (features & technique)
        for json_col, fields in [('features', JSON_FEATURE_FIELDS), ('technique', JSON_TECHNIQUE_FIELDS)]:
            try:
                j_str = r.get(json_col)
                j_data = json.loads(j_str) if j_str else {}
                if j_data is None: j_data = {}
            except (json.JSONDecodeError, TypeError):
                j_data = {}
                
            for field in fields:
                val = j_data.get(field)
                # Normalize JSON booleans/integers to 1, 0, or None
                norm_val = 1 if val in (1, True, '1', 'true') else (0 if val in (0, False, '0', 'false') else None)
                data[field] = (norm_val, cert_map.get(f'{json_col}_{field}', 'solid'))
                
        # Metadata for stratification
        data['_relevance'] = r.get('relevance')
        data['_is_offtopic'] = r.get('is_offtopic')
        
        papers[pid] = data
        
    return papers

# ============================================================================
# COMPARISON ENGINE
# ============================================================================

def classify_comparison(user_val, ai_val, ai_cert):
    """
    Returns semantic comparison category.
    user_val, ai_val: 1 (Y), 0 (N), None (U)
    ai_cert: 'solid', '80', '60', 'conflict'
    """
    # 1. AI Internal Conflict (Fatal, overrides everything)
    if ai_cert == 'conflict':
        return 'ai_conflict_fatal'
        
    u_known = user_val is not None
    a_known = ai_val is not None
    
    if u_known and a_known:
        if user_val == ai_val:
            return 'exact_match_solid' if ai_cert == 'solid' else 'partial_match'
        else:
            return 'direct_conflict'
    elif not u_known and a_known:
        return 'ai_overconfident'
    elif u_known and not a_known:
        return 'ai_underconfident'
    else:
        # Both Unknown
        return 'exact_match_solid' if ai_cert == 'solid' else 'partial_match'

def run_comparison(user_db_path: str, ai_db_path: str, output_prefix: str):
    print(f"📥 Loading Human DB: {user_db_path}")
    user_data = load_main_set(user_db_path)
    print(f"📥 Loading AI DB:    {ai_db_path}")
    ai_data = load_main_set(ai_db_path)
    
    # Align papers
    common_ids = sorted(set(user_data.keys()) & set(ai_data.keys()))
    if not common_ids:
        print("❌ No common paper IDs found between databases.")
        return
        
    print(f"🔍 Comparing {len(common_ids)} papers across {len(ALL_COMPARISON_FIELDS)} fields...")
    
    # Aggregation structures
    global_stats = defaultdict(int)
    field_stats = {f: defaultdict(int) for f in ALL_COMPARISON_FIELDS}
    field_kappa = {}
    field_known_counts = {f: 0 for f in ALL_COMPARISON_FIELDS}
    
    # Stratification lists
    rel_bins = {
        'Very Low (0-1)': [], 'Low (2-3)': [], 'Medium (4-5)': [], 
        'High (6-7)': [], 'Very High (8-10)': []
    }
    off_topic_papers, on_topic_papers = [], []
    
    for pid in common_ids:
        u_row = user_data[pid]
        a_row = ai_data[pid]
        
        # Stratify paper
        is_ot = u_row.get('_is_offtopic')
        if is_ot == 1: off_topic_papers.append(pid)
        else: on_topic_papers.append(pid)
        
        rel = u_row.get('_relevance')
        if rel is not None:
            if 0 <= rel <= 1: rel_bins['Very Low (0-1)'].append(pid)
            elif 2 <= rel <= 3: rel_bins['Low (2-3)'].append(pid)
            elif 4 <= rel <= 5: rel_bins['Medium (4-5)'].append(pid)
            elif 6 <= rel <= 7: rel_bins['High (6-7)'].append(pid)
            elif 8 <= rel <= 10: rel_bins['Very High (8-10)'].append(pid)
            
        # Compare fields
        for field in ALL_COMPARISON_FIELDS:
            u_val, _ = u_row.get(field, (None, 'solid'))
            a_val, a_cert = a_row.get(field, (None, 'solid'))
            
            cat = classify_comparison(u_val, a_val, a_cert)
            field_stats[field][cat] += 1
            global_stats[cat] += 1
            
            if u_val is not None and a_val is not None:
                field_known_counts[field] += 1

    # Compute Kappa per field
    for field in ALL_COMPARISON_FIELDS:
        u_list, a_list = [], []
        for pid in common_ids:
            u_val, _ = user_data[pid].get(field, (None, 'solid'))
            a_val, _ = ai_data[pid].get(field, (None, 'solid'))
            u_list.append(u_val)
            a_list.append(a_val)
        field_kappa[field] = cohen_kappa_known_only(u_list, a_list)

    return {
        'global': global_stats,
        'field': field_stats,
        'kappa': field_kappa,
        'known_counts': field_known_counts,
        'common_ids': common_ids,
        'strata': {
            'off_topic': off_topic_papers,
            'on_topic': on_topic_papers,
            'relevance': rel_bins
        }
    }

# ============================================================================
# OUTPUT GENERATION
# ============================================================================

def print_results(results: Dict, output_prefix: str):
    g = results['global']
    total = sum(g.values())
    print("\n" + "="*90)
    print("HUMAN vs AI MAIN SET COMPARISON (ResearchParça v1.2)")
    print(f"Total Cells Compared: {total:,} | Papers: {len(results['common_ids']):,}")
    print("="*90)
    
    categories = [
        ('exact_match_solid', '✅ Exact Match (Solid AI Certainty)'),
        ('partial_match', '🟡 Partial Match (AI Leans Correctly 60/80%)'),
        ('direct_conflict', '❌ Direct Conflict (AI Y↔N vs Human)'),
        ('ai_overconfident', '⚠️ AI Overconfidence (AI commits, Human Unknown)'),
        ('ai_underconfident', 'ℹ️ AI Underconfidence (AI Unknown, Human commits)'),
        ('ai_conflict_fatal', '💥 AI Internal Conflict (Fatal AI Error)')
    ]
    
    print("\n📊 OVERALL BREAKDOWN:")
    print("-"*90)
    for key, label in categories:
        count = g.get(key, 0)
        pct = (count / total * 100) if total > 0 else 0
        fmt = format_with_ci(pct, count, total)
        print(f"  {label:<45} {fmt}")
        
    print("\n📋 FIELD-LEVEL PERFORMANCE (Sorted by Exact Match %):")
    print("-"*90)
    field_rows = []
    for f in ALL_COMPARISON_FIELDS:
        fs = results['field'][f]
        f_total = sum(fs.values())
        if f_total == 0: continue
        exact = fs.get('exact_match_solid', 0) + fs.get('partial_match', 0)
        exact_pct = exact / f_total * 100
        field_rows.append({
            'Field': f,
            'Exact+Partial%': exact_pct,
            'Conflict%': fs.get('direct_conflict', 0)/f_total*100,
            'Overconf%': fs.get('ai_overconfident', 0)/f_total*100,
            'Underconf%': fs.get('ai_underconfident', 0)/f_total*100,
            'AI_Fatal%': fs.get('ai_conflict_fatal', 0)/f_total*100,
            'Kappa': results['kappa'].get(f, 0.0)
        })
        
    df = pd.DataFrame(field_rows).sort_values('Exact+Partial%', ascending=False)
    for _, r in df.iterrows():
        bar = '█' * int(r['Exact+Partial%']/5) + '░' * (20 - int(r['Exact+Partial%']/5))
        print(f"  {r['Field']:<25} {bar} Exact: {r['Exact+Partial%']:.1f}% | Conflict: {r['Conflict%']:.1f}% | Kappa: {r['Kappa']:.3f}")
        
    print(f"\n💾 Saving CSV to {output_prefix}_comparison.csv")
    df.to_csv(f"{output_prefix}_comparison.csv", index=False)
    print("✅ Done.")

def generate_latex_table(results: Dict, latex_path: str):
    df_rows = []
    g = results['global']
    total = sum(g.values())
    categories = ['exact_match_solid', 'partial_match', 'direct_conflict', 
                  'ai_overconfident', 'ai_underconfident', 'ai_conflict_fatal']
    labels = {'exact_match_solid': 'Exact Match', 'partial_match': 'Partial Match',
              'direct_conflict': 'Direct Conflict', 'ai_overconfident': 'Overconfident',
              'ai_underconfident': 'Underconfident', 'ai_conflict_fatal': 'AI Internal Conflict'}
              
    for cat in categories:
        count = g.get(cat, 0)
        pct = count / total * 100 if total else 0
        df_rows.append({'Category': labels[cat], 'Count': count, 'Percentage': f"{pct:.2f}\\%"})
        
    df = pd.DataFrame(df_rows)
    latex_str = df.to_latex(index=False, escape=True, float_format="%.2f")
    with open(latex_path, 'w') as f:
        f.write("% Human vs AI Comparison Results\n")
        f.write(latex_str)
    print(f"📄 LaTeX table saved to {latex_path}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Compare Human vs AI classifications')
    parser.add_argument('--user-db', required=True, help='Path to User-annotated DB')
    parser.add_argument('--ai-db', required=True, help='Path to AI-averaged DB')
    parser.add_argument('-o', '--output', default='human_vs_ai_comparison')
    args = parser.parse_args()
    
    if not Path(args.user_db).exists() or not Path(args.ai_db).exists():
        print("❌ Database file not found."); sys.exit(1)
        
    res = run_comparison(args.user_db, args.ai_db, args.output)
    print_results(res, args.output)
    
    try:
        generate_latex_table(res, f"{args.output}_summary.tex")
    except Exception as e:
        print(f"⚠️ LaTeX export failed: {e}")
        
    return 0

if __name__ == '__main__':
    sys.exit(main())