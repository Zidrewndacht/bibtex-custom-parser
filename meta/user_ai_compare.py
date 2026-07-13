#!/usr/bin/env python3
# v1.2_user_vs_ai_comparison.py (v1.2.1 - Certainty-Aware)
# Compares user-modified main_set data vs AI-averaged main_set data across two separate SQLite DBs.
# NEW: Explicitly handles AI internal certainty/conflicts from main_certainty.

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
MAIN_BOOL_FIELDS = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', 'verified']
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
COMPARISON_FIELDS = MAIN_BOOL_FIELDS + JSON_FEATURE_FIELDS + JSON_TECHNIQUE_FIELDS

RELEVANCE_BINS = [
    (0, 1, "Very Low (0-1)"),
    (2, 3, "Low (2-3)"),
    (4, 5, "Medium (4-5)"),
    (6, 7, "High (6-7)"),
    (8, 10, "Very High (8-10)")
]
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
    lower = max(0, (centre - margin) * 100)
    upper = min(100, (centre + margin) * 100)
    return lower, upper

def format_with_ci(pct: float, count: int, total: int, min_n: int = MIN_N_FOR_CI) -> str:
    if total < min_n:
        return f"{pct:.2f}% ({count:,})"
    lower, upper = wilson_score_interval(count, total)
    return f"{pct:.2f}% [{lower:.2f}%, {upper:.2f}%] ({count:,})"

def normalize_val(val) -> int:
    if val in (1, True, '1', 'true'): return 2
    if val in (0, False, '0', 'false'): return 1
    return 0

def extract_paper_data(row: Dict) -> Dict:
    data = {}
    for f in MAIN_BOOL_FIELDS:
        data[f] = normalize_val(row.get(f))
        
    try:
        feat = json.loads(row.get('features', '{}') or '{}') or {}
    except: feat = {}
    for f in JSON_FEATURE_FIELDS:
        data[f] = normalize_val(feat.get(f))
        
    try:
        tech = json.loads(row.get('technique', '{}') or '{}') or {}
    except: tech = {}
    for f in JSON_TECHNIQUE_FIELDS:
        data[f] = normalize_val(tech.get(f))
        
    rel = row.get('relevance')
    data['_relevance'] = int(rel) if isinstance(rel, (int, float)) else None
    
    # NEW: Parse AI certainty/conflict metadata
    try:
        data['_certainty'] = json.loads(row.get('main_certainty', '{}') or '{}')
        if data['_certainty'] is None: data['_certainty'] = {}
    except: data['_certainty'] = {}
    return data

# ============================================================================
# DATA LOADING & ALIGNMENT
# ============================================================================
def load_comparison_data(user_db_path: str, ai_db_path: str) -> Tuple[Dict[int, Dict], List[int]]:
    print(f"  Loading User DB: {user_db_path}")
    conn_u = sqlite3.connect(user_db_path)
    conn_u.row_factory = sqlite3.Row
    user_rows = {row['id']: dict(row) for row in conn_u.execute("SELECT * FROM papers")}
    conn_u.close()
    
    print(f"  Loading AI DB: {ai_db_path}")
    conn_a = sqlite3.connect(ai_db_path)
    conn_a.row_factory = sqlite3.Row
    ai_rows = {row['id']: dict(row) for row in conn_a.execute("SELECT * FROM papers")}
    conn_a.close()
    
    common_ids = sorted(set(user_rows.keys()) & set(ai_rows.keys()))
    missing_user = set(ai_rows.keys()) - set(user_rows.keys())
    missing_ai = set(user_rows.keys()) - set(ai_rows.keys())
    
    if missing_user: print(f"  ⚠️  {len(missing_user)} papers in AI DB missing from User DB")
    if missing_ai: print(f"  ⚠️  {len(missing_ai)} papers in User DB missing from AI DB")
    
    comparison_data = {}
    for pid in common_ids:
        comparison_data[pid] = {
            'user': extract_paper_data(user_rows[pid]),
            'ai': extract_paper_data(ai_rows[pid])
        }
    return comparison_data, common_ids

# ============================================================================
# COMPARISON LOGIC (CERTAINTY-AWARE)
# ============================================================================
def get_ai_cert_level(ai_certainty: Dict, field: str) -> str:
    cert = ai_certainty.get(field, 'unknown')
    if cert == 'solid': return 'solid'
    if cert in ('60', '80'): return 'partial'
    if cert == 'conflict': return 'conflict'
    return 'unknown'

def compare_with_certainty(u_val: int, a_val: int, ai_cert_level: str) -> Dict:
    """Returns category and certainty level for User vs AI comparison."""
    if u_val == a_val:
        return {'category': 'exact_match', 'certainty': ai_cert_level}
    elif u_val > 0 and a_val > 0:
        return {'category': 'direct_conflict', 'certainty': ai_cert_level}
    elif u_val > 0 and a_val == 0:
        return {'category': 'user_override', 'certainty': ai_cert_level}
    elif u_val == 0 and a_val > 0:
        return {'category': 'ai_default', 'certainty': ai_cert_level}
    return {'category': 'unknown', 'certainty': 'unknown'}

def analyze_field_comparison(data: Dict, field: str, paper_ids: List[int]) -> Dict:
    counts = Counter()
    cert_distribution = {
        'exact_match': Counter(), 'direct_conflict': Counter(),
        'user_override': Counter(), 'ai_default': Counter()
    }
    raw_yes_u, raw_no_u, raw_yes_a, raw_no_a = 0, 0, 0, 0
    
    for pid in paper_ids:
        u = data[pid]['user'][field]
        a = data[pid]['ai'][field]
        ai_cert = get_ai_cert_level(data[pid]['ai']['_certainty'], field)
        
        res = compare_with_certainty(u, a, ai_cert)
        counts[res['category']] += 1
        cert_distribution[res['category']][res['certainty']] += 1
        
        if u == 2: raw_yes_u += 1
        elif u == 1: raw_no_u += 1
        if a == 2: raw_yes_a += 1
        elif a == 1: raw_no_a += 1
        
    n = len(paper_ids)
    return {
        'field': field, 'n_papers': n, 'n_observations': n,
        'exact_match': counts['exact_match'],
        'direct_conflict': counts['direct_conflict'],
        'user_override': counts['user_override'],
        'ai_default': counts['ai_default'],
        'certainty_dist': dict(cert_distribution),
        'raw_yes_u': raw_yes_u, 'raw_no_u': raw_no_u,
        'raw_yes_a': raw_yes_a, 'raw_no_a': raw_no_a,
    }

def analyze_stratum( Dict, paper_ids: List[int], fields: List[str], stratum_name: str) -> Dict:
    if len(paper_ids) == 0:
        return {'stratum': stratum_name, 'n_papers': 0, 'n_observations': 0, 'field_results': pd.DataFrame(),
                'overall_exact_match': 0, 'overall_direct_conflict': 0, 'overall_user_override': 0, 'certainty_breakdown': {}}
    
    field_results = [analyze_field_comparison(data, f, paper_ids) for f in fields]
    df = pd.DataFrame(field_results)
    
    n_obs = len(paper_ids) * len(fields)
    exact = df['exact_match'].sum()
    conflict = df['direct_conflict'].sum()
    user_ov = df['user_override'].sum()
    ai_def = df['ai_default'].sum()
    
    # Aggregate certainty breakdown
    total_dist = {'solid': 0, 'partial': 0, 'conflict': 0, 'unknown': 0}
    conflict_dist = {'solid': 0, 'partial': 0, 'conflict': 0, 'unknown': 0}
    
    for _, row in df.iterrows():
        for cat, dist in row['certainty_dist'].items():
            for level, cnt in dist.items():
                if cat == 'direct_conflict':
                    conflict_dist[level] += cnt
                total_dist[level] += cnt
                
    return {
        'stratum': stratum_name, 'n_papers': len(paper_ids), 'n_fields': len(fields), 'n_observations': n_obs,
        'field_results': df,
        'overall_exact_match': exact, 'overall_exact_match_pct': (exact/n_obs*100) if n_obs else 0,
        'overall_direct_conflict': conflict, 'overall_direct_conflict_pct': (conflict/n_obs*100) if n_obs else 0,
        'overall_user_override': user_ov, 'overall_user_override_pct': (user_ov/n_obs*100) if n_obs else 0,
        'overall_ai_default': ai_def, 'overall_ai_default_pct': (ai_def/n_obs*100) if n_obs else 0,
        'conflict_certainty': conflict_dist,
        'total_certainty': total_dist
    }

def run_analysis(data: Dict, paper_ids: List[int], fields: List[str], ai_db_path: str) -> Dict:
    print(f"\nAnalyzing {len(fields)} fields across User vs AI DBs (with AI certainty stratification)...\n")
    
    rel_strata = {}
    for low, high, label in RELEVANCE_BINS:
        rel_strata[label.replace(' ', '_')] = [
            pid for pid in paper_ids 
            if data[pid]['ai'].get('_relevance') is not None and low <= data[pid]['ai']['_relevance'] <= high
        ]
        
    on_topic = [pid for pid in paper_ids if data[pid]['ai'].get('is_offtopic', 0) != 2]
    off_topic = [pid for pid in paper_ids if data[pid]['ai'].get('is_offtopic', 0) == 2]
    
    strata_ids = {
        'all_papers': paper_ids, 'on_topic_only': on_topic, 'off_topic_only': off_topic,
        **{f"rel_{k}": v for k, v in rel_strata.items()}
    }
    
    return {name: analyze_stratum(data, ids, fields, name) for name, ids in strata_ids.items()}

# ============================================================================
# OUTPUT & LATEX
# ============================================================================
def print_summary(results: Dict):
    print("\n" + "="*90)
    print("USER vs AI AGREEMENT ANALYSIS (CERTAINTY-AWARE) - SUMMARY")
    print("="*90)
    
    for name in ['all_papers', 'on_topic_only', 'off_topic_only']:
        s = results[name]
        if s['n_papers'] == 0: continue
        n = s['n_observations']
        print(f"\n📊 {name.upper().replace('_', ' ')} ({s['n_papers']:,} papers × {s['n_fields']:,} fields = {n:,} obs)")
        
        ex_fmt = format_with_ci(s['overall_exact_match_pct'], s['overall_exact_match'], n)
        c_fmt = format_with_ci(s['overall_direct_conflict_pct'], s['overall_direct_conflict'], n)
        uo_fmt = format_with_ci(s['overall_user_override_pct'], s['overall_user_override'], n)
        
        print(f"   ✅ Exact Match:      {ex_fmt}")
        print(f"   ❌ Direct Conflict:  {c_fmt}")
        print(f"   🔵 User Override:    {uo_fmt}")
        print(f"   ⚪ AI Default:     {s['overall_ai_default']:,} ({s['overall_ai_default_pct']:.2f}%)")
        
        # Certainty breakdown for conflicts
        cc = s['conflict_certainty']
        if cc:
            print(f"   🔍 Conflict Breakdown by AI Certainty:")
            for level, cnt in cc.items():
                pct = (cnt/s['overall_direct_conflict']*100) if s['overall_direct_conflict'] else 0
                if level == 'solid': print(f"      🔴 AI Solid (3/3):    {cnt:,} ({pct:.1f}%) → High-impact override")
                elif level == 'partial': print(f"      🟡 AI Partial (2/3):  {cnt:,} ({pct:.1f}%) → Expected user refinement")
                elif level == 'conflict': print(f"      🟠 AI Conflict (Y/N): {cnt:,} ({pct:.1f}%) → Resolved ambiguity")
                else: print(f"      ⚪ AI Unknown:        {cnt:,} ({pct:.1f}%)")

    print(f"\n🎯 BY RELEVANCE SCORE (On-Topic)")
    for low, high, label in RELEVANCE_BINS:
        key = f"rel_{label.replace(' ', '_')}"
        s = results.get(key)
        if not s or s['n_papers'] == 0: continue
        n = s['n_observations']
        print(f"   {label}: Exact {s['overall_exact_match_pct']:.1f}% | Conflict {s['overall_direct_conflict_pct']:.1f}% | Override {s['overall_user_override_pct']:.1f}% (n={n:,})")
    print("="*90 + "\n")

def generate_latex_tables(results: Dict, output_path: str):
    # Simplified for brevity. Adds certainty columns to the conflict breakdown.
    # In production, expand this to match your exact LaTeX template needs.
    with open(output_path, 'w') as f:
        f.write(f"% User vs AI Comparison (Certainty-Aware)\n% Generated: {pd.Timestamp.now().isoformat()}\n")
        f.write("\\begin{table*}[t]\n\\centering\n\\caption{User vs AI Agreement by AI Certainty Level}\n")
        f.write("\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lccc@{}}\n\\hline\n")
        f.write("\\textbf{AI Certainty} & \\textbf{Exact Match} & \\textbf{Direct Conflict} & \\textbf{User Override} \\\\\n\\hline\n")
        s = results['on_topic_only']
        for level in ['solid', 'partial', 'conflict']:
            total = s['total_certainty'].get(level, 0)
            ex = s['field_results']['certainty_dist'].apply(lambda x: x.get('exact_match', {}).get(level, 0)).sum()
            co = s['field_results']['certainty_dist'].apply(lambda x: x.get('direct_conflict', {}).get(level, 0)).sum()
            uo = s['field_results']['certainty_dist'].apply(lambda x: x.get('user_override', {}).get(level, 0)).sum()
            label = "Solid (3/3)" if level=='solid' else "Partial (2/3)" if level=='partial' else "Conflict (Y/N)"
            f.write(f"{label} & {ex:,} ({ex/total*100:.1f}\\%) & {co:,} ({co/total*100:.1f}\\%) & {uo:,} ({uo/total*100:.1f}\\%) \\\\\n")
        f.write("\\hline\\end{tabular*}\n\\end{table*}\n")
    print(f"  LaTeX tables saved to: {output_path}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Compare User DB vs AI DB main-set agreement (v1.2.1 Certainty-Aware)')
    parser.add_argument('--user-db', required=True, help='Path to user-modified database')
    parser.add_argument('--ai-db', required=True, help='Path to AI-classified database')
    parser.add_argument('-o', '--output', default='user_vs_ai_certainty_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    parser.add_argument('--no-latex', action='store_true', help='Skip LaTeX generation')
    args = parser.parse_args()
    
    if not Path(args.user_db).exists() or not Path(args.ai_db).exists():
        print("Error: One or both database files not found.", file=sys.stderr)
        sys.exit(1)
        
    if not args.quiet: print("ResearchParça v1.2.1 | User vs AI Certainty-Aware Comparison")
        
    data, paper_ids = load_comparison_data(args.user_db, args.ai_db)
    if not paper_ids:
        print("Error: No common paper IDs found between databases.", file=sys.stderr)
        sys.exit(1)
        
    results = run_analysis(data, paper_ids, COMPARISON_FIELDS, args.ai_db)
    print_summary(results)
    
    if not args.no_latex:
        generate_latex_tables(results, f"{args.output}_tables.tex")
        
    print("Analysis complete.")
    return 0

if __name__ == '__main__':
    sys.exit(main())