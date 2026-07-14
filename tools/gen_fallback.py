#for v1.2 only
"""
generate_fallback_db.py
Generates a fallback.sqlite database with minimal valid schema and placeholder record.
This ensures ResearchParça v1.2 can launch even without existing data.
"""

import sqlite3
import json
import os
from datetime import datetime

# Default JSON structures (matching globals.py v1.2)
DEFAULT_FEATURES = {
    "tracks": None,
    "holes": None,
    "bare_pcb_other": None,
    "solder_insufficient": None,
    "solder_excess": None,
    "solder_void": None,
    "solder_crack": None,
    "solder_other": None,
    "orientation": None,
    "wrong_component": None,
    "missing_component": None,
    "component_other": None,
    "cosmetic": None,
    "other": None
}

DEFAULT_TECHNIQUE = {
    "classic_cv_based": None,
    "ml_traditional": None,
    "dl_cnn_classifier": None,
    "dl_cnn_detector": None,
    "dl_rcnn_detector": None,
    "dl_transformer": None,
    "dl_other": None,
    "hybrid": None,
    "model": None,
    "available_dataset": None
}

DEFAULT_CERTAINTY_MAP = {
    "is_offtopic": "solid",
    "is_survey": "solid",
    "is_through_hole": "solid",
    "is_smt": "solid",
    "is_x_ray": "solid",
    "verified": "solid",
    "features_tracks": "solid",
    "features_holes": "solid",
    "features_bare_pcb_other": "solid",
    "features_solder_insufficient": "solid",
    "features_solder_excess": "solid",
    "features_solder_void": "solid",
    "features_solder_crack": "solid",
    "features_solder_other": "solid",
    "features_orientation": "solid",
    "features_wrong_component": "solid",
    "features_missing_component": "solid",
    "features_component_other": "solid",
    "features_cosmetic": "solid",
    "features_other_state": "solid",
    "technique_classic_cv_based": "solid",
    "technique_ml_traditional": "solid",
    "technique_dl_cnn_classifier": "solid",
    "technique_dl_cnn_detector": "solid",
    "technique_dl_rcnn_detector": "solid",
    "technique_dl_transformer": "solid",
    "technique_dl_other": "solid",
    "technique_hybrid": "solid",
    "technique_available_dataset": "solid"
}

def create_fallback_database(db_path):
    """Create SQLite database with the full v1.2 schema and a placeholder record."""
    
    # Remove existing file if present
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create the papers table with full v1.2 schema (triple-classification system)
    cursor.execute('''
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
        set_1_last_llm_verified_by TEXT,
        
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
        set_2_last_llm_verified_by TEXT,
        
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
        set_3_last_llm_verified_by TEXT,
        
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
    
    # Enable WAL mode for better concurrency
    cursor.execute('PRAGMA journal_mode = WAL')
    
    # Prepare the placeholder record
    # Key: is_offtopic=0 and relevance=10 so it's NOT filtered out by default
    # Key: cosmetic=1 so it shows up in feature filters
    placeholder_features = DEFAULT_FEATURES.copy()
    placeholder_features["cosmetic"] = True  # Mark as having cosmetic feature
    
    placeholder_technique = DEFAULT_TECHNIQUE.copy()
    
    # Prepare set-specific data (all 3 sets identical for placeholder)
    def prepare_set_data():
        return {
            'features': json.dumps(placeholder_features),
            'technique': json.dumps(placeholder_technique),
            'is_offtopic': 0,
            'is_survey': None,
            'is_through_hole': None,
            'is_smt': None,
            'is_x_ray': None,
            'relevance': 10,
            'verified': None,
            'estimated_score': None,
            'llm_log': '[]',
            'verified_by': None
        }
    
    set_data = prepare_set_data()
    
    placeholder_data = {
        # Basic fields
        'id': '1',
        'type': 'misc',
        'title': 'Database is missing or empty. Import BibTeX or restore from a backup to start working',
        'authors': None,
        'year': 2020,
        'month': None,
        'journal': None,
        'volume': None,
        'pages': None,
        'page_count': None,
        'doi': None,
        'issn': None,
        'abstract': '',
        'keywords': None,
        'research_area': None,
        
        # Main classification fields (mirrors set_1)
        'is_offtopic': 0,
        'relevance': 10,
        'is_survey': None,
        'is_through_hole': None,
        'is_smt': None,
        'is_x_ray': None,
        'features': json.dumps(placeholder_features),
        'technique': json.dumps(placeholder_technique),
        
        # Audit fields
        'changed': None,
        'changed_by': None,
        'verified': None,
        'estimated_score': None,
        'verified_by': None,
        'user_trace': None,
        'user_override_count': 0,
        
        # PDF fields
        'pdf_filename': None,
        'pdf_state': 'none',
        'deannualized_conference': None,
        
        # Set 1 fields
        'set_1_last_llm_features': set_data['features'],
        'set_1_last_llm_technique': set_data['technique'],
        'set_1_last_llm_is_offtopic': set_data['is_offtopic'],
        'set_1_last_llm_is_survey': set_data['is_survey'],
        'set_1_last_llm_is_through_hole': set_data['is_through_hole'],
        'set_1_last_llm_is_smt': set_data['is_smt'],
        'set_1_last_llm_is_x_ray': set_data['is_x_ray'],
        'set_1_last_llm_relevance': set_data['relevance'],
        'set_1_last_llm_verified': set_data['verified'],
        'set_1_last_llm_estimated_score': set_data['estimated_score'],
        'set_1_llm_log': set_data['llm_log'],
        'set_1_last_llm_verified_by': set_data['verified_by'],
        
        # Set 2 fields
        'set_2_last_llm_features': set_data['features'],
        'set_2_last_llm_technique': set_data['technique'],
        'set_2_last_llm_is_offtopic': set_data['is_offtopic'],
        'set_2_last_llm_is_survey': set_data['is_survey'],
        'set_2_last_llm_is_through_hole': set_data['is_through_hole'],
        'set_2_last_llm_is_smt': set_data['is_smt'],
        'set_2_last_llm_is_x_ray': set_data['is_x_ray'],
        'set_2_last_llm_relevance': set_data['relevance'],
        'set_2_last_llm_verified': set_data['verified'],
        'set_2_last_llm_estimated_score': set_data['estimated_score'],
        'set_2_llm_log': set_data['llm_log'],
        'set_2_last_llm_verified_by': set_data['verified_by'],
        
        # Set 3 fields
        'set_3_last_llm_features': set_data['features'],
        'set_3_last_llm_technique': set_data['technique'],
        'set_3_last_llm_is_offtopic': set_data['is_offtopic'],
        'set_3_last_llm_is_survey': set_data['is_survey'],
        'set_3_last_llm_is_through_hole': set_data['is_through_hole'],
        'set_3_last_llm_is_smt': set_data['is_smt'],
        'set_3_last_llm_is_x_ray': set_data['is_x_ray'],
        'set_3_last_llm_relevance': set_data['relevance'],
        'set_3_last_llm_verified': set_data['verified'],
        'set_3_last_llm_estimated_score': set_data['estimated_score'],
        'set_3_llm_log': set_data['llm_log'],
        'set_3_last_llm_verified_by': set_data['verified_by'],
        
        # Main certainty
        'main_certainty': json.dumps(DEFAULT_CERTAINTY_MAP),
        
        # Metadata (copied from set_1)
        'last_llm_features': set_data['features'],
        'last_llm_technique': set_data['technique'],
        'last_llm_is_offtopic': set_data['is_offtopic'],
        'last_llm_is_survey': set_data['is_survey'],
        'last_llm_is_through_hole': set_data['is_through_hole'],
        'last_llm_is_smt': set_data['is_smt'],
        'last_llm_is_x_ray': set_data['is_x_ray'],
        'last_llm_relevance': set_data['relevance'],
        'last_llm_verified': set_data['verified'],
        'last_llm_estimated_score': set_data['estimated_score'],
        'llm_log': '[]'
    }
    
    # Build the INSERT query dynamically to match all fields
    fields = list(placeholder_data.keys())
    placeholders = ', '.join([f':{f}' for f in fields])
    field_names = ', '.join(fields)
    
    cursor.execute(f'''
    INSERT INTO papers ({field_names}) VALUES ({placeholders})
    ''', placeholder_data)
    
    conn.commit()
    
    # Verify the record was inserted
    cursor.execute("SELECT COUNT(*) FROM papers")
    count = cursor.fetchone()[0]
    print(f"Database created with {count} record(s)")
    
    cursor.execute("SELECT id, title, is_offtopic, relevance FROM papers WHERE id = '1'")
    record = cursor.fetchone()
    if record:
        print(f"Placeholder record: ID={record[0]}, Title='{record[1][:50]}...', is_offtopic={record[2]}, relevance={record[3]}")
    
    conn.close()
    
    # Remove WAL and SHM files (for a clean single-file fallback)
    wal_path = db_path + '-wal'
    shm_path = db_path + '-shm'
    if os.path.exists(wal_path):
        os.remove(wal_path)
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    print(f"Fallback database created successfully: {db_path}")
    print(f"File size: {os.path.getsize(db_path)} bytes")

if __name__ == "__main__":
    # Default output path (same directory as script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_path = os.path.join(script_dir, 'fallback.sqlite')
    
    print(f"Generating fallback database at: {fallback_path}")
    create_fallback_database(fallback_path)
    print("\nDone! Place this file in the same directory as browse_db.py")