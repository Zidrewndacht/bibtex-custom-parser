#!/usr/bin/env python3
"""
ResearchParça v1.2: Main-to-Sets Data Transfer Utility

Transfers consolidated main classification data to set_1, set_2, and set_3 columns.
This enables running three independent LLM verification passes over the exact same
user-curated/main consensus data, allowing for stochasticity analysis and 
multi-perspective AI vs Human evaluation.

Usage:
    python transfer_main_to_sets.py [path/to/db.sqlite] [--dry-run] [--confirm]
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timezone

# Fields to copy from main row to each set's last_llm_* columns
FIELDS_TO_TRANSFER = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    'relevance', 'verified', 'estimated_score', 'features', 'technique'
]

def main():
    parser = argparse.ArgumentParser(description="Transfer main classification data to set_1, set_2, and set_3 columns.")
    parser.add_argument('db_path', nargs='?', default=None, help='Path to the SQLite database file.')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without committing.')
    parser.add_argument('--confirm', action='store_true', help='Skip interactive confirmation prompt.')
    args = parser.parse_args()

    # Resolve DB path
    if args.db_path is None:
        args.db_path = os.path.join(os.getcwd(), 'data', 'db.sqlite')

    if not os.path.exists(args.db_path):
        print(f"❌ Error: Database not found at {args.db_path}")
        sys.exit(1)

    print(f"📂 Connecting to database: {args.db_path}")
    conn = sqlite3.connect(args.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    cursor = conn.cursor()

    # Fetch papers
    cursor.execute("""
        SELECT id, {} FROM papers
    """.format(', '.join(FIELDS_TO_TRANSFER)))
    
    papers = cursor.fetchall()
    print(f"📄 Found {len(papers)} papers to process.")

    if len(papers) == 0:
        print("ℹ️  Database is empty. Exiting.")
        conn.close()
        return

    if not args.confirm and not args.dry_run:
        resp = input("⚠️  This will overwrite existing set_{1,2,3}_last_llm_* data. Continue? [y/N]: ")
        if resp.strip().lower() not in ('y', 'yes'):
            print("Aborted.")
            conn.close()
            return

    # Build dynamic UPDATE statement
    set_columns = []
    for sn in [1, 2, 3]:
        for field in FIELDS_TO_TRANSFER:
            set_columns.append(f"set_{sn}_last_llm_{field} = ?")

    update_query = f"UPDATE papers SET {', '.join(set_columns)} WHERE id = ?"

    # Prepare batch data
    batch_data = []
    for paper in papers:
        params = []
        # Duplicate values for each of the 3 sets
        for _ in range(3):
            for field in FIELDS_TO_TRANSFER:
                # Pass raw DB value (int, float, string, or None) directly
                params.append(paper[field])
        params.append(paper['id'])
        batch_data.append(params)

    print("🔄 Preparing bulk update...")
    try:
        if args.dry_run:
            print("✅ Dry run complete. No changes written to database.")
        else:
            cursor.executemany(update_query, batch_data)
            
            # Initialize set logs with a clear audit entry
            timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            log_entry = {
                "timestamp": timestamp,
                "type": "user",
                "model": "manual_transfer",
                "trace": "Main row data manually copied to all 3 sets for independent triple-verification.",
                "output": "{}",
                "valid": True
            }
            log_json = json.dumps([log_entry])
            
            # Append/replace logs for all papers
            cursor.execute("""
                UPDATE papers 
                SET set_1_llm_log = ?, set_2_llm_log = ?, set_3_llm_log = ?
                WHERE set_1_llm_log IS NULL OR set_2_llm_log IS NULL OR set_3_llm_log IS NULL
            """, (log_json, log_json, log_json))
            
            conn.commit()
            print(f"✅ Successfully transferred data to 3 sets for {len(batch_data)} papers.")
            print("💡 You can now safely run `/verify` with mode `all` or `remaining`.")
            
    except Exception as e:
        conn.rollback()
        print(f"❌ Transaction failed and rolled back: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()