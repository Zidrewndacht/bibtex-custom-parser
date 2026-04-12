#!/usr/bin/env python3
"""
merge_pdfs_comments.py
Safely merges pdf_filename, pdf_state, and user_trace from a source database 
into a main database. Skips overwriting if source values are NULL/empty.
"""
import sqlite3
import os
import shutil
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Merge PDF/Comment data from a source DB into a main DB."
    )
    parser.add_argument("main_db", help="Path to the main database (destination)")
    parser.add_argument("source_db", help="Path to the source database (contains PDFs/comments)")
    parser.add_argument("--no-backup", action="store_true", help="Skip automatic backup of the main database")
    args = parser.parse_args()

    # 1. Validate paths
    for db_path in [args.main_db, args.source_db]:
        if not os.path.exists(db_path):
            print(f"Error: Database file not found at '{db_path}'")
            sys.exit(1)

    # 2. Backup main DB
    if not args.no_backup:
        backup_path = f"{args.main_db}.bak_before_merge"
        print(f"Creating backup of main database at: {backup_path}")
        shutil.copy2(args.main_db, backup_path)
    else:
        print("Warning: Skipping backup. Proceeding with caution.")

    conn_main = sqlite3.connect(args.main_db)
    conn_source = sqlite3.connect(args.source_db)
    cursor_main = conn_main.cursor()
    cursor_source = conn_source.cursor()

    try:
        # 3. Fetch target fields from source
        cursor_source.execute("SELECT id, pdf_filename, pdf_state, user_trace FROM papers")
        rows = cursor_source.fetchall()
        print(f"Found {len(rows)} records in source database.")

        # 4. Prepare safe update query
        # COALESCE(NULLIF(?, ''), col) ensures we ONLY overwrite if source has real data.
        # Prevents NULL/empty source values from wiping existing main DB data.
        update_query = """
            UPDATE papers 
            SET 
                pdf_filename = COALESCE(NULLIF(?, ''), pdf_filename),
                pdf_state    = COALESCE(NULLIF(?, ''), pdf_state),
                user_trace   = COALESCE(NULLIF(?, ''), user_trace)
            WHERE id = ?
        """

        updated_count = 0
        conn_main.execute("BEGIN TRANSACTION")
        
        for row in rows:
            src_id, src_pdf, src_state, src_trace = row
            
            # Execute update
            cursor_main.execute(update_query, (src_pdf, src_state, src_trace, src_id))
            updated_count += cursor_main.rowcount

        conn_main.commit()
        print(f"\nMerge complete.")
        print(f"Updated {updated_count} row(s) in the main database.")
        
    except sqlite3.Error as e:
        conn_main.rollback()
        print(f"\nDatabase error during merge: {e}")
        sys.exit(1)
    finally:
        conn_main.close()
        conn_source.close()

if __name__ == "__main__":
    main()