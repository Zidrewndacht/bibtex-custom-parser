#!/usr/bin/env python3
"""
diagnose_set_columns.py - FIXED VERSION
"""

import sqlite3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globals

def diagnose_paper_sets(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row  # ← FIX: Set row_factory BEFORE fetching
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM papers")
    all_papers = [row[0] for row in cursor.fetchall()]
    
    issues = {
        'all_sets_null': [],
        'partial_sets_null': [],
        'invalid_json': [],
        'ok': []
    }
    
    for paper_id in all_papers:
        cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        if not row:
            continue
        paper = dict(row)  # ← Now this works
        
        set_status = []
        for set_num in [1, 2, 3]:
            prefix = f'set_{set_num}_last_llm_'
            is_offtopic = paper.get(f'{prefix}is_offtopic')
            features_str = paper.get(f'{prefix}features')
            technique_str = paper.get(f'{prefix}technique')
            
            set_info = {'set_num': set_num, 'is_offtopic': is_offtopic}
            
            if features_str:
                try:
                    json.loads(features_str)
                    set_info['features_valid'] = True
                except:
                    set_info['features_valid'] = False
            else:
                set_info['features_valid'] = True
            
            if technique_str:
                try:
                    json.loads(technique_str)
                    set_info['technique_valid'] = True
                except:
                    set_info['technique_valid'] = False
            else:
                set_info['technique_valid'] = True
            
            set_status.append(set_info)
        
        all_null = all(s['is_offtopic'] is None for s in set_status)
        any_null = any(s['is_offtopic'] is None for s in set_status)
        any_invalid_json = any(not s['features_valid'] or not s['technique_valid'] for s in set_status)
        
        if all_null:
            issues['all_sets_null'].append(paper_id)
        elif any_null:
            issues['partial_sets_null'].append(paper_id)
        elif any_invalid_json:
            issues['invalid_json'].append(paper_id)
        else:
            issues['ok'].append(paper_id)
    
    conn.close()
    return issues, len(all_papers)


def main():
    db_path = globals.DATABASE_FILE
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found: {db_path}")
        sys.exit(1)
    
    print(f"Database: {db_path}")
    print("=" * 70)
    
    issues, total = diagnose_paper_sets(db_path)
    
    print(f"\nDIAGNOSIS ({total} papers):")
    print(f"  ✓ OK:                    {len(issues['ok'])}")
    print(f"  ✗ All 3 sets NULL:       {len(issues['all_sets_null'])}")
    print(f"  ⚠ Partial sets NULL:     {len(issues['partial_sets_null'])}")
    print(f"  ✗ Invalid JSON:          {len(issues['invalid_json'])}")
    
    if issues['all_sets_null']:
        print(f"\n📋 All sets NULL (first 10):")
        for pid in issues['all_sets_null'][:10]:
            print(f"    - {pid}")
    
    if issues['partial_sets_null']:
        print(f"\n📋 Partial sets NULL (first 10):")
        for pid in issues['partial_sets_null'][:10]:
            print(f"    - {pid}")
    
    sys.exit(0)

if __name__ == "__main__":
    main()