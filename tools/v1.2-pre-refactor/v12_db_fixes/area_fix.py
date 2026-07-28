#!/usr/bin/env python3
"""
migrate_research_area_fields.py

Adds missing research_area fields to set-specific classification columns
and populates them from existing main research_area data.

This fixes the "Missing key 'research_area'" error in verification prompts.

Usage:
    python migrate_research_area_fields.py [database_path]
"""

import sqlite3
import json
import sys
import os

# Fields to add for each set
SET_FIELDS = [
    'set_1_last_llm_research_area TEXT',
    'set_2_last_llm_research_area TEXT',
    'set_3_last_llm_research_area TEXT',
    'last_llm_research_area TEXT',  # Averaged cache field
]

def add_missing_columns(cursor, table_name='papers'):
    """Add missing research_area columns if they don't exist."""
    # Get existing columns
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    columns_added = []
    for field_def in SET_FIELDS:
        col_name = field_def.split()[0]
        if col_name not in existing_columns:
            print(f"Adding column: {col_name}")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {field_def}")
            columns_added.append(col_name)
        else:
            print(f"Column already exists: {col_name}")
    
    return columns_added

def populate_research_area_from_main(cursor, db_path):
    """
    Populate set-specific research_area fields from main research_area column.
    Also updates any papers where set fields are NULL but main has data.
    """
    # Check if main research_area column exists
    cursor.execute("PRAGMA table_info(papers)")
    columns = {row[1] for row in cursor.fetchall()}
    
    if 'research_area' not in columns:
        print("WARNING: Main 'research_area' column does not exist. Cannot populate data.")
        return 0
    
    # Update all set fields from main research_area where they are NULL
    update_queries = [
        "UPDATE papers SET set_1_last_llm_research_area = research_area WHERE set_1_last_llm_research_area IS NULL AND research_area IS NOT NULL",
        "UPDATE papers SET set_2_last_llm_research_area = research_area WHERE set_2_last_llm_research_area IS NULL AND research_area IS NOT NULL",
        "UPDATE papers SET set_3_last_llm_research_area = research_area WHERE set_3_last_llm_research_area IS NULL AND research_area IS NOT NULL",
        "UPDATE papers SET last_llm_research_area = research_area WHERE last_llm_research_area IS NULL AND research_area IS NOT NULL",
    ]
    
    total_updated = 0
    for query in update_queries:
        cursor.execute(query)
        updated = cursor.rowcount
        total_updated += updated
        print(f"Updated {updated} rows for query: {query.split('SET')[1].split('WHERE')[0].strip()}")
    
    return total_updated

def populate_from_history_if_needed(cursor, db_path):
    """
    For papers where research_area is still NULL, try to extract from llm_log history.
    This is a fallback for papers that may have been classified before this migration.
    """
    print("\nChecking for papers with NULL research_area that might have data in history...")
    
    # Get papers with NULL research_area but non-empty llm_log
    cursor.execute("""
        SELECT id, llm_log FROM papers 
        WHERE research_area IS NULL 
        AND llm_log IS NOT NULL 
        AND llm_log != ''
        LIMIT 100
    """)
    
    papers_to_check = cursor.fetchall()
    updated_count = 0
    
    for paper_id, llm_log_str in papers_to_check:
        try:
            log_entries = json.loads(llm_log_str) if llm_log_str else []
            
            # Find the most recent valid classifier/averaged_llm entry with research_area
            for entry in reversed(log_entries):
                if entry.get('type') in ['classifier', 'averaged_llm', 'consensus'] and entry.get('valid', False):
                    output = entry.get('output', {})
                    if isinstance(output, str):
                        try:
                            output = json.loads(output)
                        except:
                            continue
                    
                    research_area = output.get('research_area')
                    if research_area:
                        # Update main and all set fields
                        cursor.execute("""
                            UPDATE papers SET 
                                research_area = ?,
                                set_1_last_llm_research_area = ?,
                                set_2_last_llm_research_area = ?,
                                set_3_last_llm_research_area = ?,
                                last_llm_research_area = ?
                            WHERE id = ?
                        """, (research_area, research_area, research_area, research_area, research_area, paper_id))
                        updated_count += 1
                        print(f"  Updated paper {paper_id} from history")
                        break
        except Exception as e:
            print(f"  Error processing paper {paper_id}: {e}")
            continue
    
    return updated_count

def verify_migration(cursor):
    """Verify the migration completed successfully."""
    print("\n=== Migration Verification ===")
    
    # Check column existence
    cursor.execute("PRAGMA table_info(papers)")
    columns = {row[1] for row in cursor.fetchall()}
    
    required_columns = [
        'research_area',
        'set_1_last_llm_research_area',
        'set_2_last_llm_research_area',
        'set_3_last_llm_research_area',
        'last_llm_research_area'
    ]
    
    all_present = True
    for col in required_columns:
        status = "✓" if col in columns else "✗"
        print(f"  {status} {col}")
        if col not in columns:
            all_present = False
    
    # Check data population
    cursor.execute("SELECT COUNT(*) FROM papers WHERE research_area IS NOT NULL")
    main_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE set_1_last_llm_research_area IS NOT NULL")
    set1_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE set_2_last_llm_research_area IS NOT NULL")
    set2_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE set_3_last_llm_research_area IS NOT NULL")
    set3_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE last_llm_research_area IS NOT NULL")
    avg_count = cursor.fetchone()[0]
    
    print(f"\nData population:")
    print(f"  Main research_area: {main_count} papers")
    print(f"  Set 1: {set1_count} papers")
    print(f"  Set 2: {set2_count} papers")
    print(f"  Set 3: {set3_count} papers")
    print(f"  Averaged cache: {avg_count} papers")
    
    return all_present

def main():
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = os.path.join(os.getcwd(), 'data', 'db.sqlite')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Connecting to database: {db_path}")
    print("=" * 60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Step 1: Add missing columns
        print("\n=== Step 1: Adding Missing Columns ===")
        columns_added = add_missing_columns(cursor)
        conn.commit()
        
        if not columns_added:
            print("No new columns needed (all already exist).")
        
        # Step 2: Populate from main research_area
        print("\n=== Step 2: Populating from Main research_area Column ===")
        updated = populate_research_area_from_main(cursor, db_path)
        conn.commit()
        print(f"Total rows updated: {updated}")
        
        # Step 3: Fallback - populate from history for remaining NULLs
        print("\n=== Step 3: Fallback - Extracting from History ===")
        history_updated = populate_from_history_if_needed(cursor, db_path)
        conn.commit()
        print(f"Updated from history: {history_updated} papers")
        
        # Step 4: Verify migration
        print("\n=== Step 4: Verification ===")
        success = verify_migration(cursor)
        
        print("\n" + "=" * 60)
        if success:
            print("Migration completed successfully!")
            print("\nNext steps:")
            print("1. Restart the verification process")
            print("2. The 'Missing key research_area' error should be resolved")
        else:
            print("Migration completed with warnings. Check output above.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()