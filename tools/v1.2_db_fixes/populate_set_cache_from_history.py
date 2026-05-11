#!/usr/bin/env python3
"""
populate_set_cache_from_history.py

One-time migration: Populates set_*_last_llm_* cache columns from the latest 
valid entry in set_*_llm_log history for each set.

This fixes verification issues where cache columns are NULL but history has valid data.
"""

import sqlite3
import json
import sys
import os

def get_latest_valid_classification_from_log(db_path, paper_id, set_num):
    """
    Extract the latest valid classification data from a specific set's llm_log.
    
    Returns dict with all classification fields, or None if no valid entry found.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    log_field = f'set_{set_num}_llm_log'
    cursor.execute(f"SELECT {log_field} FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row[0]:
        return None
    
    try:
        log_entries = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    
    # Find latest valid classifier/averaged_llm entry (most recent first)
    for entry in reversed(log_entries):
        if entry.get('type') not in ['classifier', 'averaged_llm', 'consensus']:
            continue
        if not entry.get('valid', False):
            continue
        
        output = entry.get('output', {})
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except:
                continue
        if not isinstance(output, dict):
            continue
        
        # Extract all classification fields
        data = {}
        
        # Boolean fields
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            val = output.get(field)
            data[field] = 1 if val is True else 0 if val is False else None
        
        # Numeric fields
        data['relevance'] = output.get('relevance')
        data['estimated_score'] = output.get('estimated_score')
        
        # Verified (derive from score if not explicit)
        verified = output.get('verified')
        if verified is None and data['estimated_score'] is not None:
            verified = 1 if data['estimated_score'] >= 7 else 0
        data['verified'] = 1 if verified is True else 0 if verified is False else None
        
        # JSON fields
        data['features'] = output.get('features', {})
        data['technique'] = output.get('technique', {})
        
        # Research area
        data['research_area'] = output.get('research_area')
        
        return data
    
    return None

def populate_set_cache(db_path, paper_id, set_num, data):
    """
    Update set_*_last_llm_* cache columns for a specific set.
    """
    if not data:
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    prefix = f'set_{set_num}_last_llm_'
    update_fields = []
    update_values = []
    
    # Boolean fields
    for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
        update_fields.append(f"{prefix}{field} = ?")
        update_values.append(data.get(field))
    
    # Numeric fields
    update_fields.append(f"{prefix}relevance = ?")
    update_values.append(data.get('relevance'))
    
    update_fields.append(f"{prefix}estimated_score = ?")
    update_values.append(data.get('estimated_score'))
    
    update_fields.append(f"{prefix}verified = ?")
    update_values.append(data.get('verified'))
    
    # JSON fields
    update_fields.append(f"{prefix}features = ?")
    update_values.append(json.dumps(data.get('features', {})))
    
    update_fields.append(f"{prefix}technique = ?")
    update_values.append(json.dumps(data.get('technique', {})))
    
    # Research area
    update_fields.append(f"{prefix}research_area = ?")
    update_values.append(data.get('research_area'))
    
    update_values.append(paper_id)
    
    query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
    cursor.execute(query, update_values)
    conn.commit()
    conn.close()
    
    return True

def main():
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = os.path.join(os.getcwd(), 'data', 'db.sqlite')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM papers")
    paper_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    total_papers = len(paper_ids)
    print(f"Found {total_papers} papers to process")
    print("=" * 60)
    
    updated_count = 0
    papers_with_issues = 0
    
    for i, paper_id in enumerate(paper_ids, 1):
        paper_updated = False
        
        for set_num in [1, 2, 3]:
            # Check if cache is already populated
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            prefix = f'set_{set_num}_last_llm_'
            cursor.execute(f"SELECT {prefix}is_offtopic FROM papers WHERE id = ?", (paper_id,))
            row = cursor.fetchone()
            conn.close()
            
            # If cache has data, skip this set
            if row and row[0] is not None:
                continue
            
            # Cache is NULL - populate from history
            data = get_latest_valid_classification_from_log(db_path, paper_id, set_num)
            
            if data:
                populate_set_cache(db_path, paper_id, set_num, data)
                paper_updated = True
                updated_count += 1
                print(f"  Paper {paper_id} Set {set_num}: Cache populated from history")
            else:
                papers_with_issues += 1
                print(f"  Paper {paper_id} Set {set_num}: ⚠️  No valid history entry found")
        
        if i % 100 == 0 or i == total_papers:
            print(f"Progress: {i}/{total_papers} papers ({100*i//total_papers}%)")
    
    print("=" * 60)
    print(f"Migration complete!")
    print(f"  Cache columns updated: {updated_count}")
    print(f"  Papers with missing history: {papers_with_issues}")
    print(f"  Database: {db_path}")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run verification again - it should now use all 3 sets correctly")
    print("2. Future classifications will keep cache columns up-to-date automatically")

if __name__ == "__main__":
    main()