# standalone debug tool, used during development.
import os
import sys

# Ensure the shared modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import config, db


def main():
    db_path = config.DATABASE_FILE
    print(f"Initializing database at: {db_path}")
    db.init_db(db_path)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Fetch all paper IDs and titles
        cursor.execute("SELECT id, title FROM papers")
        papers = cursor.fetchall()
        
    total = len(papers)
    print(f"Found {total} papers in the database.\n")
    
    recalculated_count = 0
    for i, row in enumerate(papers):
        paper_id = row['id']
        title = row['title'] or ""
        
        # Skip the default placeholder paper
        if paper_id == '1' and 'Database is missing or empty' in title:
            print("Skipping placeholder paper...")
            continue
            
        # Recalculate without creating a new history log entry to avoid spamming the UI
        db.recalculate_main_set(
            paper_id, 
            changed_by="Script_Force_Recalculate", 
            create_log_entry=False
        )
        recalculated_count += 1
        
        # Print progress every 50 papers
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"Progress: {i + 1}/{total} papers processed...")
            
    print(f"\n✅ Successfully recalculated {recalculated_count} papers.")
    print("👉 You can now refresh the frontend to see the updated text fields.")

if __name__ == '__main__':
    main()