"""
Standalone migration script to convert a ResearchParça v1.2 (PCB AOI) SQLite database
to the v1.4 domain-agnostic schema.

Fixes:
- Correctly migrates `main_certainty` keys from v1.2 flat format (e.g., `features_tracks`) 
  to v1.4 dot-notation paths (e.g., `features.tracks`).
- Recursively patches `certainty_map` keys inside all `llm_log` and `set_N_llm_log` entries 
  (both at the top level and nested inside the `output` JSON string) so that history rows 
  correctly render conflict warnings and translucent states for old data.

Usage:
    python migrate_v1.2_to_v1.4.py <source_v1.2.db> <dest_v1.4.db>
"""

import json
import os
import sqlite3
import sys


def parse_json(val):
    """Safely parse a JSON string into a dict, returning {} on failure."""
    if not val:
        return {}
    try:
        return json.loads(val)
    except Exception:
        return {}

def migrate_certainty_keys(old_map):
    """
    Migrates v1.2 certainty map keys (e.g. 'features_tracks', 'technique_model')
    to v1.4 dot-notation paths (e.g. 'features.tracks', 'technique.model').
    """
    if not old_map or not isinstance(old_map, dict):
        return {}
    new_map = {}
    for k, v in old_map.items():
        if k.startswith('features_'):
            new_key = 'features.' + k[len('features_'):]
        elif k.startswith('technique_'):
            new_key = 'technique.' + k[len('technique_'):]
        else:
            new_key = k
        new_map[new_key] = v
    return new_map

def migrate_log_entries(log_str):
    """
    Parses a log array JSON string, migrates the certainty_map keys
    in both the top-level entry and the nested 'output' JSON, and returns
    the re-serialized JSON string.
    """
    if not log_str:
        return '[]'
    try:
        entries = json.loads(log_str)
        if not isinstance(entries, list):
            return '[]'
    except Exception:
        return '[]'
        
    for entry in entries:
        # 1. Migrate top-level certainty_map
        if 'certainty_map' in entry and isinstance(entry['certainty_map'], dict):
            entry['certainty_map'] = migrate_certainty_keys(entry['certainty_map'])
            
        # 2. Migrate certainty_map inside 'output' if it exists
        if 'output' in entry:
            output_raw = entry['output']
            output_dict = None
            is_string = False
            
            if isinstance(output_raw, str):
                is_string = True
                try:
                    output_dict = json.loads(output_raw)
                except Exception:
                    pass
            elif isinstance(output_raw, dict):
                output_dict = output_raw
                
            if isinstance(output_dict, dict):
                if 'certainty_map' in output_dict and isinstance(output_dict['certainty_map'], dict):
                    output_dict['certainty_map'] = migrate_certainty_keys(output_dict['certainty_map'])
                    
                if is_string:
                    entry['output'] = json.dumps(output_dict)
                else:
                    entry['output'] = output_dict
                    
    return json.dumps(entries)

def build_classification_blob(row, prefix=""):
    """
    Builds the unified classification JSON blob from scattered v1.2 columns.
    prefix can be "", "last_llm_", "set_1_last_llm_", etc.
    """
    blob = {}
    
    # Universal inferred fields
    blob['is_offtopic'] = row.get(f'{prefix}is_offtopic')
    blob['relevance'] = row.get(f'{prefix}relevance')
    blob['is_survey'] = row.get(f'{prefix}is_survey')
    blob['is_through_hole'] = row.get(f'{prefix}is_through_hole')
    blob['is_smt'] = row.get(f'{prefix}is_smt')
    blob['is_x_ray'] = row.get(f'{prefix}is_x_ray')
    
    if prefix == "":
        # Main state includes explicit audit fields and research_area
        blob['features'] = parse_json(row.get('features'))
        blob['technique'] = parse_json(row.get('technique'))
        blob['research_area'] = row.get('research_area')
        blob['verified'] = row.get('verified')
        blob['verified_by'] = row.get('verified_by')
        blob['estimated_score'] = row.get('estimated_score')
    else:
        # LLM states (last_llm or set_N) don't track research_area
        blob['features'] = parse_json(row.get(f'{prefix}features'))
        blob['technique'] = parse_json(row.get(f'{prefix}technique'))
        blob['verified'] = row.get(f'{prefix}verified')
        blob['estimated_score'] = row.get(f'{prefix}estimated_score')
        blob['verified_by'] = row.get(f'{prefix}verified_by')
        
    return blob

def migrate_db(src_path, dst_path):
    if not os.path.exists(src_path):
        print(f"❌ Source DB '{src_path}' not found.")
        sys.exit(1)
        
    if os.path.exists(dst_path):
        print(f"❌ Destination DB '{dst_path}' already exists. Please remove it or choose a different path.")
        sys.exit(1)
        
    print(f"🚀 Migrating '{src_path}' -> '{dst_path}'")
    
    src_conn = sqlite3.connect(src_path)
    src_conn.row_factory = sqlite3.Row
    src_cur = src_conn.cursor()
    
    dst_conn = sqlite3.connect(dst_path)
    dst_cur = dst_conn.cursor()
    
    # Create v1.4 schema
    dst_cur.execute("""
    CREATE TABLE papers (
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
        deannualized_conference TEXT,
        user_trace TEXT,
        changed TEXT,
        changed_by TEXT,
        verified INTEGER,
        verified_by TEXT,
        estimated_score INTEGER,
        user_override_count INTEGER DEFAULT 0,
        pdf_filename TEXT,
        pdf_state TEXT DEFAULT 'none',
        main_certainty TEXT DEFAULT '{}',
        classification TEXT DEFAULT '{}',
        last_llm_classification TEXT DEFAULT '{}',
        set_1_llm TEXT,
        set_2_llm TEXT,
        set_3_llm TEXT,
        set_1_llm_log TEXT DEFAULT '[]',
        set_2_llm_log TEXT DEFAULT '[]',
        set_3_llm_log TEXT DEFAULT '[]',
        llm_log TEXT DEFAULT '[]'
    )
    """)
    dst_conn.commit()
    
    src_cur.execute("SELECT * FROM papers")
    rows = src_cur.fetchall()
    
    total = len(rows)
    print(f"📚 Found {total} papers to migrate.")
    
    for i, row in enumerate(rows):
        row_dict = dict(row)
        
        # Build unified JSON blobs
        classification = build_classification_blob(row_dict, "")
        last_llm_classification = build_classification_blob(row_dict, "last_llm_")
        
        set_1_llm = build_classification_blob(row_dict, "set_1_last_llm_")
        set_2_llm = build_classification_blob(row_dict, "set_2_last_llm_")
        set_3_llm = build_classification_blob(row_dict, "set_3_last_llm_")
        
        # Migrate logs (handles certainty_map key translation dynamically)
        llm_log = migrate_log_entries(row_dict.get('llm_log'))
        set_1_llm_log = migrate_log_entries(row_dict.get('set_1_llm_log'))
        set_2_llm_log = migrate_log_entries(row_dict.get('set_2_llm_log'))
        set_3_llm_log = migrate_log_entries(row_dict.get('set_3_llm_log'))
        
        # Migrate main_certainty map
        main_certainty_str = row_dict.get('main_certainty')
        try:
            mc_dict = json.loads(main_certainty_str) if main_certainty_str else {}
            mc_dict = migrate_certainty_keys(mc_dict)
            main_certainty = json.dumps(mc_dict)
        except Exception:
            main_certainty = '{}'
        
        # Insert into new DB
        dst_cur.execute("""
            INSERT INTO papers (
                id, type, title, authors, year, month, journal, volume, pages, page_count,
                doi, issn, abstract, keywords, deannualized_conference,
                user_trace, changed, changed_by, verified, verified_by, estimated_score,
                user_override_count, pdf_filename, pdf_state,
                main_certainty, classification, last_llm_classification,
                set_1_llm, set_2_llm, set_3_llm,
                set_1_llm_log, set_2_llm_log, set_3_llm_log, llm_log
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
        """, (
            row_dict.get('id'), row_dict.get('type'), row_dict.get('title'), row_dict.get('authors'),
            row_dict.get('year'), row_dict.get('month'), row_dict.get('journal'), row_dict.get('volume'),
            row_dict.get('pages'), row_dict.get('page_count'),
            row_dict.get('doi'), row_dict.get('issn'), row_dict.get('abstract'), row_dict.get('keywords'),
            row_dict.get('deannualized_conference'),
            row_dict.get('user_trace'), row_dict.get('changed'), row_dict.get('changed_by'),
            row_dict.get('verified'), row_dict.get('verified_by'), row_dict.get('estimated_score'),
            row_dict.get('user_override_count'), row_dict.get('pdf_filename'), row_dict.get('pdf_state'),
            main_certainty,
            json.dumps(classification),
            json.dumps(last_llm_classification),
            json.dumps(set_1_llm),
            json.dumps(set_2_llm),
            json.dumps(set_3_llm),
            set_1_llm_log, set_2_llm_log, set_3_llm_log, llm_log
        ))
        
        if (i + 1) % 100 == 0 or (i + 1) == total:
            print(f"✅ Migrated {i + 1}/{total} papers...")
            
    dst_conn.commit()
    
    # Migrate auxiliary tables if they exist
    src_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'papers'")
    other_tables = src_cur.fetchall()
    for (table_name,) in other_tables:
        print(f"📋 Copying auxiliary table: {table_name}")
        src_cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        create_sql = src_cur.fetchone()[0]
        dst_cur.execute(create_sql)
        
        src_cur.execute(f"SELECT * FROM {table_name}")
        t_rows = src_cur.fetchall()
        if t_rows:
            cols = [desc[0] for desc in src_cur.description]
            placeholders = ','.join(['?'] * len(cols))
            col_names = ','.join(cols)
            for t_row in t_rows:
                dst_cur.execute(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})", tuple(t_row))
                
    dst_conn.commit()
    src_conn.close()
    dst_conn.close()
    print("🎉 Migration complete!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python migrate_v1.2_to_v1.4.py <source_v1.2.db> <dest_v1.4.db>")
        sys.exit(1)
    migrate_db(sys.argv[1], sys.argv[2])