# reset_consensus_classifications.py
"""
Standalone script to reset all papers that have had consensus classifications.
Resets main classification fields, last_llm_* cache fields, verification fields,
AND CLEARS THE llm_log HISTORY.

After running, affected papers will look like newly imported papers with no 
classification history - ready for fresh classification runs.

NOTE: Database path must be explicitly provided (no default from globals.py).
"""

import sqlite3
import json
import argparse
import os
from datetime import datetime

# Import globals ONLY for DEFAULT_FEATURES and DEFAULT_TECHNIQUE
# NOT for DATABASE_FILE
import globals

def has_consensus_history(llm_log):
    """
    Detect if a paper went through consensus classification.
    Consensus = multiple classification attempts with verification cycles.
    
    Heuristics:
    - 3+ classifier entries (normal flow = 1, maybe 2 with reclassification)
    - OR multiple classifier+verifier pairs
    - OR changed_by contains model name with multiple classification timestamps
    """
    if not llm_log or len(llm_log) < 2:
        return False
    
    # Count classifier and verifier entries
    classifier_count = sum(1 for e in llm_log if e.get('type') == 'classifier')
    verifier_count = sum(1 for e in llm_log if e.get('type') == 'verifier')
    
    # Consensus typically has multiple classification rounds
    # Normal flow: 1 classifier + 1 verifier
    # Consensus: 2+ classifiers + 2+ verifiers (multiple rounds)
    if classifier_count >= 2 and verifier_count >= 1:
        return True
    
    # Alternative: Check for reclassification pattern
    # (classifier after verifier, multiple times)
    last_type = None
    reclassify_cycles = 0
    for entry in llm_log:
        current_type = entry.get('type')
        if last_type == 'verifier' and current_type == 'classifier':
            reclassify_cycles += 1
        last_type = current_type
    
    # 2+ reclassification cycles suggests consensus
    if reclassify_cycles >= 2:
        return True
    
    return False


def reset_consensus_papers(db_path):
    """Find all papers with consensus classifications and reset them."""
    print(f"Connecting to database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        return False
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find all papers with llm_log entries
    print("Analyzing papers for consensus classification history...")
    cursor.execute("SELECT id, llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != ''")
    
    papers_to_reset = []
    analyzed_count = 0
    
    for row in cursor.fetchall():
        paper_id = row['id']
        llm_log_str = row['llm_log']
        analyzed_count += 1
        
        try:
            llm_log = json.loads(llm_log_str) if llm_log_str else []
            if has_consensus_history(llm_log):
                papers_to_reset.append(paper_id)
        except json.JSONDecodeError:
            print(f"Warning: Could not parse llm_log for paper {paper_id}, skipping.")
            continue
        
        # Progress indicator
        if analyzed_count % 500 == 0:
            print(f"  Analyzed {analyzed_count} papers, found {len(papers_to_reset)} with consensus so far...")
    
    total_to_reset = len(papers_to_reset)
    print(f"\nAnalysis complete: {analyzed_count} papers analyzed.")
    print(f"Found {total_to_reset} paper(s) with consensus classification history.")
    
    if total_to_reset == 0:
        print("\nNo papers found with consensus classifications. Nothing to reset.")
        print("\nDebug info - checking for papers with multiple classifications:")
        cursor.execute("""
            SELECT id, llm_log FROM papers 
            WHERE llm_log IS NOT NULL AND llm_log != ''
            LIMIT 5
        """)
        for row in cursor.fetchall():
            try:
                llm_log = json.loads(row['llm_log'])
                classifier_count = sum(1 for e in llm_log if e.get('type') == 'classifier')
                verifier_count = sum(1 for e in llm_log if e.get('type') == 'verifier')
                print(f"  Paper {row['id']}: {classifier_count} classifiers, {verifier_count} verifiers")
            except:
                pass
        conn.close()
        return True
    
    # Confirm before proceeding
    print("\n" + "="*70)
    print("⚠️  ⚠️  ⚠️  CRITICAL WARNING  ⚠️  ⚠️  ⚠️")
    print("="*70)
    print("\nThis will reset the following for all affected papers:")
    print("  ✓ Main classification fields (is_offtopic, is_survey, features, technique, etc.)")
    print("  ✓ last_llm_* cache fields")
    print("  ✓ Verification fields (verified, estimated_score, verified_by)")
    print("  ✓ user_override_count (reset to 0)")
    print("  ✗ llm_log HISTORY WILL BE CLEARED (all classification traces lost)")
    print("\nAfter this operation, these papers will look like NEWLY IMPORTED papers")
    print("with NO classification history whatsoever.")
    print(f"\nDatabase: {db_path}")
    print(f"Total papers affected: {total_to_reset}")
    print("="*70)
    
    # Reset each paper
    reset_timestamp = datetime.utcnow().isoformat() + 'Z'
    default_features = json.dumps(globals.DEFAULT_FEATURES)
    default_technique = json.dumps(globals.DEFAULT_TECHNIQUE)
    empty_llm_log = json.dumps([])
    
    success_count = 0
    error_count = 0
    
    for paper_id in papers_to_reset:
        try:
            cursor.execute("""
                UPDATE papers SET
                    is_offtopic = NULL,
                    is_survey = NULL,
                    is_through_hole = NULL,
                    is_smt = NULL,
                    is_x_ray = NULL,
                    relevance = NULL,
                    research_area = NULL,
                    features = ?,
                    technique = ?,
                    last_llm_is_offtopic = NULL,
                    last_llm_is_survey = NULL,
                    last_llm_is_through_hole = NULL,
                    last_llm_is_smt = NULL,
                    last_llm_is_x_ray = NULL,
                    last_llm_relevance = NULL,
                    last_llm_features = ?,
                    last_llm_technique = ?,
                    verified = NULL,
                    estimated_score = NULL,
                    verified_by = '',
                    changed = ?,
                    changed_by = NULL,
                    user_override_count = 0,
                    llm_log = ?
                WHERE id = ?
            """, (
                default_features,
                default_technique,
                default_features,
                default_technique,
                reset_timestamp,
                empty_llm_log,
                paper_id
            ))
            success_count += 1
        except Exception as e:
            print(f"Error resetting paper {paper_id}: {e}")
            error_count += 1
    
    conn.commit()
    
    print(f"\n{'='*70}")
    print(f"RESET COMPLETE")
    print(f"{'='*70}")
    print(f"Successfully reset: {success_count}")
    print(f"Errors: {error_count}")
    print(f"{'='*70}")
    
    if success_count > 0:
        print(f"\nAll {success_count} paper(s) have been reset to unclassified state.")
        print("llm_log history has been CLEARED for these papers.")
        print("They now appear as newly imported papers with no classification history.")
    
    conn.close()
    return error_count == 0


def main():
    parser = argparse.ArgumentParser(
        description='Reset all papers that have had consensus classifications to unclassified state. CLEARS llm_log history.'
    )
    parser.add_argument(
        '--db_file',
        required=True,  # ← CHANGED: Now REQUIRED, no default
        help='SQLite database file path (REQUIRED - no default from globals.py)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Only show what would be reset without making changes'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt (DANGEROUS - use with caution)'
    )
    
    args = parser.parse_args()
    
    # Validate database path exists before proceeding
    if not os.path.exists(args.db_file):
        print(f"{'='*70}")
        print(f"ERROR: Database file not found")
        print(f"{'='*70}")
        print(f"Path provided: {args.db_file}")
        print(f"\nPlease provide a valid database file path.")
        print(f"Common locations:")
        print(f"  - ./data/db.sqlite")
        print(f"  - /path/to/your/project/data/db.sqlite")
        print(f"\nUse --db_file to specify the correct path.")
        return 1
    
    print(f"{'='*70}")
    print(f"ResearchParça - Consensus Classification Reset Tool")
    print(f"{'='*70}")
    print(f"Database: {args.db_file}")
    print(f"{'='*70}\n")
    
    # Connect and check what would be affected
    conn = sqlite3.connect(args.db_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != ''")
    
    papers_to_reset = []
    analyzed_count = 0
    
    for row in cursor.fetchall():
        paper_id = row['id']
        llm_log_str = row['llm_log']
        analyzed_count += 1
        
        try:
            llm_log = json.loads(llm_log_str) if llm_log_str else []
            if has_consensus_history(llm_log):
                papers_to_reset.append(paper_id)
        except json.JSONDecodeError:
            continue
    
    conn.close()
    
    print(f"Papers analyzed: {analyzed_count}")
    print(f"Papers with consensus history found: {len(papers_to_reset)}")
    
    if len(papers_to_reset) == 0:
        print("\nNo papers found with consensus classifications. Nothing to reset.")
        return 0
    
    if args.dry_run:
        print("\n[DRY RUN] No changes will be made.")
        print("\nFirst 10 paper IDs that would be reset:")
        for pid in papers_to_reset[:10]:
            print(f"  - {pid}")
        if len(papers_to_reset) > 10:
            print(f"  ... and {len(papers_to_reset) - 10} more")
        print("\n⚠️  NOTE: llm_log history WILL BE CLEARED for these papers.")
        return 0
    
    if not args.yes:
        print("\n" + "="*70)
        print("⚠️  ⚠️  ⚠️  CRITICAL WARNING  ⚠️  ⚠️  ⚠️")
        print("="*70)
        print("\nThis will reset the following fields for all affected papers:")
        print("  - Main classification fields (is_offtopic, is_survey, features, technique, etc.)")
        print("  - last_llm_* cache fields")
        print("  - Verification fields (verified, estimated_score, verified_by)")
        print("  - user_override_count (reset to 0)")
        print("  - changed_by (set to NULL)")
        print("  - llm_log (CLEARED - all history lost)")
        print("\n  After this operation, papers will look like NEWLY IMPORTED records")
        print("  with NO classification history whatsoever.")
        print(f"\n  Database: {args.db_file}")
        print(f"  Total papers affected: {len(papers_to_reset)}")
        print("="*70)
        
        response = input("\nAre you SURE you want to proceed? Type 'YES CLEAR ALL' to confirm: ").strip()
        if response != 'YES CLEAR ALL':
            print("Aborted. No changes made.")
            return 0
    
    # Perform the reset
    success = reset_consensus_papers(args.db_file)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())