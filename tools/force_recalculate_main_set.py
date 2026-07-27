# patch_db.py
# Forces recalculate_main_set;
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import config, db

def main():
    db.init_db(config.DATABASE_FILE)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, verified, verified_by, classification FROM papers")
        papers = cursor.fetchall()
        
        sql_updates = []
        json_updates = []
        
        for row in papers:
            paper_id, sql_verified, sql_verified_by, class_json = row
            
            # Parse JSON blob
            try:
                c = json.loads(class_json) if class_json else {}
            except Exception:
                c = {}
                
            json_verified = c.get('verified')
            json_verified_by = c.get('verified_by')
            
            # Ground truth: Is there an active AI verification decision?
            is_ai_verified = (sql_verified in (0, 1)) or (json_verified in (True, False, 0, 1))
            
            # Respect explicit 'user' overrides
            if sql_verified_by == 'user' or json_verified_by == 'user':
                continue
                
            target_verified_by = 'computer' if is_ai_verified else None
            
            # Queue SQL column update if needed
            if sql_verified_by != target_verified_by:
                sql_updates.append((target_verified_by, paper_id))
                
            # Queue JSON blob update if needed (keeps backend state perfectly synced)
            if json_verified_by != target_verified_by:
                c['verified_by'] = target_verified_by
                json_updates.append((json.dumps(c), paper_id))

        # Execute batch updates
        if sql_updates:
            cursor.executemany("UPDATE papers SET verified_by = ? WHERE id = ?", sql_updates)
        if json_updates:
            cursor.executemany("UPDATE papers SET classification = ? WHERE id = ?", json_updates)
            
        if sql_updates or json_updates:
            conn.commit()
            print(f"✅ Patched {len(sql_updates)} SQL rows and {len(json_updates)} JSON blobs.")
        else:
            print("✨ Database is already perfectly synced. Nothing to patch.")

if __name__ == '__main__':
    main()