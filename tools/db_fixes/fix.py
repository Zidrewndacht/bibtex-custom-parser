#!/usr/bin/env python3
"""
fix_verification_data.py

Recalculates verification data from latest valid history entries per set,
averaged according to v1.2 requirements, for all existing papers.

Sources data from set_{1,2,3}_llm_log (NOT set_*_last_llm_* cached columns)
"""

import sqlite3
import json
import os
import sys
from datetime import datetime

# Import globals for paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globals

def get_latest_valid_verification_from_set_llm_log(db_path, paper_id, set_num):
    """
    Extract the latest valid verification data from a specific set's llm_log.
    
    Args:
        db_path: Database path
        paper_id: Paper ID
        set_num: 1, 2, or 3
    
    Returns:
        dict: {'verified': 1/0/None, 'estimated_score': int/None, 'has_data': bool}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get the set-specific llm_log
    log_field = f'set_{set_num}_llm_log'
    cursor.execute(f"SELECT {log_field} FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row[0]:
        return {'verified': None, 'estimated_score': None, 'has_data': False}
    
    try:
        log_entries = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {'verified': None, 'estimated_score': None, 'has_data': False}
    
    # Find latest valid verifier entry (most recent first)
    for entry in reversed(log_entries):
        if entry.get('type') != 'verifier':
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
        
        # Extract verification data
        verified_raw = output.get('verified')
        score_raw = output.get('estimated_score')
        
        # Convert verified to tri-state
        if verified_raw is True or verified_raw == 1:
            verified = 1
        elif verified_raw is False or verified_raw == 0:
            verified = 0
        else:
            verified = None
        
        # Extract score
        if isinstance(score_raw, (int, float)):
            estimated_score = int(score_raw)
        else:
            estimated_score = None
        
        return {
            'verified': verified,
            'estimated_score': estimated_score,
            'has_data': True
        }
    
    return {'verified': None, 'estimated_score': None, 'has_data': False}

def score_to_verified(score):
    """
    Convert verification score to verified tri-state.
    Score >= 7 → verified:yes (1)
    Score < 7 → verified:no (0)
    Score None → verified:unknown (None)
    """
    if score is None:
        return None
    return 1 if score >= 7 else 0

def calculate_verification_certainty(verified_values):
    """
    Calculate certainty for verification field across 3 sets.
    
    Args:
        verified_values: list of 3 values (1=True, 0=False, None=Unknown)
    
    Returns:
        tuple: (main_value, certainty_string)
    """
    if not verified_values or len(verified_values) != 3:
        return None, 'solid'
    
    # Count yes (1), no (0), and null (None)
    yes_count = sum(1 for v in verified_values if v == 1)
    no_count = sum(1 for v in verified_values if v == 0)
    null_count = sum(1 for v in verified_values if v is None)
    
    # Determine majority vote
    if yes_count > no_count:
        main_value = 1
        has_disagreement = (no_count > 0)
    elif no_count > yes_count:
        main_value = 0
        has_disagreement = (yes_count > 0)
    else:
        # Tie or all null
        main_value = None
        has_disagreement = True
    
    # Determine certainty
    if has_disagreement and yes_count > 0 and no_count > 0:
        # Actual conflict (both yes and no present)
        certainty = 'conflict'
    elif null_count == 2:
        # Only 1 value available
        certainty = '60'
    elif null_count == 1:
        # 2 values available, agree
        certainty = '80'
    else:
        # All 3 values agree (or all null)
        certainty = 'solid'
    
    return main_value, certainty

def calculate_score_average(score_values):
    """
    Calculate average of valid scores.
    
    Args:
        score_values: list of 3 scores (int or None)
    
    Returns:
        int or None: Average score, or None if no valid scores
    """
    valid_scores = [s for s in score_values if s is not None]
    if not valid_scores:
        return None
    return int(sum(valid_scores) / len(valid_scores))

def fix_paper_verification(db_path, paper_id):
    """
    Fix verification data for a single paper.
    
    Args:
        db_path: Database path
        paper_id: Paper ID to fix
    
    Returns:
        dict: Updated verification data and certainty
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Fetch paper data
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    paper = cursor.fetchone()
    if not paper:
        conn.close()
        return None
    
    paper = dict(paper)
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # Get latest valid verification from each set's llm_log
    set_verifications = []
    set_scores = []
    
    for set_num in [1, 2, 3]:
        verif_data = get_latest_valid_verification_from_set_llm_log(db_path, paper_id, set_num)
        
        # Convert score to verified per set (score >= 7 → yes, < 7 → no)
        if verif_data['has_data'] and verif_data['estimated_score'] is not None:
            verified_from_score = score_to_verified(verif_data['estimated_score'])
            set_verifications.append(verified_from_score)
            set_scores.append(verif_data['estimated_score'])
        else:
            set_verifications.append(None)
            set_scores.append(None)
    
    # Calculate averaged verification state
    main_verified, verification_certainty = calculate_verification_certainty(set_verifications)
    
    # Calculate averaged estimated score (numeric average of original scores)
    main_score = calculate_score_average(set_scores)
    
    # Update main_certainty
    current_certainty_str = paper.get('main_certainty', '{}')
    try:
        certainty_map = json.loads(current_certainty_str) if current_certainty_str else {}
    except:
        certainty_map = {}
    
    certainty_map['verified'] = verification_certainty
    
    # Update database
    cursor.execute("""
        UPDATE papers SET
            verified = ?,
            estimated_score = ?,
            main_certainty = ?,
            changed = ?,
            changed_by = ?
        WHERE id = ?
    """, (
        main_verified,
        main_score,
        json.dumps(certainty_map),
        changed_timestamp,
        'verification_fix_script',
        paper_id
    ))
    
    # === CREATE/UPDATE MAIN LOG ENTRY ===
    cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    try:
        existing_log = json.loads(row[0]) if row and row[0] else []
    except:
        existing_log = []
    
    # Build full state snapshot for log entry
    cursor.execute("""
        SELECT is_offtopic, is_survey, is_through_hole, is_smt, is_x_ray,
               relevance, features, technique, user_trace
        FROM papers WHERE id = ?
    """, (paper_id,))
    main_data = cursor.fetchone()
    
    def db_to_bool(val):
        if val == 1:
            return True
        elif val == 0:
            return False
        else:
            return None
    
    try:
        features = json.loads(main_data[6]) if main_data[6] else {}
    except:
        features = {}
    
    try:
        technique = json.loads(main_data[7]) if main_data[7] else {}
    except:
        technique = {}
    
    user_log_output = {
        "is_offtopic": db_to_bool(main_data[0]),
        "is_survey": db_to_bool(main_data[1]),
        "is_through_hole": db_to_bool(main_data[2]),
        "is_smt": db_to_bool(main_data[3]),
        "is_x_ray": db_to_bool(main_data[4]),
        "relevance": main_data[5],
        "features": features,
        "technique": technique,
        "verified": db_to_bool(main_verified),
        "estimated_score": main_score
    }
    
    # Check if last entry was also an averaged_llm entry (consolidate)
    if existing_log and existing_log[-1].get('type') == 'averaged_llm':
        existing_log[-1] = {
            "timestamp": changed_timestamp,
            "type": "averaged_llm",
            "model": "averaged_3_sets",
            "trace": f"Verification recalculation from latest valid history entries per set",
            "output": json.dumps(user_log_output),
            "valid": True,
            "certainty_map": certainty_map
        }
    else:
        log_entry = {
            "timestamp": changed_timestamp,
            "type": "averaged_llm",
            "model": "averaged_3_sets",
            "trace": f"Verification recalculation from latest valid history entries per set",
            "output": json.dumps(user_log_output),
            "valid": True,
            "certainty_map": certainty_map
        }
        existing_log.append(log_entry)
    
    cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
    
    conn.commit()
    conn.close()
    
    return {
        'verified': main_verified,
        'estimated_score': main_score,
        'certainty': verification_certainty,
        'set_verifications': set_verifications,
        'set_scores': set_scores
    }

def main():
    """Main function to fix all papers in the database."""
    db_path = globals.DATABASE_FILE
    
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all paper IDs
    cursor.execute("SELECT id FROM papers")
    paper_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    total_papers = len(paper_ids)
    print(f"Starting verification data fix for {total_papers} papers...")
    print(f"Database: {db_path}")
    print()
    print("Sourcing data from: set_{1,2,3}_llm_log (latest valid verifier entries)")
    print("NOT from: set_*_last_llm_* cached columns (bogus)")
    print()
    
    # Statistics
    stats = {
        'solid_yes': 0,
        'solid_no': 0,
        'solid_unknown': 0,
        '80_percent': 0,
        '60_percent': 0,
        'conflict': 0,
        'errors': 0
    }
    
    # Process each paper
    for i, paper_id in enumerate(paper_ids, 1):
        try:
            result = fix_paper_verification(db_path, paper_id)
            
            if result:
                certainty = result['certainty']
                verified = result['verified']
                
                # Update statistics
                if certainty == 'solid':
                    if verified == 1:
                        stats['solid_yes'] += 1
                    elif verified == 0:
                        stats['solid_no'] += 1
                    else:
                        stats['solid_unknown'] += 1
                elif certainty == '80':
                    stats['80_percent'] += 1
                elif certainty == '60':
                    stats['60_percent'] += 1
                elif certainty == 'conflict':
                    stats['conflict'] += 1
                
                # Progress output
                if i % 100 == 0 or i == total_papers:
                    print(f"Progress: {i}/{total_papers} papers processed ({i/total_papers*100:.1f}%)")
            else:
                stats['errors'] += 1
                print(f"  Warning: Paper {paper_id} not found or error occurred")
        
        except Exception as e:
            stats['errors'] += 1
            print(f"  Error processing paper {paper_id}: {e}")
    
    # Print summary
    print()
    print("=" * 70)
    print("VERIFICATION DATA FIX COMPLETE")
    print("=" * 70)
    print(f"Total papers processed: {total_papers}")
    print()
    print("Verification certainty distribution:")
    print(f"  Solid (Yes):     {stats['solid_yes']:6d}")
    print(f"  Solid (No):      {stats['solid_no']:6d}")
    print(f"  Solid (Unknown): {stats['solid_unknown']:6d}")
    print(f"  80% (2/3 agree): {stats['80_percent']:6d}")
    print(f"  60% (1/3 known): {stats['60_percent']:6d}")
    print(f"  Conflict:        {stats['conflict']:6d}")
    print(f"  Errors:          {stats['errors']:6d}")
    print()
    print("Main row fields updated:")
    print("  - verified (tri-state based on score >= 7 threshold per set)")
    print("  - estimated_score (numeric average of latest valid scores per set)")
    print("  - main_certainty (for verified field)")
    print("  - llm_log (new/updated averaged_llm entry with full snapshot)")
    print()
    print("Data source: set_{1,2,3}_llm_log (latest valid verifier entries)")
    print("NOT from: set_*_last_llm_* cached columns")
    print("=" * 70)

if __name__ == "__main__":
    main()