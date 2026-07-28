#!/usr/bin/env python3
# compare_user_vs_ai.py
# v1.3 - Human vs AI Main Set Comparison Script (Stratified)
# Compares a user-annotated DB against an AI-averaged DB.
# v1.3 Updates: Global summary preserved; explicit on/off-topic stratification 
#               using HUMAN annotations; field-level analysis restricted to on-topic.

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

MIN_N_FOR_CI = 10

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
        r = dict(row)
        pid = r['id']
        data = {}
        
        try:
            cert_map = json.loads(r.get('main_certainty')) if r.get('main_certainty') else {}
            if not isinstance(cert_map, dict): cert_map = {}
        except (json.JSONDecodeError, TypeError):
            cert_map = {}
            
        for field in BOOLEAN_FIELDS:
            val = r.get(field)
            data[field] = (val if val in (0, 1) else None, cert_map.get(field, 'solid'))
            
        for json_col, fields in [('features', JSON_FEATURE_FIELDS), ('technique', JSON_TECHNIQUE_FIELDS)]:
            try:
                j_str = r.get(json_col)
                j_data = json.loads(j_str) if j_str else {}
                if j_data is None: j_data = {}
            except (json.JSONDecodeError, TypeError):
                j_data = {}
                
            for field in fields:
                val = j_data.get(field)
                norm_val = 1 if val in (1, True, '1', 'true') else (0 if val in (0, False, '0', 'false') else None)
                data[field] = (norm_val, cert_map.get(f'{json_col}_{field}', 'solid'))
                
        # Store raw values for stratification
        data['_relevance'] = r.get('relevance')
        data['_is_offtopic'] = r.get('is_offtopic')
        
        papers[pid] = data
        
    return papers

# ============================================================================
# COMPARISON ENGINE
# ============================================================================

def classify_comparison(user_val, ai_val, ai_cert):
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
        return 'exact_match_solid' if ai_cert == 'solid' else 'partial_match'

def compute_stratum_stats(ids: List[int], user_data: Dict, ai_data: Dict) -> Dict:
    """Compute comparison statistics for a specific list of paper IDs."""
    global_stats = defaultdict(int)
    field_stats = {f: defaultdict(int) for f in ALL_COMPARISON_FIELDS}
    field_known_counts = {f: 0 for f in ALL_COMPARISON_FIELDS}
    
    # Collect values for Kappa
    field_u_vals = {f: [] for f in ALL_COMPARISON_FIELDS}
    field_a_vals = {f: [] for f in ALL_COMPARISON_FIELDS}
    
    for pid in ids:
        u_row = user_data[pid]
        a_row = ai_data[pid]
        
        for field in ALL_COMPARISON_FIELDS:
            u_val, _ = u_row.get(field, (None, 'solid'))
            a_val, a_cert = a_row.get(field, (None, 'solid'))
            
            cat = classify_comparison(u_val, a_val, a_cert)
            field_stats[field][cat] += 1
            global_stats[cat] += 1
            
            field_u_vals[field].append(u_val)
            field_a_vals[field].append(a_val)
            if u_val is not None and a_val is not None:
                field_known_counts[field] += 1

    field_kappa = {}
    for field in ALL_COMPARISON_FIELDS:
        field_kappa[field] = cohen_kappa_known_only(field_u_vals[field], field_a_vals[field])

    return {
        'global': global_stats,
        'field': field_stats,
        'kappa': field_kappa,
        'known_counts': field_known_counts,
        'n_papers': len(ids)
    }

def run_comparison(user_db_path: str, ai_db_path: str, output_prefix: str):
    print(f"📥 Loading Human DB: {user_db_path}")
    user_data = load_main_set(user_db_path)
    print(f"📥 Loading AI DB:    {ai_db_path}")
    ai_data = load_main_set(ai_db_path)
    
    common_ids = sorted(set(user_data.keys()) & set(ai_data.keys()))
    if not common_ids:
        print("❌ No common paper IDs found between databases.")
        return
        
    print(f"🔍 Comparing {len(common_ids)} papers across {len(ALL_COMPARISON_FIELDS)} fields...")
    
    # Stratify based EXPLICITLY on HUMAN annotation
    on_topic_ids = []
    off_topic_ids = []
    for pid in common_ids:
        # _is_offtopic comes directly from the Human DB
        if user_data[pid].get('_is_offtopic') == 1:
            off_topic_ids.append(pid)
        else:
            on_topic_ids.append(pid)
            
    print(f"📊 Stratification (Human): {len(on_topic_ids)} on-topic, {len(off_topic_ids)} off-topic")
    
    # Compute stats for all three views
    return {
        'overall': compute_stratum_stats(common_ids, user_data, ai_data),
        'on_topic': compute_stratum_stats(on_topic_ids, user_data, ai_data),
        'off_topic': compute_stratum_stats(off_topic_ids, user_data, ai_data),
        'common_ids': common_ids,
        'n_on_topic': len(on_topic_ids),
        'n_off_topic': len(off_topic_ids)
    }

# ============================================================================
# OUTPUT GENERATION
# ============================================================================

def print_stratum_results(res: Dict, stratum_name: str, show_field_level: bool = True) -> Optional[pd.DataFrame]:
    """Print results for a single stratum. Optionally shows field-level breakdown."""
    g = res['global']
    total = sum(g.values())
    if total == 0:
        print(f"\n📊 {stratum_name.upper()} (No data to display)")
        return None

    print(f"\n{'='*90}")
    print(f"📊 {stratum_name.upper()} (Papers: {res['n_papers']:,} | Cells: {total:,})")
    print(f"{'='*90}")
    
    categories = [
        ('exact_match_solid', '✅ Exact Match (Solid AI Certainty)'),
        ('partial_match', '🟡 Partial Match (AI Leans Correctly 60/80%)'),
        ('direct_conflict', '❌ Direct Conflict (AI Y↔N vs Human)'),
        ('ai_overconfident', '⚠️ AI Overconfidence (AI commits, Human Unknown)'),
        ('ai_underconfident', 'ℹ️ AI Underconfidence (AI Unknown, Human commits)'),
        ('ai_conflict_fatal', '💥 AI Internal Conflict (Fatal AI Error)')
    ]
    
    print("\n  📊 OVERALL BREAKDOWN:")
    print("-"*90)
    for key, label in categories:
        count = g.get(key, 0)
        pct = (count / total * 100) if total > 0 else 0
        fmt = format_with_ci(pct, count, total)
        print(f"    {label:<45} {fmt}")
        
    df = None
    if show_field_level:
        print(f"\n  📋 FIELD-LEVEL PERFORMANCE (Sorted by Exact+Partial Match %):")
        print("-"*90)
        field_rows = []
        for f in ALL_COMPARISON_FIELDS:
            fs = res['field'][f]
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
                'Kappa': res['kappa'].get(f, 0.0)
            })
            
        df = pd.DataFrame(field_rows).sort_values('Exact+Partial%', ascending=False)
        for _, r in df.iterrows():
            bar = '█' * int(r['Exact+Partial%']/5) + '░' * (20 - int(r['Exact+Partial%']/5))
            print(f"    {r['Field']:<25} {bar} Exact: {r['Exact+Partial%']:.1f}% | Conflict: {r['Conflict%']:.1f}% | Kappa: {r['Kappa']:.3f}")
        
    return df

def print_results(results: Dict, output_prefix: str):
    # 1. OVERALL (Combines everything, as requested)
    df_overall = print_stratum_results(results['overall'], "Overall (All Papers)", show_field_level=True)
    if df_overall is not None:
        csv_path = f"{output_prefix}_overall_comparison.csv"
        print(f"\n💾 Saving Overall CSV to {csv_path}")
        df_overall.to_csv(csv_path, index=False)
        
    # 2. ON-TOPIC (Primary focus, full field breakdown)
    df_on = print_stratum_results(results['on_topic'], "On-Topic Only (Primary Metric)", show_field_level=True)
    if df_on is not None:
        csv_path = f"{output_prefix}_on_topic_comparison.csv"
        print(f"\n💾 Saving On-Topic CSV to {csv_path}")
        df_on.to_csv(csv_path, index=False)
        
    # 3. OFF-TOPIC (Global only, field-level skipped as fields are null by design)
    print_stratum_results(results['off_topic'], "Off-Topic Only (Global Summary Only)", show_field_level=False)
        
    print("\n✅ Done.")

def generate_latex_table(results: Dict, latex_path: str):
    """Generate LaTeX tables for Overall and On-Topic strata."""
    categories = ['exact_match_solid', 'partial_match', 'direct_conflict', 
                  'ai_overconfident', 'ai_underconfident', 'ai_conflict_fatal']
    labels = {'exact_match_solid': 'Exact Match (Solid)', 'partial_match': 'Partial Match',
              'direct_conflict': 'Direct Conflict', 'ai_overconfident': 'Overconfident',
              'ai_underconfident': 'Underconfident', 'ai_conflict_fatal': 'AI Internal Conflict'}

    tables = []
    # Generate tables for Overall and On-Topic
    for stratum_key, stratum_label in [('overall', 'Overall'), ('on_topic', 'On-Topic')]:
        res = results[stratum_key]
        g = res['global']
        total = sum(g.values())
        if total == 0: continue
        
        rows = []
        for cat in categories:
            count = g.get(cat, 0)
            pct = count / total * 100 if total else 0
            rows.append({'Category': labels[cat], 'Count': count, 'Percentage': f"{pct:.2f}\\%"})
            
        df = pd.DataFrame(rows)
        # Use booktabs compatible format
        latex_str = df.to_latex(index=False, escape=True, float_format="%.2f", column_format="lcc")
        
        table_str = f"""
\\begin{{table}}[htbp]
\\centering
\\caption{{Human vs AI Comparison Results: {stratum_label} Papers ({res['n_papers']:,} papers, {total:,} cells)}}
\\label{{tab:comparison_{stratum_key}}}
\\resizebox{{\\columnwidth}}{{!}}{{%
{latex_str.replace('table', '')}
}}
\\end{{table}}
"""
        tables.append(table_str)
        
    with open(latex_path, 'w', encoding='utf-8') as f:
        f.write("% Human vs AI Comparison Results (Stratified)\n")
        f.write("% Requires: graphicx package for \\resizebox\n\n")
        for t in tables:
            f.write(t)
            f.write("\n")
    print(f"📄 LaTeX tables saved to {latex_path}")

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
    if res is None: return 1
        
    print_results(res, args.output)
    
    try:
        generate_latex_table(res, f"{args.output}_summary.tex")
    except Exception as e:
        print(f"⚠️ LaTeX export failed: {e}")
        
    return 0

if __name__ == '__main__':
    sys.exit(main())