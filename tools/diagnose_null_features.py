import sqlite3
import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_null_features.py <path_to_db>")
        sys.exit(1)

    db_path = sys.argv[1]
    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print(f"Scanning {db_path} for incomplete classifications...")

    # 1. Find papers where consensus finished (is_offtopic is set) but features/technique are NULL
    # We check if features is NULL or empty string, assuming technique follows the same pattern
    cursor.execute("""
SELECT id, set_1_last_llm_features
FROM papers
WHERE set_1_last_llm_is_offtopic = 0  -- Only check ON-TOPIC papers
  AND (set_1_last_llm_features IS NULL OR set_1_last_llm_features = '')
    """)

    rows = cursor.fetchall()
    
    if not rows:
        print("No discrepancies found. All completed papers have features populated.")
        conn.close()
        return

    print(f"Found {len(rows)} papers with discrepancies.\n")
    print(f"{'ID':<10} | {'Set':<3} | {'Reason (from Log)'}")
    print("-" * 80)

    for row in rows:
        paper_id = row['id']
        
        for set_num in [1, 2, 3]:
            is_offtopic = row[f'set_{set_num}_last_llm_is_offtopic']
            features = row[f'set_{set_num}_last_llm_features']
            
            # Check if this specific set is the culprit
            if is_offtopic is not None and (features is None or features == ''):
                # Fetch the log for this set to find the error
                log_col = f'set_{set_num}_llm_log'
                log_data = row[log_col]
                error_summary = "No log entry found"
                
                if log_data:
                    try:
                        log_entries = json.loads(log_data)
                        # Find the last invalid entry or the reason for the final state
                        for entry in reversed(log_entries):
                            if not entry.get('valid', True):
                                output = entry.get('output', '')
                                # Truncate long error messages
                                msg = output[:100] + "..." if len(output) > 100 else output
                                error_summary = f"{entry.get('type', 'unknown')}: {msg}"
                                break
                        else:
                            # If all entries are valid but features are empty, it might be a schema mismatch
                            if log_entries:
                                last_entry = log_entries[-1]
                                error_summary = f"Valid response but empty keys? Output: {str(last_entry.get('output', ''))[:80]}..."
                    except json.JSONDecodeError:
                        error_summary = "Invalid JSON in log"
                
                print(f"{paper_id:<10} | {set_num:<3} | {error_summary}")

    conn.close()

if __name__ == '__main__':
    main()