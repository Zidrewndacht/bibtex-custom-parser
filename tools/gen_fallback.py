#!/usr/bin/env python3
"""
generate_fallback_db.py
Generates a fallback.sqlite database with minimal valid schema and placeholder record.
This ensures ResearchParça can launch even without existing data.
"""

import sqlite3
import json
import os
from datetime import datetime

# Default JSON structures (matching globals.py)
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

def create_fallback_database(db_path):
    """Create SQLite database with the full schema and a placeholder record."""
    
    # Remove existing file if present
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create the papers table with full schema (matching import_bibtex.py)
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
        pdf_filename TEXT DEFAULT NULL,
        pdf_state TEXT DEFAULT 'none',
        deannualized_conference TEXT,
        llm_log TEXT,
        last_llm_features TEXT,
        last_llm_technique TEXT,
        last_llm_is_survey INTEGER,
        last_llm_is_offtopic INTEGER,
        last_llm_is_through_hole INTEGER,
        last_llm_is_smt INTEGER,
        last_llm_is_x_ray INTEGER,
        last_llm_relevance INTEGER,
        last_llm_verified INTEGER,
        last_llm_estimated_score INTEGER,
        user_override_count INTEGER
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
    
    placeholder_data = {
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
        'abstract': '',  # Empty, no abstract
        'keywords': None,
        'research_area': None,
        'is_offtopic': 0,  # NOT off-topic (so not filtered out by default)
        'relevance': 10,   # High relevance (on-topic)
        'is_survey': None,
        'is_through_hole': None,
        'is_smt': None,
        'is_x_ray': None,
        'features': json.dumps(placeholder_features),
        'technique': json.dumps(placeholder_technique),
        'changed': None,
        'changed_by': None,
        'verified': None,
        'estimated_score': None,
        'verified_by': None,
        'user_trace': None,
        'pdf_filename': None,
        'pdf_state': 'none',
        'deannualized_conference': None,
        'llm_log': '[]',
        'last_llm_features': json.dumps(placeholder_features),
        'last_llm_technique': json.dumps(placeholder_technique),
        'last_llm_is_survey': None,
        'last_llm_is_offtopic': 0,
        'last_llm_is_through_hole': None,
        'last_llm_is_smt': None,
        'last_llm_is_x_ray': None,
        'last_llm_relevance': 10,
        'last_llm_verified': None,
        'last_llm_estimated_score': None,
        'user_override_count': 0
    }
    
    # Insert the placeholder record
    cursor.execute('''
    INSERT INTO papers (
        id, type, title, authors, year, month, journal,
        volume, pages, page_count, doi, issn, abstract, keywords,
        research_area, is_offtopic, relevance, is_survey, is_through_hole,
        is_smt, is_x_ray, features, technique, changed, changed_by, verified, 
        estimated_score, verified_by, user_trace, pdf_filename, pdf_state,
        deannualized_conference, llm_log, last_llm_features, last_llm_technique,
        last_llm_is_survey, last_llm_is_offtopic, last_llm_is_through_hole,
        last_llm_is_smt, last_llm_is_x_ray, last_llm_relevance, last_llm_verified,
        last_llm_estimated_score, user_override_count
    ) VALUES (
        :id, :type, :title, :authors, :year, :month, :journal,
        :volume, :pages, :page_count, :doi, :issn, :abstract, :keywords,
        :research_area, :is_offtopic, :relevance, :is_survey, :is_through_hole,
        :is_smt, :is_x_ray, :features, :technique, :changed, :changed_by, :verified,
        :estimated_score, :verified_by, :user_trace, :pdf_filename, :pdf_state,
        :deannualized_conference, :llm_log, :last_llm_features, :last_llm_technique,
        :last_llm_is_survey, :last_llm_is_offtopic, :last_llm_is_through_hole,
        :last_llm_is_smt, :last_llm_is_x_ray, :last_llm_relevance, :last_llm_verified,
        :last_llm_estimated_score, :user_override_count
    )
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