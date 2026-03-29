#!/usr/bin/env python3
"""
ResearchParça Database Reset Script
Resets a v1.2 database to freshly-imported state while preserving:
- Core bibliographic data
- User comments (user_trace)
- User-set research areas
- PDF files and their states

Clears:
- All LLM classifications (is_offtopic, is_survey, features, technique, etc.)
- All verifications (verified, estimated_score, verified_by)
- All timestamps and audit fields (changed, changed_by, user_override_count)
- All LLM logs (llm_log, set_*_llm_log)
- All cached LLM fields (set_*_last_llm_*, last_llm_*)
- All certainty maps (main_certainty)
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
    
    # Fields to CLEAR (LLM classifications, verifications, logs, audit)
    clear_fields = [
        # Classification booleans
        'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
        # Verification fields
        'relevance', 'verified', 'estimated_score', 'verified_by',
        # JSON fields
        'features', 'technique',
        # Audit fields
        'changed', 'changed_by', 'user_override_count',
        # Certainty
        'main_certainty',
        # Main log
        'llm_log',
        # Set-specific logs (3 sets)
        'set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log',
        # Set-specific cached classification fields (3 sets × 9 fields)
        'set_1_last_llm_is_offtopic', 'set_1_last_llm_is_survey', 
        'set_1_last_llm_is_through_hole', 'set_1_last_llm_is_smt', 
        'set_1_last_llm_is_x_ray', 'set_1_last_llm_relevance',
        'set_1_last_llm_verified', 'set_1_last_llm_estimated_score',
        'set_1_last_llm_features', 'set_1_last_llm_technique',
        
        'set_2_last_llm_is_offtopic', 'set_2_last_llm_is_survey', 
        'set_2_last_llm_is_through_hole', 'set_2_last_llm_is_smt', 
        'set_2_last_llm_is_x_ray', 'set_2_last_llm_relevance',
        'set_2_last_llm_verified', 'set_2_last_llm_estimated_score',
        'set_2_last_llm_features', 'set_2_last_llm_technique',
        
        'set_3_last_llm_is_offtopic', 'set_3_last_llm_is_survey', 
        'set_3_last_llm_is_through_hole', 'set_3_last_llm_is_smt', 
        'set_3_last_llm_is_x_ray', 'set_3_last_llm_relevance',
        'set_3_last_llm_verified', 'set_3_last_llm_estimated_score',
        'set_3_last_llm_features', 'set_3_last_llm_technique',
        
        # Last LLM cache fields (mirrors main fields)
        'last_llm_is_offtopic', 'last_llm_is_survey', 
        'last_llm_is_through_hole', 'last_llm_is_smt', 
        'last_llm_is_x_ray', 'last_llm_relevance',
        'last_llm_verified', 'last_llm_estimated_score',
        'last_llm_features', 'last_llm_technique',
    ]
    
    # Fields to PRESERVE (core bibliographic + user data)
    preserve_fields = [
        'id', 'type', 'title', 'authors', 'year', 'month', 
        'journal', 'volume', 'pages', 'page_count', 'doi', 'issn', 
        'abstract', 'keywords', 'deannualized_conference',
        # User metadata
        'research_area', 'user_trace',
        # PDF management
        'pdf_filename', 'pdf_state'
    ]
    
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
        for field in clear_fields:
            # Check if field exists in this database version
            if field in all_columns:
                if field in ['features', 'technique']:
                    # JSON fields should be NULL
                    clear_assignments.append(f"{field} = NULL")
                elif field in ['llm_log', 'set_1_llm_log', 'set_2_llm_log', 'set_3_llm_log']:
                    # Log fields should be empty JSON array
                    clear_assignments.append(f"{field} = '[]'")
                else:
                    # All other fields to NULL
                    clear_assignments.append(f"{field} = NULL")
            else:
                print(f"⚠ Field '{field}' not found in database (may be older schema)")
        
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
            OR is_offtopic IS NOT NULL
        """)
        remaining_classified = cursor.fetchone()[0]
        
        if remaining_classified > 0:
            print(f"⚠ Warning: {remaining_classified} papers still have classification data")
        else:
            print("✓ All classifications cleared successfully")
        
        # Show preserved data stats
        cursor.execute("SELECT COUNT(*) FROM papers WHERE user_trace IS NOT NULL AND user_trace != ''")
        papers_with_comments = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM papers WHERE pdf_filename IS NOT NULL")
        papers_with_pdf = cursor.fetchone()[0]
        
        print(f"✓ Preserved {papers_with_comments} papers with user comments")
        print(f"✓ Preserved {papers_with_pdf} papers with PDF files")
        
        # Vacuum database to reclaim space
        print("✓ Optimizing database...")
        cursor.execute("VACUUM")
        conn.commit()
        
        print("\n" + "="*60)
        print("DATABASE RESET COMPLETE")
        print("="*60)
        print(f"Total papers: {total_papers}")
        print(f"Papers with user comments: {papers_with_comments}")
        print(f"Papers with PDFs: {papers_with_pdf}")
        print(f"All LLM classifications: CLEARED")
        print(f"All verification data: CLEARED")
        print(f"All logs: CLEARED")
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
    print("ResearchParça Database Reset Tool (v1.2)")
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
    print("   • User-set research areas")
    print("   • PDF files and their states")
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