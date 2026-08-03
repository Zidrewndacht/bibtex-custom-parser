#!/usr/bin/env python3
"""
ResearchParça Database Reset Script (v1.4 Domain-Agnostic)

Resets a v1.4 database to freshly-imported state while preserving:
- Core bibliographic data
- User comments (user_trace)
- PDF files and their states

Clears:
- All LLM classifications (classification, last_llm_classification, set_*_llm JSON blobs)
- All verifications (verified, estimated_score, verified_by)
- All timestamps and audit fields (changed, changed_by, user_override_count)
- All LLM logs (llm_log, set_*_llm_log)
- All certainty maps (main_certainty)

Note: In v1.4, domain-specific fields (like research_area, model, features, etc.) 
are stored dynamically inside the 'classification' JSON blob. Clearing this blob 
will also remove user edits to these inferred fields.
"""

import sqlite3
import os
import sys
import shutil
from datetime import datetime

# Configuration
DEFAULT_DB_PATH = os.path.join(os.getcwd(), 'data', 'db.sqlite')
BACKUP_DIR = os.path.join(os.getcwd(), 'data', 'backups')

def create_backup(db_path):
    """Create a timestamped backup of the database."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"db_backup_{timestamp}.sqlite")
    shutil.copy2(db_path, backup_path)
    print(f"✓ Backup created: {backup_path}")
    return backup_path

def reset_database(db_path):
    """Reset all LLM-related fields to NULL/empty while preserving core data."""
    
    # Fields to CLEAR and their target reset values for v1.4 domain-agnostic schema
    clear_fields_map = {
        # Audit & Verification columns
        'changed': 'NULL',
        'changed_by': 'NULL',
        'verified': 'NULL',
        'verified_by': "''",
        'estimated_score': 'NULL',
        'user_override_count': '0',
        
        # Main JSON blobs
        'main_certainty': "'{}'",
        'classification': "'{}'",
        'last_llm_classification': "'{}'",
        
        # Set-specific raw LLM blobs
        'set_1_llm': 'NULL',
        'set_2_llm': 'NULL',
        'set_3_llm': 'NULL',
        
        # Log arrays
        'llm_log': "'[]'",
        'set_1_llm_log': "'[]'",
        'set_2_llm_log': "'[]'",
        'set_3_llm_log': "'[]'",
    }
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        # Verify database structure
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
        if not cursor.fetchone():
            print("✗ Error: 'papers' table not found in database")
            return False
        
        # Get all column names to verify we're not missing anything
        cursor.execute("PRAGMA table_info(papers)")
        all_columns = [col[1] for col in cursor.fetchall()]
        
        print(f"✓ Database has {len(all_columns)} columns")
        
        # Count papers before reset
        cursor.execute("SELECT COUNT(*) FROM papers")
        total_papers = cursor.fetchone()[0]
        print(f"✓ Total papers in database: {total_papers}")
        
        # Build UPDATE statement
        clear_assignments = []
        for field, reset_val in clear_fields_map.items():
            if field in all_columns:
                clear_assignments.append(f"{field} = {reset_val}")
            else:
                print(f"⚠ Field '{field}' not found in database (schema mismatch?)")
        
        if not clear_assignments:
            print("✗ Error: No fields to clear")
            return False
        
        update_query = f"UPDATE papers SET {', '.join(clear_assignments)}"
        
        print(f"✓ Executing reset query...")
        cursor.execute(update_query)
        conn.commit()
        
        rows_affected = cursor.rowcount
        print(f"✓ Reset {rows_affected} paper records")
        
        # Verify reset worked
        cursor.execute("""
            SELECT COUNT(*) FROM papers 
            WHERE changed_by IS NOT NULL 
            OR verified IS NOT NULL 
            OR classification != '{}'
        """)
        remaining_classified = cursor.fetchone()[0]
        
        if remaining_classified > 0:
            print(f"⚠ Warning: {remaining_classified} papers still have classification data")
        else:
            print("✓ All classifications cleared successfully")
        
        # Show preserved data stats
        cursor.execute("SELECT COUNT(*) FROM papers WHERE user_trace IS NOT NULL AND user_trace != ''")
        papers_with_comments = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM papers WHERE pdf_filename IS NOT NULL AND pdf_filename != ''")
        papers_with_pdf = cursor.fetchone()[0]
        
        print(f"✓ Preserved {papers_with_comments} papers with user comments")
        print(f"✓ Preserved {papers_with_pdf} papers with PDF files")
        
        # Vacuum database to reclaim space
        print("✓ Optimizing database...")
        cursor.execute("VACUUM")
        conn.commit()
        
        print("\n" + "="*60)
        print("DATABASE RESET COMPLETE (v1.4 Domain-Agnostic)")
        print("="*60)
        print(f"Total papers: {total_papers}")
        print(f"Papers with user comments: {papers_with_comments}")
        print(f"Papers with PDFs: {papers_with_pdf}")
        print(f"All LLM classifications (JSON blobs): CLEARED")
        print(f"All verification data: CLEARED")
        print(f"All logs & certainty maps: CLEARED")
        print("="*60)
        
        return True
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {type(e).__name__}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def main():
    print("="*60)
    print("ResearchParça Database Reset Tool (v1.4 Domain-Agnostic)")
    print("="*60)
    print()
    
    # Get database path
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = DEFAULT_DB_PATH
    
    print(f"Database path: {db_path}")
    
    # Check if database exists
    if not os.path.exists(db_path):
        print(f"✗ Error: Database file not found: {db_path}")
        print("   Please provide the correct path as an argument")
        sys.exit(1)
    
    # Confirm action
    print()
    print("⚠ WARNING: This will permanently clear all LLM classifications,")
    print("   verifications, logs, and audit data from the database.")
    print()
    print("   The following will be PRESERVED:")
    print("   • Core bibliographic data (title, authors, journal, etc.)")
    print("   • User comments (user_trace)")
    print("   • PDF files and their states")
    print()
    print("   Note: In v1.4, domain-specific fields (like research_area, model,")
    print("   features, etc.) are stored inside the 'classification' JSON blob.")
    print("   Clearing this blob will also remove user edits to these fields.")
    print()
    
    response = input("Continue? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Operation cancelled.")
        sys.exit(0)
    
    print()
    
    # Create backup
    print("Step 1/2: Creating backup...")
    backup_path = create_backup(db_path)
    print()
    
    # Reset database
    print("Step 2/2: Resetting database...")
    success = reset_database(db_path)
    print()
    
    if success:
        print("✓ Database reset successful!")
        print(f"✓ Backup available at: {backup_path}")
        print()
        print("You can now run classification/verification on the reset database.")
        sys.exit(0)
    else:
        print("✗ Database reset failed!")
        print(f"✓ Backup still available at: {backup_path}")
        print("   You can restore from backup if needed.")
        sys.exit(1)

if __name__ == '__main__':
    main()