#probably for v1.0 only
import os
import sys
import sqlite3
import shutil
from datetime import datetime

def get_column_names(db_path):
    """Fetches all column names from the 'papers' table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(papers)")
    # col[1] is the column name
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()
    return cols

def count_on_topic(db_path):
    """Counts records where is_offtopic = 0 (On-Topic)."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 0 = On-Topic, 1 = Off-Topic, NULL = Unknown/Unclassified
        cursor.execute("SELECT COUNT(*) FROM papers WHERE is_offtopic = 0")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        print(f"Error counting {db_path}: {e}")
        return -1

def main():
    # 1. Determine Input Folder
    if len(sys.argv) > 1:
        folder_path = sys.argv[1]
    else:
        folder_path = os.getcwd()
        print(f"No folder specified. Using current directory: {folder_path}")

    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid directory.")
        sys.exit(1)

    # 2. Find Database Files
    # Looking for common SQLite extensions used in the project
    db_files = [f for f in os.listdir(folder_path) 
                if f.endswith('.sqlite') or f.endswith('.db') or f.endswith('.sqlite3')]
    
    # Exclude the output file if it already exists from a previous run
    output_filename = "merged_max_on_topic.sqlite"
    if output_filename in db_files:
        db_files.remove(output_filename)

    if len(db_files) < 1:
        print("No database files found in the specified folder.")
        sys.exit(1)

    full_paths = [os.path.join(folder_path, f) for f in db_files]

    # 3. Analyze and Select Basis DB
    print(f"\nScanning {len(full_paths)} databases...")
    best_db = None
    max_count = -1
    stats = []

    for db in full_paths:
        count = count_on_topic(db)
        stats.append((db, count))
        if count > max_count:
            max_count = count
            best_db = db
    
    # Sort stats for nice printing
    stats.sort(key=lambda x: x[1], reverse=True)
    
    print("\nOn-topic counts per DB:")
    for db, count in stats:
        marker = " <-- BASIS" if db == best_db else ""
        print(f"  [{count:5d}] {os.path.basename(db)}{marker}")

    if not best_db:
        print("Error: Could not determine a basis database.")
        sys.exit(1)

    # 4. Initialize Output DB
    output_path = os.path.join(folder_path, output_filename)
    print(f"\nCopying basis DB to: {output_path}")
    shutil.copy2(best_db, output_path)

    # 5. Merge Logic
    print("Merging on-topic records from other databases...")
    
    # Get columns to update (exclude 'id' which is Primary Key)
    # We fetch from the new output DB to ensure schema consistency
    all_cols = get_column_names(output_path)
    if 'id' in all_cols:
        all_cols.remove('id')
    
    # Prepare UPDATE statement placeholders
    # SET col1 = ?, col2 = ?, ...
    set_clause = ", ".join([f"{col} = ?" for col in all_cols])
    
    conn_out = sqlite3.connect(output_path)
    cursor_out = conn_out.cursor()
    
    total_updates = 0
    other_dbs = [db for db in full_paths if db != best_db]

    for db in other_dbs:
        conn_in = sqlite3.connect(db)
        cursor_in = conn_in.cursor()
        
        # Select ONLY on-topic records from the source DB
        # This minimizes data transfer and processing
        cursor_in.execute("SELECT * FROM papers WHERE is_offtopic = 0")
        rows = cursor_in.fetchall()
        
        updates_in_this_db = 0
        
        for row in rows:
            # Map row values to columns. 
            # Note: row index matches all_cols + 'id' order from PRAGMA, 
            # but we need to be careful about order. 
            # PRAGMA table_info returns columns in definition order.
            # SELECT * returns columns in definition order.
            # So row[i] corresponds to the i-th column in all_cols (plus 'id' at start usually).
            # To be safe, let's map by column index.
            
            # We need the ID to check the target
            # Assuming 'id' is the first column (standard in this project's schema)
            # If not, we should map by name. Let's map by name for safety.
            row_dict = dict(zip(['id'] + all_cols, row))
            paper_id = row_dict['id']
            
            # Check current status in Output DB
            # We only care if the Output DB currently thinks this paper is Off-Topic (1) or Unknown (NULL)
            # If Output DB already has 0, we skip (Basis priority / Optimization)
            cursor_out.execute("SELECT is_offtopic FROM papers WHERE id = ?", (paper_id,))
            res = cursor_out.fetchone()
            
            if res and res[0] != 0:
                # Target is NOT on-topic. Source IS on-topic.
                # Replace the whole row in Output with Source row data.
                
                # Prepare values for update (order must match all_cols)
                values = [row_dict[col] for col in all_cols]
                values.append(paper_id) # For WHERE clause
                
                update_query = f"UPDATE papers SET {set_clause} WHERE id = ?"
                cursor_out.execute(update_query, values)
                updates_in_this_db += 1
        
        conn_in.close()
        if updates_in_this_db > 0:
            print(f"  - {os.path.basename(db)}: Updated {updates_in_this_db} records.")
            total_updates += updates_in_this_db
        else:
            print(f"  - {os.path.basename(db)}: No new on-topic records found.")
            
    conn_out.commit()
    
    # Vacuum to optimize file size after massive updates
    print("Optimizing database file (VACUUM)...")
    cursor_out.execute("VACUUM")
    conn_out.commit()
    conn_out.close()

    print(f"\nMerge Complete.")
    print(f"Total records updated to On-Topic: {total_updates}")
    print(f"Output saved to: {output_path}")

if __name__ == "__main__":
    main()