
# convert_conference_to _inproceedings.py
# Single-use tool to fix previously imported conferences that weren't normalized to "inproceedings" type.
import sqlite3
import argparse

def fix_conference_type(db_path):
    """Change all entries with type 'conference' to 'inproceedings'."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Count how many entries have type 'conference'
    cursor.execute("SELECT COUNT(*) FROM papers WHERE type = 'conference'")
    count = cursor.fetchone()[0]
    
    if count == 0:
        print("No entries with type 'conference' found.")
        conn.close()
        return
    
    print(f"Found {count} entries with type 'conference'.")
    
    # Update all entries with type 'conference' to 'inproceedings'
    cursor.execute("UPDATE papers SET type = 'inproceedings' WHERE type = 'conference'")
    
    conn.commit()
    
    print(f"Updated {count} entries from 'conference' to 'inproceedings'.")
    
    # Verify the change
    cursor.execute("SELECT COUNT(*) FROM papers WHERE type = 'conference'")
    remaining = cursor.fetchone()[0]
    
    if remaining == 0:
        print("All 'conference' entries have been successfully updated.")
    else:
        print(f"Warning: {remaining} entries still have type 'conference'.")
    
    conn.close()

def preview_changes(db_path):
    """Preview the entries that would be changed."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, title, year, journal 
        FROM papers 
        WHERE type = 'conference'
    """)
    results = cursor.fetchall()
    
    if results:
        print(f"Found {len(results)} entries with type 'conference':")
        for entry_id, title, year, journal in results:
            print(f"  - {entry_id}: '{title}' ({year}) - {journal}")
    else:
        print("No entries with type 'conference' found.")
    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Change all entries with type "conference" to "inproceedings"')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('--preview', action='store_true', help='Preview changes without applying them')
    args = parser.parse_args()
    
    if args.preview:
        preview_changes(args.db_file)
    else:
        print("This will change all entries with type 'conference' to 'inproceedings'.")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() in ['yes', 'y']:
            fix_conference_type(args.db_file)
        else:
            print("Operation cancelled.")