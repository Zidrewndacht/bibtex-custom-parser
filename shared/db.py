# shared/db.py
import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from . import config  # Replaces 'import globals'

_db_path = None

def _get_val_by_path(d, path):
    """Safely get a value from a nested dict using dot-notation."""
    if not d or not path: return None
    keys = path.split('.')
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d

def _set_val_by_path(d, path, val):
    """Safely set a value in a nested dict using dot-notation."""
    keys = path.split('.')
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val

def _get_all_paths(d, prefix=''):
    """Recursively discover all leaf-node paths in a nested dict."""
    paths = []
    if not isinstance(d, dict): return paths
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            paths.extend(_get_all_paths(v, path))
        else:
            paths.append(path)
    return paths

def _generate_schema_and_placeholder(db_path):
    """Creates the fixed, domain-agnostic database schema and inserts the placeholder paper."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
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
        
        -- Universal Purpose / Audit
        user_trace TEXT,
        changed TEXT,
        changed_by TEXT,
        verified INTEGER,
        verified_by TEXT,
        estimated_score INTEGER,
        user_override_count INTEGER DEFAULT 0,
        
        -- File management
        pdf_filename TEXT,
        pdf_state TEXT DEFAULT 'none',
        
        -- LLM Blobs (100% of inferred data)
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
    
    cursor.execute("""
    INSERT INTO papers (id, type, title, year, pdf_state, user_override_count,
                        main_certainty, classification, last_llm_classification,
                        set_1_llm_log, set_2_llm_log, set_3_llm_log, llm_log)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        '1', 
        'misc', 
        'Database is missing or empty. Import BibTeX or restore from a backup to start working', 
        2020,
        'none',
        0,
        '{}',
        '{}',
        '{}',
        '[]',
        '[]',
        '[]',
        '[]'
    ))
    
    conn.commit()
    conn.close()

def init_db(db_path):
    global _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(_db_path), exist_ok=True)
    
    if not os.path.exists(_db_path):
        print(f"[Init] Database not found at {_db_path}. Creating domain-agnostic schema...")
        _generate_schema_and_placeholder(_db_path)
        print(f"[Init] Database ready: {_db_path}")

@contextmanager
def get_db():
    """Strictly ephemeral SQLite connection context manager."""
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def format_changed_timestamp(changed_str):
    if not changed_str: return ""
    try:
        dt = datetime.fromisoformat(changed_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%y %H:%M:%S")
    except ValueError:
        return changed_str

def get_paper_by_id(paper_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None

def fetch_papers(hide_offtopic=True, year_from=None, year_to=None, min_page_count=None):
    with get_db() as conn:
        base_query = "SELECT p.* FROM papers p"
        conditions = []
        params = []
        
        if hide_offtopic:
            conditions.append("(json_extract(p.classification, '$.is_offtopic') = 0 OR json_extract(p.classification, '$.is_offtopic') IS NULL)")
        if year_from is not None:
            try: conditions.append("p.year >= ?"); params.append(int(year_from))
            except: pass
        if year_to is not None:
            try: conditions.append("p.year <= ?"); params.append(int(year_to))
            except: pass
        if min_page_count is not None:
            try: conditions.append("(p.page_count IS NULL OR p.page_count = '' OR p.page_count >= ?)"); params.append(int(min_page_count))
            except: pass
            
        query_parts = [base_query]
        if conditions: query_parts.append("WHERE " + " AND ".join(conditions))
        query_parts.append("ORDER BY (p.user_trace IS NULL OR p.user_trace = '') ASC")
        
        papers = conn.execute(" ".join(query_parts), params).fetchall()
        paper_list = []
        for paper in papers:
            p_dict = dict(paper)
            try: p_dict['classification'] = json.loads(p_dict['classification']) if p_dict['classification'] else {}
            except: p_dict['classification'] = {}
            try: p_dict['main_certainty'] = json.loads(p_dict['main_certainty']) if p_dict['main_certainty'] else {}
            except: p_dict['main_certainty'] = {}
            p_dict['changed_formatted'] = format_changed_timestamp(p_dict.get('changed'))
            paper_list.append(p_dict)
        return paper_list

def calculate_field_certainty(values):
    if not values or len(values) != 3:
        return None, 'solid'
        
    yes_count = sum(1 for v in values if v == 1)
    no_count = sum(1 for v in values if v == 0)
    null_count = sum(1 for v in values if v is None or v == '')
    
    if yes_count > no_count:
        main_value = 1
        has_disagreement = (no_count > 0)
    elif no_count > yes_count:
        main_value = 0
        has_disagreement = (yes_count > 0)
    else:
        main_value = None
        has_disagreement = True
        
    if has_disagreement and yes_count > 0 and no_count > 0:
        certainty = 'conflict'
    elif null_count == 2:
        certainty = '60'
    elif null_count == 1:
        certainty = '80'
    else:
        certainty = 'solid'
        
    return main_value, certainty

def update_paper_custom_fields(paper_id, data, changed_by="user"):
    with get_db() as conn:
        cursor = conn.cursor()
        paper = dict(cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone())
        if not paper: return {'status': 'error', 'message': 'Paper not found'}

        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        try: current_class = json.loads(paper['classification'] or '{}')
        except: current_class = {}
        try: last_llm_class = json.loads(paper['last_llm_classification'] or '{}')
        except: last_llm_class = {}
        try: certainty_map = json.loads(paper['main_certainty'] or '{}')
        except: certainty_map = {}
        
        update_fields = []
        update_values = []
        
        # 1. Handle Baseline SQL Columns
        if 'page_count' in data:
            update_fields.append("page_count = ?")
            update_values.append(int(data['page_count']) if str(data['page_count']).isdigit() else None)
        if 'user_trace' in data:
            update_fields.append("user_trace = ?")
            update_values.append(data['user_trace'])
            
        # 2. Handle Classification Blob (Dot-notation keys)
        for key, value in data.items():
            if key in ['id', 'page_count', 'user_trace']: continue
            
            # Parse boolean strings
            if isinstance(value, str):
                if value.lower() == 'true': parsed_val = True
                elif value.lower() == 'false': parsed_val = False
                elif value == '': parsed_val = None
                else: parsed_val = value
            else:
                parsed_val = value
                
            _set_val_by_path(current_class, key, parsed_val)
            certainty_map[key] = 'solid' # User edits are always 'solid' certainty

        # 3. Calculate User Override Count
        def normalize_bool(val):
            if val is None or val == '' or val == 'null': return None
            if val is True or val == 1: return 1
            if val is False or val == 0: return 0
            return val

        override_count = 0
        all_paths = set(_get_all_paths(current_class)) | set(_get_all_paths(last_llm_class))
        for path in all_paths:
            if normalize_bool(_get_val_by_path(current_class, path)) != normalize_bool(_get_val_by_path(last_llm_class, path)):
                override_count += 1

        # 4. Save
        update_fields.extend(["classification = ?", "main_certainty = ?", "user_override_count = ?", "changed = ?", "changed_by = ?"])
        update_values.extend([json.dumps(current_class), json.dumps(certainty_map), override_count, changed_timestamp, changed_by])
        
        cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values + [paper_id])
        conn.commit()
        
        # Return updated data for the frontend
        return fetch_updated_paper_data(paper_id)
    
def update_set_cache(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid, log_type="classifier", reset_verification=False):
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # 1. Save the raw LLM output directly to the set blob
        update_fields = [f"set_{set_num}_llm = ?"]
        update_values = [json.dumps(llm_data)]
        
        # 2. Handle Log
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        existing_log.append({"timestamp": timestamp, "type": log_type, "model": model_name, "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid})
        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values + [paper_id])

def fetch_updated_paper_data(paper_id):
    """Returns the parsed JSON blobs and baseline columns for frontend cell updates."""
    with get_db() as conn:
        updated_paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if updated_paper:
            p = dict(updated_paper)
            try: p['classification'] = json.loads(p['classification']) if p['classification'] else {}
            except: p['classification'] = {}
            try: p['main_certainty'] = json.loads(p['main_certainty']) if p['main_certainty'] else {}
            except: p['main_certainty'] = {}
            
            return {
                'status': 'success',
                'changed': p.get('changed'),
                'changed_formatted': format_changed_timestamp(p.get('changed')),
                'changed_by': p.get('changed_by'),
                'verified_by': p.get('verified_by'),
                'page_count': p.get('page_count'),
                'verified': p.get('verified'),
                'estimated_score': p.get('estimated_score'),
                'user_trace': p.get('user_trace'),
                'user_override_count': p.get('user_override_count'),
                'classification': p['classification'],
                'main_certainty': p['main_certainty'],
                'pdf_state': p.get('pdf_state'),
                'pdf_filename': p.get('pdf_filename')
            }
        return {'status': 'error', 'message': 'Paper not found after update.'}

def update_set_verifier(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid):
    """Writes verifier output (verified, estimated_score) into the set_N_llm JSON blob."""
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # 1. Update the set_N_llm blob
        row = cursor.execute(f"SELECT set_{set_num}_llm FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_blob = json.loads(row[0]) if row and row[0] else {}
        except: existing_blob = {}
        
        if 'verified' in llm_data: existing_blob['verified'] = llm_data['verified']
        if 'estimated_score' in llm_data: existing_blob['estimated_score'] = int(llm_data['estimated_score'])
            
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm = ? WHERE id = ?", (json.dumps(existing_blob), paper_id))
        
        # 2. Update the set_N_llm_log
        row = cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        existing_log.append({
            "timestamp": timestamp, "type": "verifier", "model": model_name, 
            "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid
        })
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))

def update_set_log_only(paper_id, set_num, log_type, model_name, reasoning_trace, json_result, valid):
    """Appends an error/trace entry to the set_N_llm_log without modifying the classification blob."""
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        row = cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        existing_log.append({
            "timestamp": timestamp, "type": log_type, "model": model_name, 
            "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid
        })
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))

def recalculate_main_set(paper_id, changed_by="LLM_Averaged", create_log_entry=True):
    with get_db() as conn:
        cursor = conn.cursor()
        paper = dict(cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone())
        if not paper: return None

        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Load the 3 sets
        sets_data = []
        for sn in [1, 2, 3]:
            try: sets_data.append(json.loads(paper.get(f'set_{sn}_llm') or '{}'))
            except: sets_data.append({})

        # Discover all unique paths across all 3 sets
        all_paths = set()
        for s in sets_data:
            all_paths.update(_get_all_paths(s))

        main_classification = {}
        certainty_map = {}
        main_output_log = {} # For the llm_log

        for path in all_paths:
            values = [_get_val_by_path(s, path) for s in sets_data]
            
            # Handle Relevance / Estimated Score (Averages)
            if path == 'relevance' or path == 'estimated_score':
                valid_vals = [v for v in values if isinstance(v, (int, float))]
                avg = sum(valid_vals) / len(valid_vals) if valid_vals else None
                _set_val_by_path(main_classification, path, avg)
                main_output_log[path] = avg
                continue

            # Handle Verified (Tri-state logic based on score >= 7)
            if path == 'verified':
                # Handled separately below
                continue

            # Tri-state averaging
            main_val, certainty = calculate_field_certainty([1 if v is True else (0 if v is False else None) for v in values])
            
            # Convert 1/0/None back to True/False/None for the JSON blob
            final_val = True if main_val == 1 else (False if main_val == 0 else None)
            _set_val_by_path(main_classification, path, final_val)
            certainty_map[path] = certainty
            main_output_log[path] = final_val

        # Handle Verification logic
        score_values = [_get_val_by_path(s, 'estimated_score') for s in sets_data]
        verified_from_score = [1 if (s is not None and s >= 7) else (0 if s is not None else None) for s in score_values]
        main_verified, verified_certainty = calculate_field_certainty(verified_from_score)
        final_verified = True if main_verified == 1 else (False if main_verified == 0 else None)
        
        main_classification['verified'] = final_verified
        certainty_map['verified'] = verified_certainty
        main_output_log['verified'] = final_verified
        
        score_valid = [v for v in score_values if v is not None]
        main_score = sum(score_valid) / len(score_valid) if score_valid else None
        main_classification['estimated_score'] = int(main_score) if main_score is not None else None
        main_output_log['estimated_score'] = main_classification['estimated_score']

        # Save to DB
        class_json = json.dumps(main_classification)
        cert_json = json.dumps(certainty_map)
        
        cursor.execute("""
            UPDATE papers SET 
                classification = ?, 
                last_llm_classification = ?, 
                main_certainty = ?,
                changed = ?, 
                changed_by = ?
            WHERE id = ?
        """, (class_json, class_json, cert_json, changed_timestamp, changed_by, paper_id))

        if create_log_entry:
            row = cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
            try: existing_log = json.loads(row[0]) if row and row[0] else []
            except: existing_log = []
            log_entry = {
                "timestamp": changed_timestamp, "type": "averaged_llm", "model": "averaged_3_sets",
                "trace": "Averaged from 3 classification sets",
                "output": json.dumps({**main_output_log, "certainty_map": certainty_map}),
                "valid": True, "certainty_map": certainty_map
            }
            existing_log.append(log_entry)
            cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
            
        return certainty_map