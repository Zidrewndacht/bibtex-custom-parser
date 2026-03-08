# migrate_triple_classification.py
"""
Migration script for triple-classification system.
Adds set_1_*, set_2_*, set_3_* columns and main_certainty column.
"""
import sqlite3
import json
import os
import sys

# Import globals for database path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globals

def get_field_list():
    """Returns the list of classification fields to duplicate for each set."""
    return [
        ('last_llm_features', 'TEXT'),
        ('last_llm_technique', 'TEXT'),
        ('last_llm_is_offtopic', 'INTEGER'),
        ('last_llm_is_survey', 'INTEGER'),
        ('last_llm_is_through_hole', 'INTEGER'),
        ('last_llm_is_smt', 'INTEGER'),
        ('last_llm_is_x_ray', 'INTEGER'),
        ('last_llm_relevance', 'INTEGER'),
        ('last_llm_verified', 'INTEGER'),
        ('last_llm_estimated_score', 'INTEGER'),
        ('llm_log', 'TEXT'),
    ]

def add_columns_to_table(cursor, table_name, columns):
    """Add columns to a table if they don't exist."""
    # Get existing columns
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    added_count = 0
    for col_name, col_type in columns:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
            added_count += 1
            print(f"  Added column: {col_name}")
    
    return added_count

def migrate_database(db_path):
    """Main migration function."""
    print(f"Starting migration for database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Build column lists for each set
    all_columns = []
    for set_num in [1, 2, 3]:
        for field_name, field_type in get_field_list():
            # Special handling for llm_log (set-specific naming)
            if field_name == 'llm_log':
                col_name = f'set_{set_num}_llm_log'
            else:
                col_name = f'set_{set_num}_{field_name}'
            all_columns.append((col_name, field_type))
    
    # Add main_certainty column
    all_columns.append(('main_certainty', 'TEXT'))
    
    # Add columns to papers table
    print("\nAdding new columns to papers table...")
    added = add_columns_to_table(cursor, 'papers', all_columns)
    print(f"Total columns added: {added}")
    
    # Copy existing data to set_1 columns
    print("\nCopying existing data to set_1 columns...")
    
    # Get existing field mappings
    field_mappings = [
        ('last_llm_features', 'set_1_last_llm_features'),
        ('last_llm_technique', 'set_1_last_llm_technique'),
        ('last_llm_is_offtopic', 'set_1_last_llm_is_offtopic'),
        ('last_llm_is_survey', 'set_1_last_llm_is_survey'),
        ('last_llm_is_through_hole', 'set_1_last_llm_is_through_hole'),
        ('last_llm_is_smt', 'set_1_last_llm_is_smt'),
        ('last_llm_is_x_ray', 'set_1_last_llm_is_x_ray'),
        ('last_llm_relevance', 'set_1_last_llm_relevance'),
        ('last_llm_verified', 'set_1_last_llm_verified'),
        ('last_llm_estimated_score', 'set_1_last_llm_estimated_score'),
        ('llm_log', 'set_1_llm_log'),
    ]
    
    for old_col, new_col in field_mappings:
        cursor.execute(f"""
            UPDATE papers 
            SET {new_col} = {old_col} 
            WHERE {old_col} IS NOT NULL
        """)
        print(f"  Copied {old_col} -> {new_col}")
    
    # Initialize main_certainty for all papers
    print("\nInitializing main_certainty for all papers...")
    cursor.execute("""
        UPDATE papers 
        SET main_certainty = '{}' 
        WHERE main_certainty IS NULL
    """)
    
    # Commit all changes
    conn.commit()
    
    # Verify migration
    print("\nVerifying migration...")
    cursor.execute("PRAGMA table_info(papers)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    print(f"\nTotal columns in papers table: {len(columns)}")
    
    # Count set_1, set_2, set_3 columns
    set_1_cols = sum(1 for c in columns if c.startswith('set_1_'))
    set_2_cols = sum(1 for c in columns if c.startswith('set_2_'))
    set_3_cols = sum(1 for c in columns if c.startswith('set_3_'))
    
    print(f"  set_1_* columns: {set_1_cols}")
    print(f"  set_2_* columns: {set_2_cols}")
    print(f"  set_3_* columns: {set_3_cols}")
    print(f"  main_certainty column: {'✓' if 'main_certainty' in columns else '✗'}")
    
    conn.close()
    print("\n✓ Migration completed successfully!")

if __name__ == '__main__':
    db_path = globals.DATABASE_FILE
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    migrate_database(db_path)