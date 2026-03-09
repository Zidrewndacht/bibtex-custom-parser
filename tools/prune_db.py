#!/usr/bin/env python3
"""
Prune ResearchParça database to keep only a random subset of papers.
Used for performance testing and human quality validation.
Supports stratification by on-topic/off-topic ratio.
"""

import sqlite3
import argparse
import os
import sys

def parse_ratio(value):
    """Parse ratio argument. Accepts both percentage (80) or decimal (0.8)."""
    if value is None:
        return None
    ratio = float(value)
    if ratio > 1.0:
        ratio = ratio / 100.0
    if not (0.0 <= ratio <= 1.0):
        raise argparse.ArgumentTypeError(
            f"Ratio must be between 0-100 (percentage) or 0.0-1.0 (decimal). Got: {value}"
        )
    return ratio

def prune_database(db_path, keep_count=2000, year_from=2005, on_topic_ratio=None, seed=None):
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get counts before pruning (with year filter)
    cursor.execute("SELECT COUNT(*) FROM papers WHERE year >= ?", (year_from,))
    total_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE year >= ? AND (is_offtopic = 0 OR is_offtopic IS NULL)", (year_from,))
    on_topic_count = cursor.fetchone()[0]
    
    off_topic_count = total_count - on_topic_count
    
    cursor.execute("SELECT COUNT(*) FROM papers")
    overall_total = cursor.fetchone()[0]
    
    print(f"Total papers in database: {overall_total}")
    print(f"Papers from year {year_from} onwards: {total_count}")
    print(f"  - On-topic: {on_topic_count}")
    print(f"  - Off-topic: {off_topic_count}")
    
    if keep_count >= total_count:
        print(f"No pruning needed. Database already has {total_count} papers from {year_from}+ (≤ {keep_count}).")
        conn.close()
        return
    
    # Calculate target counts for stratified selection
    if on_topic_ratio is not None:
        target_on_topic = int(keep_count * on_topic_ratio)
        target_off_topic = keep_count - target_on_topic
        
        if target_on_topic > on_topic_count:
            print(f"Warning: Requested {target_on_topic} on-topic papers, but only {on_topic_count} available.")
            target_on_topic = on_topic_count
            target_off_topic = keep_count - target_on_topic
            print(f"  Adjusted to: {target_on_topic} on-topic, {target_off_topic} off-topic")
        
        if target_off_topic > off_topic_count:
            print(f"Warning: Requested {target_off_topic} off-topic papers, but only {off_topic_count} available.")
            target_off_topic = off_topic_count
            target_on_topic = keep_count - target_off_topic
            print(f"  Adjusted to: {target_on_topic} on-topic, {target_off_topic} off-topic")
        
        print(f"\nStratified selection:")
        print(f"  Target on-topic: {target_on_topic} ({on_topic_ratio*100:.0f}%)")
        print(f"  Target off-topic: {target_off_topic} ({(1-on_topic_ratio)*100:.0f}%)")
        
        # Select on-topic papers randomly
        cursor.execute("""
            SELECT id FROM papers 
            WHERE year >= ? AND (is_offtopic = 0 OR is_offtopic IS NULL)
            ORDER BY RANDOM() 
            LIMIT ?
        """, (year_from, target_on_topic))
        on_topic_ids = set(row[0] for row in cursor.fetchall())
        
        # Select off-topic papers randomly
        cursor.execute("""
            SELECT id FROM papers 
            WHERE year >= ? AND (is_offtopic = 1)
            ORDER BY RANDOM() 
            LIMIT ?
        """, (year_from, target_off_topic))
        off_topic_ids = set(row[0] for row in cursor.fetchall())
        
        papers_to_keep = on_topic_ids | off_topic_ids
        print(f"\nSelected {len(papers_to_keep)} random papers to keep (year ≥ {year_from}):")
        print(f"  - On-topic: {len(on_topic_ids)}")
        print(f"  - Off-topic: {len(off_topic_ids)}")
    else:
        # Purely random selection
        cursor.execute("""
            SELECT id FROM papers 
            WHERE year >= ?
            ORDER BY RANDOM() 
            LIMIT ?
        """, (year_from, keep_count))
        papers_to_keep = set(row[0] for row in cursor.fetchall())
        print(f"\nSelected {len(papers_to_keep)} random papers to keep (year ≥ {year_from}).")
    
    # ✅ FIXED: Delete using the ACTUAL papers_to_keep set
    print(f"\nDeleting {total_count - len(papers_to_keep)} papers...")
    
    if papers_to_keep:
        papers_to_keep_list = list(papers_to_keep)
        
        # SQLite has IN clause limit (~999), use temp table for safety
        cursor.execute("CREATE TEMPORARY TABLE papers_to_keep_temp (id TEXT PRIMARY KEY)")
        
        # Insert in batches to avoid parameter limits
        batch_size = 500
        for i in range(0, len(papers_to_keep_list), batch_size):
            batch = papers_to_keep_list[i:i + batch_size]
            cursor.executemany("INSERT INTO papers_to_keep_temp (id) VALUES (?)", 
                             [(pid,) for pid in batch])
        
        # Delete papers NOT in our keep list
        cursor.execute("""
            DELETE FROM papers 
            WHERE id NOT IN (SELECT id FROM papers_to_keep_temp)
        """)
    else:
        cursor.execute("DELETE FROM papers WHERE year >= ?", (year_from,))
    
    deleted_count = cursor.rowcount
    conn.commit()
    
    # Verify final count
    cursor.execute("SELECT COUNT(*) FROM papers")
    final_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE (is_offtopic = 0 OR is_offtopic IS NULL)")
    final_on_topic = cursor.fetchone()[0]
    
    final_off_topic = final_count - final_on_topic
    
    print(f"\n--- Pruning Complete ---")
    print(f"Papers deleted: {deleted_count}")
    print(f"Papers remaining: {final_count}")
    if on_topic_ratio is not None:
        print(f"  - On-topic: {final_on_topic} ({final_on_topic/final_count*100:.1f}%)")
        print(f"  - Off-topic: {final_off_topic} ({final_off_topic/final_count*100:.1f}%)")
    
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
    parser.add_argument('db_file', help='Path to the SQLite database file')
    parser.add_argument('--keep', '-k', type=int, default=2000, help='Number of papers to keep (default: 2000)')
    parser.add_argument('--year-from', '-y', type=int, default=2005, help='Minimum year for papers (default: 2005)')
    parser.add_argument('--on-topic-ratio', '-r', type=parse_ratio, default=None, 
                       help='Proportion of on-topic papers (80 or 0.8 for 80%)')
    parser.add_argument('--seed', '-s', type=int, default=None, help='Random seed (optional)')
    
    args = parser.parse_args()
    
    print(f"WARNING: This will permanently delete papers from the database!")
    print(f"Database: {args.db_file}")
    print(f"Papers to keep: {args.keep}")
    print(f"Year cutoff: {args.year_from} (papers older than this will be excluded)")
    if args.on_topic_ratio is not None:
        print(f"Stratification: {args.on_topic_ratio*100:.0f}% on-topic, {(1-args.on_topic_ratio)*100:.0f}% off-topic")
    else:
        print(f"Stratification: None (purely random selection)")
    if args.seed:
        print(f"Random seed: {args.seed}")
    
    confirm = input("\nType 'YES' to confirm: ")
    if confirm.strip().upper() != 'YES':
        print("Aborted.")
        sys.exit(0)
    
    prune_database(args.db_file, args.keep, args.year_from, args.on_topic_ratio, args.seed)