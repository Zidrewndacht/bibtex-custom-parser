#!/usr/bin/env python3
"""
Prune ResearchParça database to keep only a random subset of papers.
Used for performance testing and human quality validation.
"""

import sqlite3
import argparse
import os
import sys

def prune_database(db_path, keep_count=2000, year_from=2005, seed=None):
    """
    Prunes the database to keep only `keep_count` random papers from `year_from` onwards.
    
    Args:
        db_path: Path to the SQLite database file
        keep_count: Number of papers to keep (default: 2000)
        year_from: Minimum year for papers to include (default: 2005)
        seed: Random seed for reproducibility (optional)
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get total count before pruning (with year filter)
    cursor.execute("SELECT COUNT(*) FROM papers WHERE year >= ?", (year_from,))
    total_count = cursor.fetchone()[0]
    
    # Get overall total for info
    cursor.execute("SELECT COUNT(*) FROM papers")
    overall_total = cursor.fetchone()[0]
    
    print(f"Total papers in database: {overall_total}")
    print(f"Papers from year {year_from} onwards: {total_count}")
    
    if keep_count >= total_count:
        print(f"No pruning needed. Database already has {total_count} papers from {year_from}+ (≤ {keep_count}).")
        conn.close()
        return
    
    # Select random paper IDs to keep (with year filter)
    cursor.execute("""
        SELECT id FROM papers 
        WHERE year >= ?
        ORDER BY RANDOM() 
        LIMIT ?
    """, (year_from, keep_count))
    papers_to_keep = set(row[0] for row in cursor.fetchall())
    print(f"Selected {len(papers_to_keep)} random papers to keep (year ≥ {year_from}).")
    
    # Delete all papers NOT in the keep set
    # Papers older than year_from are always deleted
    # Papers from year_from onwards are deleted if not in the random selection
    cursor.execute("""
        DELETE FROM papers 
        WHERE id NOT IN (
            SELECT id FROM papers 
            WHERE year >= ?
            ORDER BY RANDOM() 
            LIMIT ?
        )
    """, (year_from, keep_count))
    
    deleted_count = cursor.rowcount
    conn.commit()
    
    # Verify final count
    cursor.execute("SELECT COUNT(*) FROM papers")
    final_count = cursor.fetchone()[0]
    
    print(f"\n--- Pruning Complete ---")
    print(f"Papers deleted: {deleted_count}")
    print(f"Papers remaining: {final_count}")
    
    # Vacuum to reclaim disk space
    print("Running VACUUM to reclaim disk space...")
    cursor.execute("VACUUM")
    conn.commit()
    
    conn.close()
    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Prune ResearchParça database to a random subset of papers.'
    )
    parser.add_argument(
        'db_file',
        help='Path to the SQLite database file (e.g., data/db.sqlite)'
    )
    parser.add_argument(
        '--keep', '-k',
        type=int,
        default=2000,
        help='Number of papers to keep (default: 2000)'
    )
    parser.add_argument(
        '--year-from', '-y',
        type=int,
        default=2005,
        help='Minimum year for papers to include (default: 2005)'
    )
    parser.add_argument(
        '--seed', '-s',
        type=int,
        default=None,
        help='Random seed for reproducibility (optional)'
    )
    
    args = parser.parse_args()
    
    # Confirmation prompt
    print(f"WARNING: This will permanently delete papers from the database!")
    print(f"Database: {args.db_file}")
    print(f"Papers to keep: {args.keep}")
    print(f"Year cutoff: {args.year_from} (papers older than this will be excluded)")
    if args.seed:
        print(f"Random seed: {args.seed}")
    
    confirm = input("\nType 'YES' to confirm: ")
    if confirm.strip().upper() != 'YES':
        print("Aborted.")
        sys.exit(0)
    
    prune_database(args.db_file, args.keep, args.year_from, args.seed)