# merge_triple_databases.py
"""
Merges three independently-classified databases into the new triple-classification format.
Each source database becomes set_1, set_2, set_3 in the target database.
User data (comments, traces, overrides) is taken from database 1.
"""
import sqlite3
import json
import os
import sys
from datetime import datetime

# Import globals for schema constants
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globals

def get_classification_fields():
    """Returns list of classification field names to migrate."""
    return [
        'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
        'relevance', 'verified', 'estimated_score', 'features', 'technique'
    ]

def copy_paper_data(source_conn, target_conn, paper_id, set_num):
    """
    Copy classification data from source database to target database for a specific set.
    
    Args:
        source_conn: Source database connection
        target_conn: Target database connection
        paper_id: Paper ID to copy
        set_num: 1, 2, or 3 (which set this source becomes)
    """
    prefix = f'set_{set_num}_last_llm_'
    
    # Fetch source paper data
    source_cursor = source_conn.cursor()
    source_cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    source_paper = source_cursor.fetchone()
    
    if not source_paper:
        print(f"  Warning: Paper {paper_id} not found in source database {set_num}")
        return False
    
    source_paper = dict(source_paper)
    
    # Prepare update statements for set-specific columns
    update_fields = []
    update_values = []
    
    # Boolean classification fields
    for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', 'relevance', 'verified', 'estimated_score']:
        source_value = source_paper.get(field)
        update_fields.append(f"{prefix}{field} = ?")
        update_values.append(source_value)
    
    # JSON fields (features, technique)
    for field in ['features', 'technique']:
        source_value = source_paper.get(field)
        update_fields.append(f"{prefix}{field} = ?")
        update_values.append(source_value)
    
    # Copy llm_log to set-specific log
    source_llm_log = source_paper.get('llm_log', '[]')
    update_fields.append(f"set_{set_num}_llm_log = ?")
    update_values.append(source_llm_log)
    
    # Execute update
    if update_fields:
        update_values.append(paper_id)
        update_query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
        target_cursor = target_conn.cursor()
        target_cursor.execute(update_query, update_values)
        target_conn.commit()
    
    return True

def copy_user_data(source_conn, target_conn, paper_id):
    """
    Copy user-specific data from source database 1 to target database.
    This includes user_trace, user_override_count, changed_by, etc.
    
    Args:
        source_conn: Source database 1 connection
        target_conn: Target database connection
        paper_id: Paper ID to copy
    """
    source_cursor = source_conn.cursor()
    source_cursor.execute("""
        SELECT user_trace, user_override_count, changed, changed_by, 
               research_area, page_count, pdf_filename, pdf_state
        FROM papers WHERE id = ?
    """, (paper_id,))
    source_paper = source_cursor.fetchone()
    
    if not source_paper:
        return False
    
    # Copy user fields to target
    target_cursor = target_conn.cursor()
    update_fields = [
        "user_trace = ?", "user_override_count = ?", "changed = ?", "changed_by = ?",
        "research_area = ?", "page_count = ?", "pdf_filename = ?", "pdf_state = ?"
    ]
    update_values = list(source_paper)
    update_values.append(paper_id)
    
    update_query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
    target_cursor.execute(update_query, update_values)
    target_conn.commit()
    
    return True

def merge_llm_logs(source_conns, target_conn, paper_id):
    """
    Merge llm_logs from all 3 sources into the target main llm_log.
    Each source's log entries are tagged with their set number.
    
    Args:
        source_conns: List of 3 source database connections
        target_conn: Target database connection
        paper_id: Paper ID to merge logs for
    """
    target_cursor = target_conn.cursor()
    merged_log = []
    
    for set_num, source_conn in enumerate(source_conns, 1):
        source_cursor = source_conn.cursor()
        source_cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,))
        row = source_cursor.fetchone()
        
        if row and row[0]:
            try:
                source_log = json.loads(row[0])
                # Tag each entry with set_num
                for entry in source_log:
                    entry['set_num'] = set_num
                    merged_log.append(entry)
            except json.JSONDecodeError:
                print(f"  Warning: Invalid llm_log JSON for paper {paper_id} in source {set_num}")
    
    # Sort by timestamp (newest first for display, but store in chronological order)
    merged_log.sort(key=lambda x: x.get('timestamp', ''))
    
    # Update target llm_log
    target_cursor.execute(
        "UPDATE papers SET llm_log = ? WHERE id = ?",
        (json.dumps(merged_log), paper_id)
    )
    target_conn.commit()

def create_target_database(target_path, source_paths):
    """
    Create target database with new schema and merge data from 3 sources.
    
    Args:
        target_path: Path for the new merged database
        source_paths: List of 3 source database paths
    """
    print(f"Creating target database: {target_path}")
    print(f"Source databases: {source_paths}")
    
    # Open source databases
    source_conns = []
    for i, source_path in enumerate(source_paths, 1):
        if not os.path.exists(source_path):
            print(f"Error: Source database {i} not found: {source_path}")
            return False
        conn = sqlite3.connect(source_path)
        conn.row_factory = sqlite3.Row
        source_conns.append(conn)
        print(f"  ✓ Opened source database {i}: {source_path}")
    
    # Get paper IDs from source 1 (all should have same papers)
    source_cursor = source_conns[0].cursor()
    source_cursor.execute("SELECT id FROM papers ORDER BY id")
    paper_ids = [row[0] for row in source_cursor.fetchall()]
    total_papers = len(paper_ids)
    print(f"\nFound {total_papers} papers to migrate")
    
    # Create target database with new schema
    # First, create a fresh database using the migration script's schema
    print(f"\nCreating target database with new schema...")
    
    # Remove existing target if exists
    if os.path.exists(target_path):
        os.remove(target_path)
        print(f"  Removed existing target database: {target_path}")
    
    # Create new database with schema
    target_conn = sqlite3.connect(target_path)
    target_cursor = target_conn.cursor()
    
    # Create papers table with new schema (simplified version)
    target_cursor.execute('''
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY,
        type TEXT,
        title TEXT,
        authors TEXT,
        year INTEGER,
        month TEXT,
        journal TEXT,
        volume TEXT,
        pages TEXT,
        page_count INTEGER,
        doi TEXT,
        issn TEXT,
        abstract TEXT,
        keywords TEXT,
        research_area TEXT,
        is_offtopic INTEGER,
        relevance INTEGER,
        is_survey INTEGER,
        is_through_hole INTEGER,
        is_smt INTEGER,
        is_x_ray INTEGER,
        features TEXT,
        technique TEXT,
        changed TEXT,
        changed_by TEXT,
        verified INTEGER,
        estimated_score INTEGER,
        verified_by TEXT,
        user_trace TEXT,
        user_override_count INTEGER DEFAULT 0,
        pdf_filename TEXT,
        pdf_state TEXT DEFAULT 'none',
        deannualized_conference TEXT,
        
        -- Set 1 Classification Fields
        set_1_last_llm_features TEXT,
        set_1_last_llm_technique TEXT,
        set_1_last_llm_is_offtopic INTEGER,
        set_1_last_llm_is_survey INTEGER,
        set_1_last_llm_is_through_hole INTEGER,
        set_1_last_llm_is_smt INTEGER,
        set_1_last_llm_is_x_ray INTEGER,
        set_1_last_llm_relevance INTEGER,
        set_1_last_llm_verified INTEGER,
        set_1_last_llm_estimated_score INTEGER,
        set_1_llm_log TEXT,
        
        -- Set 2 Classification Fields
        set_2_last_llm_features TEXT,
        set_2_last_llm_technique TEXT,
        set_2_last_llm_is_offtopic INTEGER,
        set_2_last_llm_is_survey INTEGER,
        set_2_last_llm_is_through_hole INTEGER,
        set_2_last_llm_is_smt INTEGER,
        set_2_last_llm_is_x_ray INTEGER,
        set_2_last_llm_relevance INTEGER,
        set_2_last_llm_verified INTEGER,
        set_2_last_llm_estimated_score INTEGER,
        set_2_llm_log TEXT,
        
        -- Set 3 Classification Fields
        set_3_last_llm_features TEXT,
        set_3_last_llm_technique TEXT,
        set_3_last_llm_is_offtopic INTEGER,
        set_3_last_llm_is_survey INTEGER,
        set_3_last_llm_is_through_hole INTEGER,
        set_3_last_llm_is_smt INTEGER,
        set_3_last_llm_is_x_ray INTEGER,
        set_3_last_llm_relevance INTEGER,
        set_3_last_llm_verified INTEGER,
        set_3_last_llm_estimated_score INTEGER,
        set_3_llm_log TEXT,
        
        -- Main Set Certainty
        main_certainty TEXT,
        
        -- Metadata (copied from source 1)
        last_llm_features TEXT,
        last_llm_technique TEXT,
        last_llm_is_offtopic INTEGER,
        last_llm_is_survey INTEGER,
        last_llm_is_through_hole INTEGER,
        last_llm_is_smt INTEGER,
        last_llm_is_x_ray INTEGER,
        last_llm_relevance INTEGER,
        last_llm_verified INTEGER,
        last_llm_estimated_score INTEGER,
        llm_log TEXT
    )
    ''')
    
    # Copy base paper data from source 1 (title, authors, year, etc.)
    print(f"\nCopying base paper data from source 1...")
    for i, paper_id in enumerate(paper_ids):
        if i % 100 == 0:
            print(f"  Progress: {i}/{total_papers} papers...")
        
        source_cursor = source_conns[0].cursor()
        source_cursor.execute("""
            SELECT id, type, title, authors, year, month, journal, volume, pages, 
                   page_count, doi, issn, abstract, keywords, deannualized_conference
            FROM papers WHERE id = ?
        """, (paper_id,))
        base_paper = source_cursor.fetchone()
        
        if base_paper:
            target_cursor.execute("""
                INSERT INTO papers (
                    id, type, title, authors, year, month, journal, volume, pages,
                    page_count, doi, issn, abstract, keywords, deannualized_conference
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, base_paper)
    
    target_conn.commit()
    print(f"  ✓ Base paper data copied")
    
    # Copy classification data from all 3 sources
    print(f"\nCopying classification data from all 3 sources...")
    for i, paper_id in enumerate(paper_ids):
        if i % 100 == 0:
            print(f"  Progress: {i}/{total_papers} papers...")
        
        for set_num, source_conn in enumerate(source_conns, 1):
            copy_paper_data(source_conn, target_conn, paper_id, set_num)
    
    print(f"  ✓ Classification data copied")
    
    # Copy user data from source 1
    print(f"\nCopying user data from source 1...")
    for i, paper_id in enumerate(paper_ids):
        if i % 100 == 0:
            print(f"  Progress: {i}/{total_papers} papers...")
        copy_user_data(source_conns[0], target_conn, paper_id)
    
    print(f"  ✓ User data copied")
    
    # Merge llm_logs
    print(f"\nMerging llm_logs from all 3 sources...")
    for i, paper_id in enumerate(paper_ids):
        if i % 100 == 0:
            print(f"  Progress: {i}/{total_papers} papers...")
        merge_llm_logs(source_conns, target_conn, paper_id)
    
    print(f"  ✓ llm_logs merged")
    
    # Calculate main_certainty for all papers
    print(f"\nCalculating main_certainty for all papers...")
    for i, paper_id in enumerate(paper_ids):
        if i % 100 == 0:
            print(f"  Progress: {i}/{total_papers} papers...")
        try:
            globals.recalculate_main_set(paper_id, target_path)
        except Exception as e:
            print(f"  Warning: Failed to calculate certainty for paper {paper_id}: {e}")
    
    print(f"  ✓ main_certainty calculated")
    
    # Copy last_llm_* fields from set_1 for backward compatibility
    print(f"\nCopying set_1 data to last_llm_* fields for backward compatibility...")
    target_cursor.execute("""
        UPDATE papers SET
            last_llm_features = set_1_last_llm_features,
            last_llm_technique = set_1_last_llm_technique,
            last_llm_is_offtopic = set_1_last_llm_is_offtopic,
            last_llm_is_survey = set_1_last_llm_is_survey,
            last_llm_is_through_hole = set_1_last_llm_is_through_hole,
            last_llm_is_smt = set_1_last_llm_is_smt,
            last_llm_is_x_ray = set_1_last_llm_is_x_ray,
            last_llm_relevance = set_1_last_llm_relevance,
            last_llm_verified = set_1_last_llm_verified,
            last_llm_estimated_score = set_1_last_llm_estimated_score,
            llm_log = set_1_llm_log
    """)
    target_conn.commit()
    print(f"  ✓ Backward compatibility fields populated")
    
    # Close all connections
    for conn in source_conns:
        conn.close()
    target_conn.close()
    
    print(f"\n{'='*60}")
    print(f"✓ Migration completed successfully!")
    print(f"Target database: {target_path}")
    print(f"Total papers migrated: {total_papers}")
    print(f"{'='*60}")
    
    return True

if __name__ == '__main__':
    if len(sys.argv) < 5:
        print("Usage: python merge_triple_databases.py <target_db> <source1_db> <source2_db> <source3_db>")
        print("Example: python merge_triple_databases.py data/merged.sqlite data/db1.sqlite data/db2.sqlite data/db3.sqlite")
        sys.exit(1)
    
    target_path = sys.argv[1]
    source_paths = sys.argv[2:5]
    
    # Ensure target directory exists
    target_dir = os.path.dirname(target_path)
    if target_dir and not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"Created directory: {target_dir}")
    
    success = create_target_database(target_path, source_paths)
    
    if not success:
        sys.exit(1)