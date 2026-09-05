# shared/db.py
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from shared import config   

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
    
    # Added IF NOT EXISTS for safety against locked/partially valid files
    cursor.execute("""
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
    
    # Check if placeholder already exists to avoid IntegrityError on re-runs
    cursor.execute("SELECT id FROM papers WHERE id = '1'")
    if not cursor.fetchone():
        cursor.execute("""
        INSERT INTO papers (id, type, title, year, pdf_state, user_override_count,
        main_certainty, classification, last_llm_classification,
        set_1_llm_log, set_2_llm_log, set_3_llm_log, llm_log)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            '1',
            'misc',
            'Database is missing or empty. Import BibTeX or restore from a backup to start working',
            2025,
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


def _get_val_by_path(d, path):
    if not d or not path: return None
    keys = path.split('.')
    for k in keys:
        if isinstance(d, dict) and k in d: d = d[k]
        else: return None
    return d

def _set_val_by_path(d, path, val):
    keys = path.split('.')
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val

_BOOL_TRUE  = {1, "1", "true", "True", "TRUE", "yes", "Yes", "on", "On"}
_BOOL_FALSE = {0, "0", "false", "False", "FALSE", "no", "No", "off", "Off"}

def normalize_llm_blob(blob: dict, boolean_paths: list[str] | None,
                       numeric_paths: list[str] | tuple[str, ...] = ("relevance", "estimated_score")) -> dict:
    if not isinstance(blob, dict):
        return blob
    
    if boolean_paths:
        for path in boolean_paths:
            val = _get_val_by_path(blob, path)
            if val is True or val is False or val is None: continue
            if val in _BOOL_TRUE: _set_val_by_path(blob, path, True)
            elif val in _BOOL_FALSE: _set_val_by_path(blob, path, False)

    for path in numeric_paths:
        val = _get_val_by_path(blob, path)
        if isinstance(val, (int, float)): continue
        if isinstance(val, str):
            try:
                num = float(val)
                _set_val_by_path(blob, path, int(num) if num == int(num) else num)
            except ValueError:
                pass
    return blob

def init_db(db_path):
    global _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(_db_path), exist_ok=True)
    needs_rebuild = False
    
    if os.path.exists(_db_path):
        try:
            # Verify the file is a valid SQLite DB and contains the required table
            test_conn = sqlite3.connect(_db_path)
            cursor = test_conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers';")
            if not cursor.fetchone():
                print("[Init] Database file exists but 'papers' table is missing (empty or incomplete DB).")
                needs_rebuild = True
            else:
                # --- BOOT-TIME CLEANUP: Remove placeholder if real papers exist ---
                placeholder_title = 'Database is missing or empty. Import BibTeX or restore from a backup to start working'
                cursor.execute("SELECT id FROM papers WHERE title = ?", (placeholder_title,))
                placeholder_row = cursor.fetchone()
                
                if placeholder_row:
                    # Count how many REAL papers exist (excluding the placeholder)
                    cursor.execute("SELECT COUNT(id) FROM papers WHERE title != ?", (placeholder_title,))
                    real_paper_count = cursor.fetchone()[0]
                    
                    if real_paper_count > 0:
                        cursor.execute("DELETE FROM papers WHERE id = ?", (placeholder_row[0],))
                        test_conn.commit()
                        print(f"[Init] Removed lingering placeholder (id={placeholder_row[0]}) since {real_paper_count} real paper(s) exist.")
            test_conn.close()
        except sqlite3.Error as e:
            print(f"[Init] Database file is corrupted or invalid: {e}")
            needs_rebuild = True

    if needs_rebuild:
        print("[Init] Rebuilding database schema and placeholder...")
        # Delete the corrupted/empty file so SQLite creates a completely fresh one
        try:
            os.remove(_db_path)
        except OSError as e:
            print(f"[Init] Warning: Could not delete invalid DB file ({e}). Will attempt to overwrite.")
            # Fallback to ensure schema is generated even if deletion fails
            _generate_schema_and_placeholder(_db_path)
        else:
            print(f"[Init] Database not found at {_db_path}. Creating domain-agnostic schema...")
            _generate_schema_and_placeholder(_db_path)
    elif not os.path.exists(_db_path):
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
            # Bulletproof JSON boolean check: 
            # Handles SQL NULL, JSON null, integer 0, string '0', and string 'false'
            conditions.append("(json_extract(p.classification, '$.is_offtopic') IS NULL OR json_extract(p.classification, '$.is_offtopic') IN (0, '0', 'false', 'False'))")
            
        if year_from is not None:
            try: conditions.append("p.year >= ?"); params.append(int(year_from))
            except: pass
        if year_to is not None:
            try: conditions.append("p.year <= ?"); params.append(int(year_to))
            except: pass
        if min_page_count is not None:
            # Added CAST to ensure string page counts from BibTeX don't break the >= comparison
            try: conditions.append("(p.page_count IS NULL OR p.page_count = '' OR CAST(p.page_count AS INTEGER) >= ?)"); params.append(int(min_page_count))
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
        if not paper: 
            return {'status': 'error', 'message': 'Paper not found'}

        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        try: current_class = json.loads(paper['classification'] or '{}')
        except: current_class = {}
        try: last_llm_class = json.loads(paper['last_llm_classification'] or '{}')
        except: last_llm_class = {}
        
        # FIX 1: Load existing certainty map to prevent wiping conflicts on comment-only saves
        try: 
            existing_certainty = json.loads(paper['main_certainty'] or '{}')
            certainty_map = dict(existing_certainty)
        except: 
            certainty_map = {}
            
        try: existing_log = json.loads(paper['llm_log'] or '[]')
        except: existing_log = []

        update_fields = []
        update_values = []

        user_set_verified = 'verified' in data
        user_set_verified_by = 'verified_by' in data
        original_verified_by = paper.get('verified_by')

        # Track current_user_trace properly so the log entry gets the NEW trace immediately
        current_user_trace = paper.get('user_trace') or ""

        # 1. Handle Baseline SQL Columns
        if 'page_count' in data:
            update_fields.append("page_count = ?")
            update_values.append(int(data['page_count']) if str(data['page_count']).isdigit() else None)
            data.pop('page_count')

        if 'user_trace' in data:
            current_user_trace = data['user_trace']
            update_fields.append("user_trace = ?")
            update_values.append(current_user_trace)
            
            # Automated paywall detection
            is_paywalled = 'paywalled' in str(current_user_trace).lower()
            has_pdf = bool(paper.get('pdf_filename'))
            
            if has_pdf:
                # PDF existence takes absolute priority. 
                # If it was somehow marked paywalled, fix it to PDF.
                if paper.get('pdf_state') == "paywalled":
                    update_fields.append("pdf_state = ?")
                    update_values.append("PDF")
            else:
                # No PDF exists: state depends entirely on the user's comment text
                if is_paywalled and paper.get('pdf_state') != "paywalled":
                    update_fields.append("pdf_state = ?")
                    update_values.append("paywalled")
                elif not is_paywalled and paper.get('pdf_state') == "paywalled":
                    update_fields.append("pdf_state = ?")
                    update_values.append("none")
            data.pop('user_trace')

        if 'verified' in data:
            val = data['verified']
            if isinstance(val, str):
                db_val = 1 if val.lower() in ('true', '1', 'on') else (0 if val.lower() in ('false', '0') else None)
            else:
                db_val = 1 if val is True else (0 if val is False else None)
            update_fields.append("verified = ?")
            update_values.append(db_val)
            current_class['verified'] = db_val
            data.pop('verified')

        if 'verified_by' in data:
            verified_by_value = data['verified_by']
            db_val = None if verified_by_value == 'unknown' or verified_by_value is None else verified_by_value
            update_fields.append("verified_by = ?")
            update_values.append(db_val)
            current_class['verified_by'] = db_val
            data.pop('verified_by')

        if 'estimated_score' in data:
            val = data['estimated_score']
            db_val = max(0, min(100, int(val))) if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()) else None
            update_fields.append("estimated_score = ?")
            update_values.append(db_val)
            current_class['estimated_score'] = db_val
            data.pop('estimated_score')

        # 2. Handle Classification Blob (Dot-notation keys)
        for key, value in data.items():
            if key in ['id']: continue
            if isinstance(value, str):
                if value.lower() in ('true', '1', 'on'): parsed_val = True
                elif value.lower() in ('false', '0', 'off'): parsed_val = False
                elif value.lower() in ('', 'null', 'unknown', 'none'): parsed_val = None
                else: parsed_val = value
            else:
                parsed_val = value
            
            _set_val_by_path(current_class, key, parsed_val)
            # FIX 2: Only update certainty for fields the user actually changed
            certainty_map[key] = 'solid'

        # 3. Calculate User Override Count (Moved UP & Exclude verification metadata)
        def normalize_bool(val):
            if val is None or val == '' or val == 'null' or val == 'unknown' or val == 'none': return None
            if val is True or val == 1 or val == '1' or val == 'true': return 1
            if val is False or val == 0 or val == '0' or val == 'false': return 0
            return val

        override_count = 0
        all_paths = set(_get_all_paths(current_class)) | set(_get_all_paths(last_llm_class))
        
        # Exclude verification metadata from override count; these are audit fields, not classification overrides
        exclude_paths = {'verified', 'estimated_score', 'verified_by'}
        for path in all_paths:
            if path in exclude_paths:
                continue
            if normalize_bool(_get_val_by_path(current_class, path)) != normalize_bool(_get_val_by_path(last_llm_class, path)):
                override_count += 1

        # 4. Verification Reset Logic (Moved DOWN & Condition Added)
        # Only reset verification if the user ACTUALLY changed an inferred classification field.
        if changed_by == "user" and not user_set_verified and not user_set_verified_by:
            if override_count > 0:
                was_llm_verified = (original_verified_by and
                                    str(original_verified_by).strip() != '' and
                                    original_verified_by != 'user')
                if was_llm_verified:
                    update_fields.extend(["verified = ?", "estimated_score = ?", "verified_by = ?"])
                    update_values.extend([None, None, ""])
                    current_class['verified'] = None
                    current_class['estimated_score'] = None
                    current_class['verified_by'] = ""

        # 5. History Log Building (Strictly follows original compaction logic)
        user_log_entry = {
            "timestamp": changed_timestamp,
            "type": "user",
            "model": "user",
            "trace": current_user_trace,
            "output": json.dumps(current_class),
            "valid": True,
            "certainty_map": certainty_map
        }

        # If the latest entry is from a user, compact the changes into it.
        # Otherwise (if it's AI or empty), append a new user entry.
        if existing_log and existing_log[-1].get('type') == 'user':
            last_user_entry = existing_log[-1]
            last_user_entry['output'] = json.dumps(current_class)
            last_user_entry['trace'] = current_user_trace
            last_user_entry['timestamp'] = changed_timestamp
            last_user_entry['certainty_map'] = certainty_map
        else:
            existing_log.append(user_log_entry)

        # 6. Save
        update_fields.extend([
            "classification = ?", "main_certainty = ?", "user_override_count = ?", 
            "changed = ?", "changed_by = ?", "llm_log = ?"
        ])
        update_values.extend([
            json.dumps(current_class), json.dumps(certainty_map), override_count, 
            changed_timestamp, changed_by, json.dumps(existing_log)
        ])

        cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values + [paper_id])
        conn.commit()
        
        return fetch_updated_paper_data(paper_id)
    
def recalculate_main_set(paper_id, changed_by="LLM_Averaged", create_log_entry=True):
    with get_db() as conn:
        cursor = conn.cursor()
        paper = dict(cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone())
        if not paper: return None
        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        sets_data = []
        for sn in [1, 2, 3]:
            try: sets_data.append(json.loads(paper.get(f'set_{sn}_llm') or '{}'))
            except: sets_data.append({})
            
        all_paths = set()
        for s in sets_data:
            all_paths.update(_get_all_paths(s))
            
        main_classification = {}
        certainty_map = {}
        main_output_log = {} 
        

        for path in all_paths:
            values = [_get_val_by_path(s, path) for s in sets_data]
            
            if path == 'relevance' or path == 'estimated_score':
                valid_vals = [v for v in values if isinstance(v, (int, float))]
                avg = sum(valid_vals) / len(valid_vals) if valid_vals else None
                _set_val_by_path(main_classification, path, avg)
                main_output_log[path] = avg
                continue

            # --- Handle Text Fields (Strings) ---
            # FIX: Exclude stringified booleans and numbers from being treated as text fields.
            # Otherwise, LLMs returning "false" or "0" silently bypass boolean voting and get 'solid' certainty.
            def _is_real_text(v):
                if not isinstance(v, str): return False
                s = v.strip().lower()
                if s in ('true', 'false', 'yes', 'no', '1', '0', 'null', 'none', ''):
                    return False
                try:
                    float(s)
                    return False
                except ValueError:
                    return True

            is_text = any(_is_real_text(v) for v in values)
            if is_text:
                seen_lower = set()
                unique_vals = []
                # Iterating in order (Set 1 -> Set 3) ensures Set 1's capitalization is kept
                for v in values:
                    if isinstance(v, str):
                        import re
                        # Strip whitespace and trailing commas/periods to prevent false mismatches
                        cleaned = v.strip().rstrip(',.')
                        # Normalize comma spacing and general whitespace so "CNN,RNN" matches "CNN, RNN"
                        cleaned = re.sub(r'\s*,\s*', ', ', cleaned)
                        cleaned = re.sub(r'\s+', ' ', cleaned)
                        if not cleaned:
                            continue
                        lower_v = cleaned.lower()
                        if lower_v not in seen_lower:
                            seen_lower.add(lower_v)
                            unique_vals.append(cleaned)
                
                final_val = "; ".join(unique_vals) if unique_vals else None
                _set_val_by_path(main_classification, path, final_val)
                certainty_map[path] = 'solid' # Text fields don't conflict, they combine
                main_output_log[path] = final_val
                continue
            # -----------------------------------------
                
            main_val, certainty = calculate_field_certainty([1 if v is True else (0 if v is False else None) for v in values])
            final_val = True if main_val == 1 else (False if main_val == 0 else None)
            _set_val_by_path(main_classification, path, final_val)
            certainty_map[path] = certainty
            main_output_log[path] = final_val

        score_values = [_get_val_by_path(s, 'estimated_score') for s in sets_data]
        verified_from_score = [1 if (s is not None and s >= 7) else (0 if s is not None else None) for s in score_values]
        main_verified, verified_certainty = calculate_field_certainty(verified_from_score)
        final_verified = True if main_verified == 1 else (False if main_verified == 0 else None)
        
        main_classification['verified'] = final_verified
        certainty_map['verified'] = verified_certainty
        main_output_log['verified'] = final_verified
        
        score_valid = [v for v in score_values if v is not None]
        main_score = sum(score_valid) / len(score_valid) if score_valid else None
        final_score = int(round(main_score)) if main_score is not None else None
        main_classification['estimated_score'] = final_score
        main_output_log['estimated_score'] = final_score

        sql_verified = 1 if final_verified is True else (0 if final_verified is False else None)
        
        # Simple logic: if the AI made a verification decision, it was done by computer.
        main_verified_by = 'computer' if sql_verified is not None else None
        main_classification['verified_by'] = main_verified_by

        class_json = json.dumps(main_classification)
        cert_json = json.dumps(certainty_map)
        #Fix: add user_override_count = 0
        cursor.execute("""
            UPDATE papers SET
                classification = ?,
                last_llm_classification = ?,
                main_certainty = ?,
                changed = ?,
                changed_by = ?,
                verified = ?,
                estimated_score = ?,
                verified_by = ?,
                user_override_count = 0
            WHERE id = ?
        """, (class_json, class_json, cert_json, changed_timestamp, changed_by, sql_verified, final_score, main_verified_by, paper_id))
   
        if create_log_entry:
            row = cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
            try: existing_log = json.loads(row[0]) if row and row[0] else []
            except: existing_log = []
            
            log_entry = {
                "timestamp": changed_timestamp, "type": "averaged_llm", "model": "averaged_3_sets",
                "trace": "Averaged from 3 classification sets",
                # FIX: Save the NESTED main_classification instead of the FLAT main_output_log
                "output": json.dumps({**main_classification, "certainty_map": certainty_map}),
                "valid": True, "certainty_map": certainty_map
            }
            existing_log.append(log_entry)
            cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
            
        return certainty_map
    
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


def update_set_cache(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid, log_type="classifier", reset_verification=False, invalid_reason=None, boolean_fields=None):
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Normalize at write time. Default to the domain-declared boolean
        # fields so stringified booleans from the LLM ("false", "1", ...) are
        # stored as real JSON booleans; otherwise they'd vote as NULL in
        # recalculate_main_set / agreement_core despite being stamped valid.
        if boolean_fields is None:
            boolean_fields = config.get_boolean_classification_fields()
        llm_data = normalize_llm_blob(llm_data, boolean_fields)

        update_fields = [f"set_{set_num}_llm = ?"]
        update_values = [json.dumps(llm_data)]

        # 2. Handle Log
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        log_entry = {
            "timestamp": timestamp, 
            "type": log_type, 
            "model": model_name, 
            "trace": reasoning_trace or "", 
            "output": json_result or "{}", 
            "valid": valid
        }
        if invalid_reason:
            log_entry["invalid_reason"] = invalid_reason
            
        existing_log.append(log_entry)

        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values + [paper_id])


def update_set_verifier(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid, invalid_reason=None):
    """Writes verifier output (verified, estimated_score) into the set_N_llm JSON blob."""
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # 1. Update the set_N_llm blob
        row = cursor.execute(f"SELECT set_{set_num}_llm FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_blob = json.loads(row[0]) if row and row[0] else {}
        except: existing_blob = {}
        
        if 'verified' in llm_data:
            v = llm_data['verified']
            # Normalize stringified/integer booleans to real JSON booleans so
            # the consensus state machine and the /consensus SQL gate agree.
            if v is not True and v is not False:
                if v in _BOOL_TRUE:
                    v = True
                elif v in _BOOL_FALSE:
                    v = False
            existing_blob['verified'] = v
        if 'estimated_score' in llm_data:
            existing_blob['estimated_score'] = int(round(float(llm_data['estimated_score'])))
            
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm = ? WHERE id = ?", (json.dumps(existing_blob), paper_id))
        
        # 2. Update the set_N_llm_log
        row = cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        log_entry = {
            "timestamp": timestamp, 
            "type": "verifier", 
            "model": model_name,
            "trace": reasoning_trace or "", 
            "output": json_result or "{}", 
            "valid": valid
        }
        if invalid_reason:
            log_entry["invalid_reason"] = invalid_reason
            
        existing_log.append(log_entry)
        
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))


def update_set_log_only(paper_id, set_num, log_type, model_name, reasoning_trace, json_result, valid, invalid_reason=None):
    """Appends an error/trace entry to the set_N_llm_log without modifying the classification blob."""
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        row = cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except: existing_log = []
        
        log_entry = {
            "timestamp": timestamp, 
            "type": log_type, 
            "model": model_name,
            "trace": reasoning_trace or "", 
            "output": json_result or "{}", 
            "valid": valid
        }
        if invalid_reason:
            log_entry["invalid_reason"] = invalid_reason
            
        existing_log.append(log_entry)
        
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))

def append_trace_review_log(paper_id, model_name, reasoning_trace, report_content, valid=True, invalid_reason=None):
    """Appends a free-form agent trace review report to the MAIN llm_log.

    Deliberately does NOT touch classification, main_certainty, changed/changed_by,
    and does NOT call recalculate_main_set. It is a standalone audit entry.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        row = cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not row:
            return {'status': 'error', 'message': 'Paper not found'}
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except Exception:
            existing_log = []
        log_entry = {
            "timestamp": timestamp,
            "type": "trace_review",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json.dumps({"report": report_content or ""}),
            "valid": valid
        }
        if invalid_reason:
            log_entry["invalid_reason"] = invalid_reason
        existing_log.append(log_entry)
        cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
        conn.commit()
    return {'status': 'success'}