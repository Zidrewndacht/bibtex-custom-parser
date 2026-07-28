#!/usr/bin/env python3
# v1.4_user_vs_ai_comparison.py (v1.4 - Configurable DB & Certainty-Aware)
# Compares user-modified main_set data vs AI-averaged main_set data across two separate SQLite DBs.
# Refactored to read settings from domain_config.yaml and support nested JSON classification blobs.

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
# CONFIGURATION
# ============================================================================
RELEVANCE_BINS = [
    (0, 1, "Very Low (0-1)"),
    (2, 3, "Low (2-3)"),
    (4, 5, "Medium (4-5)"),
    (6, 7, "High (6-7)"),
    (8, 10, "Very High (8-10)")
]
MIN_N_FOR_CI = 100

# ============================================================================
# DOMAIN CONFIG LOADER & HELPERS
# ============================================================================
def load_domain_config() -> Optional[Dict]:
    """Attempts to load domain_config.yaml from standard relative paths."""
    paths_to_try = [
        'domain_config.yaml',
        os.path.join(os.path.dirname(__file__), 'domain_config.yaml'),
        os.path.join(os.path.dirname(__file__), '..', 'domain_config.yaml'),
        os.path.join(os.path.dirname(__file__), '..', '..', 'domain_config.yaml')
    ]
    for p in paths_to_try:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
            except Exception as e:
                print(f"Warning: Failed to parse {p}: {e}")
    print("Warning: domain_config.yaml not found. Will attempt to infer fields from DB.")
    return None

def get_val_by_path(d: Dict, path: str):
    """Safely get a value from a nested dict using dot-notation."""
    if not d or not path: return None
    keys = path.split('.')
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d

def get_all_paths(d: Dict, prefix: str = '') -> List[str]:
    """Recursively discover all leaf-node paths in a nested dict."""
    paths = []
    if not isinstance(d, dict): return paths
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            paths.extend(get_all_paths(v, path))
        else:
            paths.append(path)
    return paths

def get_comparison_fields(domain_cfg: Optional[Dict], sample_classification: Dict) -> List[str]:
    """Dynamically determines which boolean/tri-state fields to compare."""
    fields = []
    # Universal fields that were hardcoded in v1.2.1
    fields.extend(['is_offtopic', 'verified', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray'])
    
    if domain_cfg:
        for group in domain_cfg.get('groups', []):
            json_path = group.get('json_path', '')
            if not json_path: continue
            if group.get('filter_type') == 'tri_state':
                fields.append(json_path)
            elif group.get('filter_type') in ['inclusion', 'none']:
                for f in group.get('fields', []):
                    key = f.get('key', '')
                    if key:
                        fields.append(f"{json_path}.{key}")
    else:
        # Fallback: extract all paths from sample classification blob
        paths = get_all_paths(sample_classification)
        for p in paths:
            # Exclude known non-boolean/string fields
            if p not in ('relevance', 'estimated_score', 'verified_by', 'research_area', 'model', 'other'):
                fields.append(p)
                
    # Deduplicate while preserving order
    seen = set()
    unique_fields = []
    for f in fields:
        if f and f not in seen:
            seen.add(f)
            unique_fields.append(f)
    return unique_fields

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

def extract_paper_data(row: Dict, comparison_fields: List[str]) -> Dict:
    data = {}
    
    # Parse classification blob (new schema stores inferred data here)
    try:
        classification = json.loads(row.get('classification', '{}') or '{}') or {}
    except:
        classification = {}
        
    # Parse main_certainty blob
    try:
        certainty = json.loads(row.get('main_certainty', '{}') or '{}') or {}
    except:
        certainty = {}
        
    for f in comparison_fields:
        # Try to get from classification blob
        val = get_val_by_path(classification, f)
        # Fallback to top-level row column (e.g. 'verified' might be top-level in some transitions)
        if val is None and '.' not in f:
            val = row.get(f)
        data[f] = normalize_val(val)
        
    # Relevance can be in classification or top-level
    rel = get_val_by_path(classification, 'relevance')
    if rel is None:
        rel = row.get('relevance')
    data['_relevance'] = int(rel) if isinstance(rel, (int, float)) else None
    
    # AI internal certainty/conflict metadata
    data['_certainty'] = certainty
    return data

# ============================================================================
# DATA LOADING & ALIGNMENT
# ============================================================================
def load_comparison_data(user_db_path: str, ai_db_path: str, domain_cfg: Optional[Dict]) -> Tuple[Dict[int, Dict], List[int], List[str]]:
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
    
    # Determine fields to compare
    sample_class = {}
    if common_ids:
        try:
            sample_class = json.loads(ai_rows[common_ids[0]].get('classification', '{}') or '{}') or {}
        except:
            pass
            
    comparison_fields = get_comparison_fields(domain_cfg, sample_class)
    print(f"  📋 Comparing {len(comparison_fields)} fields: {', '.join(comparison_fields[:5])}{'...' if len(comparison_fields) > 5 else ''}")
    
    comparison_data = {}
    for pid in common_ids:
        comparison_data[pid] = {
            'user': extract_paper_data(user_rows[pid], comparison_fields),
            'ai': extract_paper_data(ai_rows[pid], comparison_fields)
        }
    return comparison_data, common_ids, comparison_fields

# ============================================================================
# COMPARISON LOGIC (CERTAINTY-AWARE)
# ============================================================================
def get_ai_cert_level(ai_certainty: Dict, field: str) -> str:
    # main_certainty is now a nested dictionary matching the classification structure
    cert = get_val_by_path(ai_certainty, field)
    if cert is None:
        cert = 'unknown'
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

def analyze_stratum(data: Dict, paper_ids: List[int], fields: List[str], stratum_name: str) -> Dict:
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
        if cc and s['overall_direct_conflict'] > 0:
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
    with open(output_path, 'w') as f:
        f.write(f"% User vs AI Comparison (Certainty-Aware)\n% Generated: {pd.Timestamp.now().isoformat()}\n")
        f.write("\\begin{table*}[t]\n\\centering\n\\caption{User vs AI Agreement by AI Certainty Level}\n")
        f.write("\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lccc@{}}\n\\hline\n")
        f.write("\\textbf{AI Certainty} & \\textbf{Exact Match} & \\textbf{Direct Conflict} & \\textbf{User Override} \\\\\n\\hline\n")
        
        s = results.get('on_topic_only')
        if not s or s['n_papers'] == 0:
            f.write("% No on-topic papers found for LaTeX table.\n")
        else:
            for level in ['solid', 'partial', 'conflict']:
                total = s['total_certainty'].get(level, 0)
                if total == 0: continue
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
    parser = argparse.ArgumentParser(description='Compare User DB vs AI DB main-set agreement (v1.4 Configurable & Certainty-Aware)')
    parser.add_argument('--user-db', required=True, help='Path to user-modified database')
    parser.add_argument('--ai-db', required=True, help='Path to AI-classified database')
    parser.add_argument('-o', '--output', default='user_vs_ai_certainty_results', help='Output path prefix')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    parser.add_argument('--no-latex', action='store_true', help='Skip LaTeX generation')
    args = parser.parse_args()
    
    if not Path(args.user_db).exists() or not Path(args.ai_db).exists():
        print("Error: One or both database files not found.", file=sys.stderr)
        sys.exit(1)
        
    if not args.quiet: print("ResearchParça v1.4 | User vs AI Configurable & Certainty-Aware Comparison")
    
    domain_cfg = load_domain_config()
    if domain_cfg and not args.quiet:
        print("  ✅ Loaded domain_config.yaml")
        
    data, paper_ids, comparison_fields = load_comparison_data(args.user_db, args.ai_db, domain_cfg)
    if not paper_ids:
        print("Error: No common paper IDs found between databases.", file=sys.stderr)
        sys.exit(1)
        
    results = run_analysis(data, paper_ids, comparison_fields, args.ai_db)
    if not args.quiet:
        print_summary(results)
    
    if not args.no_latex:
        generate_latex_tables(results, f"{args.output}_tables.tex")
        
    if not args.quiet:
        print("Analysis complete.")
    return 0

if __name__ == '__main__':
    sys.exit(main())