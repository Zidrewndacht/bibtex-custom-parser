#!/usr/bin/env python3
"""
Reset all papers in the ResearchParça database to a "freshly imported" state.
Clears classification data, verification data, logs, and traces.
Useful for re-testing consensus iteration counting from a clean baseline.

KEEPS: Bibliographic metadata (title, authors, year, journal, etc.), PDFs, user comments.
CLEARS: All LLM classifications, verifications, logs, traces, and audit fields.
"""

import sqlite3
import argparse
import os
import sys
import json

# Import globals for DEFAULT_FEATURES and DEFAULT_TECHNIQUE
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globals

def reset_papers(db_path, keep_user_comments=True):
    """
    Resets all papers to a freshly imported state.
    
    Args:
        db_path: Path to the SQLite database file
        keep_user_comments: If True, preserves user_trace field. If False, clears it too.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get total count before reset
    cursor.execute("SELECT COUNT(*) FROM papers")
    total_count = cursor.fetchone()[0]
    print(f"Total papers in database: {total_count}")
    
    # Build the UPDATE query
    # Clear classification fields
    update_fields = []
    update_values = []
    
    # Main boolean classification fields
    main_bool_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in main_bool_fields:
        update_fields.append(f"{field} = ?")
        update_values.append(None)
    
    # Research area and relevance
    update_fields.append("research_area = ?")
    update_values.append(None)
    
    update_fields.append("relevance = ?")
    update_values.append(None)
    
    # Features and technique (reset to defaults)
    update_fields.append("features = ?")
    update_values.append(json.dumps(globals.DEFAULT_FEATURES))
    
    update_fields.append("technique = ?")
    update_values.append(json.dumps(globals.DEFAULT_TECHNIQUE))
    
    # Verification fields
    update_fields.extend(["verified = ?", "estimated_score = ?", "verified_by = ?"])
    update_values.extend([None, None, ""])
    
    # Audit fields
    update_fields.extend(["changed = ?", "changed_by = ?"])
    update_values.extend([None, None])
    
    # User override count
    update_fields.append("user_override_count = ?")
    update_values.append(0)
    
    # LLM log (history/traces)
    update_fields.append("llm_log = ?")
    update_values.append("[]")
    
    
    # Last LLM cache fields
    for field in main_bool_fields:
        update_fields.append(f"last_llm_{field} = ?")
        update_values.append(None)
    
    update_fields.append("last_llm_features = ?")
    update_values.append(json.dumps(globals.DEFAULT_FEATURES))
    
    update_fields.append("last_llm_technique = ?")
    update_values.append(json.dumps(globals.DEFAULT_TECHNIQUE))
    
    update_fields.append("last_llm_relevance = ?")
    update_values.append(None)
    
    # User trace (optional - preserve user comments if desired)
    if not keep_user_comments:
        update_fields.append("user_trace = ?")
        update_values.append(None)
    
    # Build and execute the query
    update_query = f"UPDATE papers SET {', '.join(update_fields)}"
    
    print(f"\n--- Reset Configuration ---")
    print(f"Database: {db_path}")
    print(f"Papers to reset: {total_count}")
    print(f"Keep user comments (user_trace): {keep_user_comments}")
    print(f"\nFields being cleared:")
    print(f"  - Classification fields (is_offtopic, is_survey, is_through_hole, is_smt, is_x_ray)")
    print(f"  - Research area and relevance")
    print(f"  - Features and technique (reset to defaults)")
    print(f"  - Verification fields (verified, estimated_score, verified_by)")
    print(f"  - Audit fields (changed, changed_by)")
    print(f"  - User override count")
    print(f"  - LLM log (all history/traces)")
    print(f"  - Last LLM cache fields (last_llm_*)")
    if not keep_user_comments:
        print(f"  - User comments (user_trace)")
    print(f"\nFields being PRESERVED:")
    print(f"  - Bibliographic data (id, type, title, authors, year, journal, volume, pages, page_count, doi, issn, abstract, keywords)")
    print(f"  - PDF attachments (pdf_filename, pdf_state)")
    if keep_user_comments:
        print(f"  - User comments (user_trace)")
    print(f"  - Deannualized conference name (deannualized_conference)")
    
    # Confirmation prompt
    confirm = input("\n⚠️  WARNING: This will PERMANENTLY DELETE all classification and verification data!")
    confirm = input("Type 'RESET' to confirm: ")
    if confirm.strip().upper() != 'RESET':
        print("Aborted.")
        conn.close()
        return
    
    print("\nResetting papers...")
    cursor.execute(update_query, update_values)
    conn.commit()
    
    rows_affected = cursor.rowcount
    
    # Verify reset
    cursor.execute("SELECT COUNT(*) FROM papers WHERE changed_by IS NULL AND llm_log = '[]'")
    reset_count = cursor.fetchone()[0]
    
    print(f"\n--- Reset Complete ---")
    print(f"Papers reset: {rows_affected}")
    print(f"Papers in clean state: {reset_count}")
    
    # Vacuum to reclaim any potential space
    print("Running VACUUM to optimize database...")
    cursor.execute("VACUUM")
    conn.commit()
    
    conn.close()
    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Reset all papers in ResearchParça database to freshly imported state.'
    )
    parser.add_argument(
        'db_file',
        help='Path to the SQLite database file (e.g., data/db.sqlite)'
    )
    parser.add_argument(
        '--clear-comments',
        action='store_true',
        help='Also clear user comments (user_trace). By default, user comments are preserved.'
    )
    
    args = parser.parse_args()
    
    reset_papers(args.db_file, keep_user_comments=not args.clear_comments)