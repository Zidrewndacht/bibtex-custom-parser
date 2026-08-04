"""
invalidate_bogus_log_entries.py

Scans set_1/2/3_llm_log columns and marks malformed entries as invalid.
Does NOT touch main llm_log (which should never have invalid entries).

Usage:
    python fix_invalid_log_entries.py [database_path]
"""

import sqlite3
import json
import sys
import os

REQUIRED_CLASSIFICATION_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    'relevance', 'features', 'technique'
]

REQUIRED_VERIFIER_FIELDS = ['verified', 'estimated_score']

# ONLY check set logs, NOT main llm_log
SET_LOG_COLUMNS = ['set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']


def is_valid_classification_entry(entry):
    """Check if a classification-type entry has all required fields."""
    if entry.get('type') not in ['classifier', 'consensus', 'averaged_llm', 'user']:
        return True, []
    
    output_raw = entry.get('output', '{}')
    
    if isinstance(output_raw, str):
        try:
            output = json.loads(output_raw) if output_raw else {}
        except (json.JSONDecodeError, TypeError):
            return False, ['output_parse_error']
    elif isinstance(output_raw, dict):
        output = output_raw
    else:
        return False, ['output_not_dict']
    
    if not isinstance(output, dict):
        return False, ['output_not_dict']
    
    missing = [f for f in REQUIRED_CLASSIFICATION_FIELDS if f not in output]
    
    if missing:
        return False, missing
    
    return True, []


def is_valid_verifier_entry(entry, previous_entry_valid):
    """Check if a verifier entry is valid."""
    if entry.get('type') != 'verifier':
        return True, None
    
    if not previous_entry_valid:
        return False, 'verifies_invalid_classification'
    
    output_raw = entry.get('output', '{}')
    
    if isinstance(output_raw, str):
        try:
            output = json.loads(output_raw) if output_raw else {}
        except (json.JSONDecodeError, TypeError):
            return False, ['output_parse_error']
    elif isinstance(output_raw, dict):
        output = output_raw
    else:
        return False, ['output_not_dict']
    
    if not isinstance(output, dict):
        return False, ['output_not_dict']
    
    missing = [f for f in REQUIRED_VERIFIER_FIELDS if f not in output]
    
    if missing:
        return False, f'missing_fields: {", ".join(missing)}'
    
    return True, None


def fix_set_log(paper_id, log_column, current_log):
    """Fix a single set log's entries."""
    fixed_log = []
    changes_made = False
    previous_entry_valid = True
    
    for i, entry in enumerate(current_log):
        entry_type = entry.get('type', 'unknown')
        
        if entry_type in ['classifier', 'consensus', 'averaged_llm', 'user']:
            is_valid, missing = is_valid_classification_entry(entry)
            
            if not is_valid:
                if entry.get('valid', True):
                    print(f"  {paper_id} [{log_column}]: Entry {i} ({entry_type}) marked invalid - Missing: {missing}")
                    entry['valid'] = False
                    entry['invalid_reason'] = f'Missing required fields: {", ".join(missing)}'
                    changes_made = True
                elif not entry.get('valid', False):
                    if 'invalid_reason' not in entry:
                        entry['invalid_reason'] = f'Missing required fields: {", ".join(missing)}'
            
            previous_entry_valid = entry.get('valid', True)
            
        elif entry_type == 'verifier':
            is_valid, reason = is_valid_verifier_entry(entry, previous_entry_valid)
            
            if not is_valid:
                if entry.get('valid', True):
                    print(f"  {paper_id} [{log_column}]: Entry {i} (verifier) marked invalid - Reason: {reason}")
                    entry['valid'] = False
                    entry['invalid_reason'] = reason
                    changes_made = True
                elif not entry.get('valid', False):
                    if 'invalid_reason' not in entry:
                        entry['invalid_reason'] = reason
            
            previous_entry_valid = True
        
        fixed_log.append(entry)
    
    return fixed_log, changes_made


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
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # === DEBUG: Check specific paper first ===
    target_paper = 'zhou_toward_2023'
    print(f"\n=== DEBUG: Checking paper '{target_paper}' ===")
    
    for log_col in SET_LOG_COLUMNS:
        cursor.execute(f"SELECT id, {log_col} FROM papers WHERE id = ?", (target_paper,))
        row = cursor.fetchone()
        
        if row and row[log_col]:
            try:
                log = json.loads(row[log_col])
                print(f"\n{log_col}: {len(log)} entries")
                for i, entry in enumerate(log):
                    entry_type = entry.get('type', 'UNKNOWN')
                    valid = entry.get('valid', 'NOT_SET')
                    output_raw = entry.get('output', 'NOT_SET')
                    
                    print(f"  Entry {i}: type={entry_type}, valid={valid}")
                    
                    if isinstance(output_raw, str):
                        try:
                            output = json.loads(output_raw)
                            keys = list(output.keys())
                            print(f"    output keys: {keys}")
                            
                            if entry_type in ['classifier', 'consensus']:
                                missing = [f for f in REQUIRED_CLASSIFICATION_FIELDS if f not in output]
                                if missing:
                                    print(f"    ⚠️  MALFORMED: Missing fields: {missing}")
                                else:
                                    print(f"    ✓ Has all required classification fields")
                        except Exception as e:
                            print(f"    ⚠️  ERROR parsing output: {e}")
                    elif isinstance(output_raw, dict):
                        print(f"    output keys: {list(output_raw.keys())}")
                    else:
                        print(f"    output type: {type(output_raw)}")
            except Exception as e:
                print(f"\n{log_col}: ERROR - {e}")
        else:
            print(f"\n{log_col}: (empty or null)")
    
    # === Now scan all papers ===
    print(f"\n=== Scanning all papers (SET LOGS ONLY) ===")
    
    # Build column list for query
    column_list = 'id, ' + ', '.join(SET_LOG_COLUMNS)
    cursor.execute(f"SELECT {column_list} FROM papers")
    papers = cursor.fetchall()
    total_papers = len(papers)
    
    print(f"Found {total_papers} papers to process")
    print("=" * 60)
    
    fixed_count = 0
    total_invalid = 0
    
    for paper in papers:
        paper_id = paper['id']
        paper_changes = False
        
        for log_col in SET_LOG_COLUMNS:
            llm_log_str = paper[log_col]
            
            try:
                current_log = json.loads(llm_log_str) if llm_log_str else []
            except (json.JSONDecodeError, TypeError):
                continue
            
            if not current_log:
                continue
            
            fixed_log, changes_made = fix_set_log(paper_id, log_col, current_log)
            
            if changes_made:
                cursor.execute(
                    f"UPDATE papers SET {log_col} = ? WHERE id = ?",
                    (json.dumps(fixed_log), paper_id)
                )
                paper_changes = True
            
            # Count invalid entries
            for entry in fixed_log:
                if not entry.get('valid', True):
                    total_invalid += 1
        
        if paper_changes:
            fixed_count += 1
    
    conn.commit()
    conn.close()
    
    print("=" * 60)
    print(f"Fix complete!")
    print(f"  Papers processed: {total_papers}")
    print(f"  Papers fixed: {fixed_count}")
    print(f"  Invalid entries found: {total_invalid}")
    print(f"  Database: {db_path}")
    print("=" * 60)
    print("\n⚠️  NOTE: Main llm_log was NOT checked (as designed).")
    print("   Only set_1/2/3_llm_log columns were validated.")


if __name__ == "__main__":
    main()