# prune_for_sanity_check.py
# Standalone script for ResearchParça v1.2
import sqlite3
import json
import random
import argparse
import os
import shutil

def has_conflict(certainty_json):
    """Check if the main_certainty JSON contains any 'conflict' values."""
    if not certainty_json:
        return False
    try:
        cert = json.loads(certainty_json)
        if isinstance(cert, dict):
            return "conflict" in cert.values()
    except (json.JSONDecodeError, TypeError):
        pass
    return False

def main():
    parser = argparse.ArgumentParser(
        description="Prune ResearchParça DB to ~100 papers for human sanity check."
    )
    parser.add_argument("db_path", help="Path to the SQLite database (e.g., data/db.sqlite)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sampling.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if not os.path.exists(args.db_path):
        print(f"Error: Database not found at {args.db_path}")
        return

    # Safety backup
    backup_path = f"{args.db_path}.prune_backup"
    print(f"[1/4] Creating safety backup at {backup_path}...")
    shutil.copy2(args.db_path, backup_path)

    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("[2/4] Fetching and categorizing papers...")
    cursor.execute("SELECT id, is_offtopic, main_certainty FROM papers")
    all_papers = cursor.fetchall()

    off_topic = []
    on_topic_conflict = []
    on_topic_normal = []

    for paper in all_papers:
        pid = paper['id']
        is_offtopic = paper['is_offtopic']
        main_certainty = paper['main_certainty']

        if is_offtopic == 1:
            off_topic.append(pid)
        else:
            # 0 or NULL means on-topic / unclassified
            if has_conflict(main_certainty):
                on_topic_conflict.append(pid)
            else:
                on_topic_normal.append(pid)

    print(f"      Found: {len(off_topic)} off-topic, {len(on_topic_conflict)} on-topic w/ conflicts, {len(on_topic_normal)} on-topic normal.")

    # Sampling logic
    target_total = 100
    max_cat = 20  # 20% cap

    sel_offtopic = random.sample(off_topic, min(max_cat, len(off_topic))) if off_topic else []
    sel_conflict = random.sample(on_topic_conflict, min(max_cat, len(on_topic_conflict))) if on_topic_conflict else []
    
    remaining = target_total - len(sel_offtopic) - len(sel_conflict)
    sel_normal = random.sample(on_topic_normal, min(remaining, len(on_topic_normal))) if on_topic_normal else []

    final_ids = set(sel_offtopic) | set(sel_conflict) | set(sel_normal)

    print(f"\n[3/4] Selection Summary:")
    print(f"  - Off-topic:          {len(sel_offtopic)}")
    print(f"  - On-topic (conflict): {len(sel_conflict)}")
    print(f"  - On-topic (random):  {len(sel_normal)}")
    print(f"  TOTAL KEPT:           {len(final_ids)} papers")

    if len(final_ids) == 0:
        print("No papers selected. Database untouched.")
        conn.close()
        return

    # Prune unselected papers
    print("[4/4] Pruning database...")
    placeholders = ','.join('?' for _ in final_ids)
    delete_query = f"DELETE FROM papers WHERE id NOT IN ({placeholders})"
    cursor.execute(delete_query, list(final_ids))
    conn.commit()
    print(f"      {cursor.rowcount} papers removed.")
    print("      Database ready for human review.")
    
    conn.close()

if __name__ == "__main__":
    main()