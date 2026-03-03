#!/usr/bin/env python3
"""
fix_user_override_count.py - CORRECTED VERSION

Recalculates user_override_count for ALL papers in the database.
Properly handles NULL/None and boolean type mismatches.
"""

import sqlite3
import json
import os
import sys

TRACKED_FIELDS = {
    'features': ['tracks', 'holes', 'bare_pcb_other', 'solder_insufficient', 
                 'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
                 'orientation', 'wrong_component', 'missing_component', 
                 'component_other', 'cosmetic', 'other'],
    'technique': ['classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
                  'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
                  'dl_other', 'hybrid', 'available_dataset'],
    'main_bool': ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray'],
    'other': ['relevance', 'verified', 'estimated_score']
}

def normalize_for_comparison(val):
    """
    Normalize values for comparison to handle DB vs Python type mismatches.
    Returns a canonical form for comparison.
    """
    # Handle NULL/None/empty string as equivalent
    if val is None or val == '' or val == 'None':
        return None
    
    # Handle boolean/int mismatch (DB stores 0/1, Python might have True/False)
    if val is True or val == 1 or val == '1' or val == 'true':
        return 1
    if val is False or val == 0 or val == '0' or val == 'false':
        return 0
    
    # Handle string numbers
    if isinstance(val, str) and val.isdigit():
        return int(val)
    
    # Keep other values as-is
    return val

def values_are_equal(current_val, llm_val):
    """
    Check if two values are effectively equal after normalization.
    """
    current_norm = normalize_for_comparison(current_val)
    llm_norm = normalize_for_comparison(llm_val)
    
    # Both NULL/None are equal
    if current_norm is None and llm_norm is None:
        return True
    
    # One NULL, one not - different
    if current_norm is None or llm_norm is None:
        return False
    
    # Direct comparison for normalized values
    return current_norm == llm_norm

def calculate_override_count(row):
    """
    Calculate the user_override_count by comparing current values against last_llm values.
    """
    count = 0
    
    # Parse current features
    try:
        current_features = json.loads(row['features']) if row['features'] else {}
    except (json.JSONDecodeError, TypeError):
        current_features = {}
    
    # Parse last_llm_features
    try:
        last_llm_features = json.loads(row['last_llm_features']) if row['last_llm_features'] else {}
    except (json.JSONDecodeError, TypeError):
        last_llm_features = {}
    
    # Compare features
    for key in TRACKED_FIELDS['features']:
        current_val = current_features.get(key)
        llm_val = last_llm_features.get(key)
        if not values_are_equal(current_val, llm_val):
            count += 1
    
    # Parse current technique
    try:
        current_technique = json.loads(row['technique']) if row['technique'] else {}
    except (json.JSONDecodeError, TypeError):
        current_technique = {}
    
    # Parse last_llm_technique
    try:
        last_llm_technique = json.loads(row['last_llm_technique']) if row['last_llm_technique'] else {}
    except (json.JSONDecodeError, TypeError):
        last_llm_technique = {}
    
    # Compare techniques
    for key in TRACKED_FIELDS['technique']:
        current_val = current_technique.get(key)
        llm_val = last_llm_technique.get(key)
        if not values_are_equal(current_val, llm_val):
            count += 1
    
    # Compare main boolean fields
    for key in TRACKED_FIELDS['main_bool']:
        current_val = row[f'{key}']
        llm_val = row[f'last_llm_{key}']
        if not values_are_equal(current_val, llm_val):
            count += 1
    
    # Compare other fields (relevance, verified, estimated_score)
    for key in TRACKED_FIELDS['other']:
        current_val = row[f'{key}']
        llm_val = row[f'last_llm_{key}']
        if not values_are_equal(current_val, llm_val):
            count += 1
    
    return count

def fix_database(db_path):
    """Recalculate user_override_count for all papers in the database."""
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get total count
    cursor.execute("SELECT COUNT(*) FROM papers")
    total_papers = cursor.fetchone()[0]
    print(f"Total papers in database: {total_papers}")
    
    # Fetch all papers with current and last_llm values
    cursor.execute("""
        SELECT 
            id,
            features, technique,
            is_survey, is_offtopic, is_through_hole, is_smt, is_x_ray,
            relevance, verified, estimated_score,
            last_llm_features, last_llm_technique,
            last_llm_is_survey, last_llm_is_offtopic, last_llm_is_through_hole,
            last_llm_is_smt, last_llm_is_x_ray,
            last_llm_relevance, last_llm_verified, last_llm_estimated_score,
            user_override_count
        FROM papers
    """)
    
    papers = cursor.fetchall()
    
    updates = []
    stats = {
        'unchanged': 0,
        'changed': 0,
        'had_negative': 0,
        'had_zero': 0,
        'had_two_bug': 0,
        'max_count': 0
    }
    
    print("\nRecalculating user_override_count for all papers...")
    print("-" * 60)
    
    for i, paper in enumerate(papers):
        paper_id = paper['id']
        
        # Calculate new count
        new_count = calculate_override_count(paper)
        
        old_count = paper['user_override_count']
        
        # Track statistics
        if old_count is not None and old_count < 0:
            stats['had_negative'] += 1
        if old_count == 0 or old_count is None:
            stats['had_zero'] += 1
        if old_count == 2:
            stats['had_two_bug'] += 1
        if new_count == 0:
            stats['unchanged'] += 1
        else:
            stats['changed'] += 1
        if new_count > stats['max_count']:
            stats['max_count'] = new_count
        
        # Only update if different
        if old_count != new_count:
            updates.append((new_count, paper_id))
        
        # Progress indicator
        if (i + 1) % 1000 == 0 or (i + 1) == total_papers:
            print(f"  Processed {i + 1}/{total_papers} papers...", end='\r')
    
    print("\n" + "-" * 60)
    
    # Apply updates in batch
    if updates:
        print(f"\nUpdating {len(updates)} papers with corrected counts...")
        cursor.executemany(
            "UPDATE papers SET user_override_count = ? WHERE id = ?",
            updates
        )
        conn.commit()
        print(f"  ✓ Updated {len(updates)} papers")
    else:
        print("\n  ✓ No updates needed (all counts were already correct)")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total papers processed:     {total_papers}")
    print(f"Papers with negative count: {stats['had_negative']} (FIXED)")
    print(f"Papers with '2' bug count:  {stats['had_two_bug']} (FIXED)")
    print(f"Papers with zero count:     {stats['had_zero']}")
    print(f"Papers unchanged (count=0): {stats['unchanged']}")
    print(f"Papers with overrides:      {stats['changed']}")
    print(f"Maximum override count:     {stats['max_count']}")
    print(f"Papers updated:             {len(updates)}")
    print("=" * 60)
    
    conn.close()
    print("\n✓ Database fix completed successfully!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = os.path.join(os.getcwd(), 'data', 'db.sqlite')
    
    print("=" * 60)
    print("ResearchParça - User Override Count Fix Script (CORRECTED)")
    print("=" * 60)
    print(f"Database: {db_path}")
    print("=" * 60)
    
    fix_database(db_path)