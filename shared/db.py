# shared/db.py
import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from . import config  # Replaces 'import globals'

_db_path = None

def init_db(db_path):
    global _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(_db_path), exist_ok=True)

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
            conditions.append("(p.is_offtopic = 0 OR p.is_offtopic IS NULL)")
        if year_from is not None:
            try:
                year_from = int(year_from)
                conditions.append("p.year >= ?")
                params.append(year_from)
            except (ValueError, TypeError): pass
        if year_to is not None:
            try:
                year_to = int(year_to)
                conditions.append("p.year <= ?")
                params.append(year_to)
            except (ValueError, TypeError): pass
        if min_page_count is not None:
            try:
                min_page_count = int(min_page_count)
                conditions.append("(p.page_count IS NULL OR p.page_count = '' OR p.page_count >= ?)")
                params.append(min_page_count)
            except (ValueError, TypeError): pass

        query_parts = [base_query]
        if conditions:
            query_parts.append("WHERE " + " AND ".join(conditions))
        query_parts.append("ORDER BY (p.user_trace IS NULL OR p.user_trace = '') ASC")
        
        query = " ".join(query_parts)
        papers = conn.execute(query, params).fetchall()
        
        paper_list = []
        for paper in papers:
            paper_dict = dict(paper)
            try: paper_dict['features'] = json.loads(paper_dict['features']) if paper_dict['features'] else {}
            except (json.JSONDecodeError, TypeError): paper_dict['features'] = {}
            try: paper_dict['technique'] = json.loads(paper_dict['technique']) if paper_dict['technique'] else {}
            except (json.JSONDecodeError, TypeError): paper_dict['technique'] = {}
            try: paper_dict['main_certainty'] = json.loads(paper_dict['main_certainty']) if paper_dict['main_certainty'] else {}
            except (json.JSONDecodeError, TypeError): paper_dict['main_certainty'] = {}
            paper_dict['changed_formatted'] = format_changed_timestamp(paper_dict.get('changed'))
            paper_list.append(paper_dict)
            
        return paper_list

def fetch_updated_paper_data(paper_id):
    with get_db() as conn:
        updated_paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if updated_paper:
            updated_dict = dict(updated_paper)
            try: updated_dict['features'] = json.loads(updated_dict['features'])
            except (json.JSONDecodeError, TypeError): updated_dict['features'] = {}
            try: updated_dict['technique'] = json.loads(updated_dict['technique'])
            except (json.JSONDecodeError, TypeError): updated_dict['technique'] = {}
            updated_dict['changed_formatted'] = format_changed_timestamp(updated_dict.get('changed'))
            return {
                'status': 'success',
                'changed': updated_dict.get('changed'),
                'changed_formatted': updated_dict['changed_formatted'],
                'changed_by': updated_dict.get('changed_by'),
                'verified_by': updated_dict.get('verified_by'),
                'research_area': updated_dict.get('research_area'),
                'page_count': updated_dict.get('page_count'),
                'is_survey': updated_dict.get('is_survey'),
                'is_offtopic': updated_dict.get('is_offtopic'),
                'is_through_hole': updated_dict.get('is_through_hole'),
                'is_smt': updated_dict.get('is_smt'),
                'is_x_ray': updated_dict.get('is_x_ray'),
                'relevance': updated_dict.get('relevance'),
                'verified': updated_dict.get('verified'),
                'estimated_score': updated_dict.get('estimated_score'),
                'features': updated_dict['features'],
                'technique': updated_dict['technique'],
                'user_trace': updated_dict.get('user_trace'),
                'user_override_count': updated_dict.get('user_override_count')
            }
        return {'status': 'error', 'message': 'Paper not found after update.'}

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
    """
    Update the custom classification fields for a paper.
    User changes only affect main columns, not set_* columns.
    Updates certainty_map for all changed fields to 'solid'.
    Handles verified_by field updates.
    Verification Reset Rules:
    - If user explicitly sets verified/verified_by, those values stick
    - If user changes non-verification fields on LLM-verified paper, verification resets
    - If user changes non-verification fields on user-verified paper, verification stays
    """
    # These need to persist after the with block closes
    certainty_map = {}
    rows_affected = 0
    
    with get_db() as conn:
        cursor = conn.cursor()
        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        cursor.execute("""
            SELECT llm_log, user_override_count, 
                   last_llm_features, last_llm_technique, 
                   last_llm_is_survey, last_llm_is_offtopic, 
                   last_llm_is_through_hole, last_llm_is_smt, last_llm_is_x_ray, 
                   last_llm_relevance, last_llm_verified, last_llm_estimated_score,
                   features, technique,
                   is_survey, is_offtopic, is_through_hole, is_smt, is_x_ray,
                   relevance, verified, estimated_score, 
                   user_trace, main_certainty, verified_by, pdf_filename, pdf_state
            FROM papers WHERE id = ?
        """, (paper_id,))
        row = cursor.fetchone()
        
        if not row:
            return {'status': 'error', 'message': 'Paper not found'}
            
        (current_llm_log_str, current_user_override_count,
         last_llm_features_str, last_llm_technique_str,
         last_llm_is_survey, last_llm_is_offtopic,
         last_llm_is_through_hole, last_llm_is_smt, last_llm_is_x_ray,
         last_llm_relevance, last_llm_verified, last_llm_estimated_score,
         current_features_str, current_technique_str,
         current_is_survey, current_is_offtopic,
         current_is_through_hole, current_is_smt, current_is_x_ray,
         current_relevance, current_verified, current_estimated_score,
         current_user_trace, current_certainty_str, current_verified_by,
         current_pdf_filename, current_pdf_state) = row

        # === Save original verified_by BEFORE any processing ===
        original_verified_by = current_verified_by
        try: existing_log = json.loads(current_llm_log_str) if current_llm_log_str else []
        except (json.JSONDecodeError, TypeError): existing_log = []
        try: current_features = json.loads(current_features_str) if current_features_str else {}
        except (json.JSONDecodeError, TypeError): current_features = {}
        try: current_technique = json.loads(current_technique_str) if current_technique_str else {}
        except (json.JSONDecodeError, TypeError): current_technique = {}
        try: certainty_map = json.loads(current_certainty_str) if current_certainty_str else {}
        except (json.JSONDecodeError, TypeError): certainty_map = {}

        update_fields = []
        update_values = []
        updated_main_fields = {}
        user_set_verified = 'verified' in data
        user_set_verified_by = 'verified_by' in data

        # Feature Updates
        feature_updates = {}
        for key in list(data.keys()):
            if key.startswith('features_'):
                feature_key = key.split('features_', 1)[1]
                value = data[key]
                if isinstance(value, str):
                    if value.lower() == 'true': feature_updates[feature_key] = True
                    elif value.lower() == 'false': feature_updates[feature_key] = False
                    elif value == '': feature_updates[feature_key] = None
                    else: feature_updates[feature_key] = value
                else: feature_updates[feature_key] = value
                data.pop(key)
                
        if feature_updates:
            current_features.update(feature_updates)
            update_fields.append("features = ?")
            update_values.append(json.dumps(current_features))
            for fk in feature_updates.keys(): certainty_map[f'features_{fk}'] = 'solid'

        # Technique Updates
        technique_updates = {}
        for key in list(data.keys()):
            if key.startswith('technique_'):
                tech_key = key.split('technique_', 1)[1]
                value = data[key]
                if isinstance(value, str):
                    if value.lower() == 'true': technique_updates[tech_key] = True
                    elif value.lower() == 'false': technique_updates[tech_key] = False
                    elif value == '': technique_updates[tech_key] = None
                    else: technique_updates[tech_key] = value
                else: technique_updates[tech_key] = value
                data.pop(key)
                
        if technique_updates:
            current_technique.update(technique_updates)
            update_fields.append("technique = ?")
            update_values.append(json.dumps(current_technique))
            for tk in technique_updates.keys(): certainty_map[f'technique_{tk}'] = 'solid'

        # Main Boolean Fields
        main_bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
        for field in main_bool_fields:
            if field in data:
                value = data[field]
                if isinstance(value, str):
                    db_val = 1 if value.lower() in ('true', '1', 'on') else (0 if value.lower() in ('false', '0') else None)
                else:
                    db_val = 1 if value is True else (0 if value is False else None)
                update_fields.append(f"{field} = ?")
                update_values.append(db_val)
                updated_main_fields[field] = db_val
                certainty_map[field] = 'solid'
                
                if field == 'is_survey': current_is_survey = db_val
                elif field == 'is_offtopic': current_is_offtopic = db_val
                elif field == 'is_through_hole': current_is_through_hole = db_val
                elif field == 'is_smt': current_is_smt = db_val
                elif field == 'is_x_ray': current_is_x_ray = db_val
                data.pop(field)

        # Other scalar fields (restoring old order: field first, then value)
        if 'research_area' in data:
            update_fields.append("research_area = ?")
            update_values.append(data['research_area'])
            data.pop('research_area')
        if 'page_count' in data:
            page_count_value = data['page_count']
            if page_count_value is not None:
                try:
                    page_count_value = int(page_count_value)
                except (ValueError, TypeError):
                    page_count_value = None
            update_fields.append("page_count = ?")
            update_values.append(page_count_value)
            data.pop('page_count')
        if 'relevance' in data:
            update_fields.append("relevance = ?")
            update_values.append(data['relevance'])
            current_relevance = data['relevance']
            data.pop('relevance')
        if 'user_trace' in data:
            update_fields.append("user_trace = ?")
            update_values.append(data['user_trace'])
            current_user_trace = data['user_trace']
            data.pop('user_trace')

        # Automated paywall detection
        is_paywalled_present = 'paywalled' in str(current_user_trace).lower()
        has_pdf = bool(current_pdf_filename)
        if is_paywalled_present:
            if not has_pdf and current_pdf_state != "paywalled":
                update_fields.append("pdf_state = ?")
                update_values.append("paywalled")
            else:
                if not has_pdf and current_pdf_state == "paywalled":
                    update_fields.append("pdf_state = ?")
                    update_values.append("none")

        # Verification explicit overrides
        if 'verified' in data:
            val = data['verified']
            if isinstance(val, str):
                db_val = 1 if val.lower() in ('true', '1', 'on') else (0 if val.lower() in ('false', '0') else None)
            else:
                db_val = 1 if val is True else (0 if val is False else None)
            update_fields.append("verified = ?")
            update_values.append(db_val)
            current_verified = db_val
            current_verified_by = 'user'
            update_fields.append("verified_by = ?")
            update_values.append('user')
            data.pop('verified')
            
        if 'verified_by' in data:
            verified_by_value = data['verified_by']
            db_val = None if verified_by_value == 'unknown' or verified_by_value is None else verified_by_value
            update_fields.append("verified_by = ?")
            update_values.append(db_val)
            current_verified_by = db_val
            data.pop('verified_by')
            
        if 'estimated_score' in data:
            val = data['estimated_score']
            db_val = max(0, min(100, int(val))) if isinstance(val, (int, float)) else None
            update_fields.append("estimated_score = ?")
            update_values.append(db_val)
            current_estimated_score = db_val
            data.pop('estimated_score')

        # Verification Reset Logic (AFTER all field processing)
        if changed_by == "user" and not user_set_verified and not user_set_verified_by:
            was_llm_verified = (original_verified_by and
                                original_verified_by.strip() != '' and
                                original_verified_by != 'user')
            if was_llm_verified:
                update_fields.append("verified = ?")
                update_values.append(None)
                update_fields.append("estimated_score = ?")
                update_values.append(None)
                update_fields.append("verified_by = ?")
                update_values.append("")
                current_verified = None
                current_estimated_score = None
                current_verified_by = ""

        # User Override Count Calculation
        def normalize_bool(val):
            if val is None or val == '' or val == 'null': return None
            if val is True or val == 1 or val == '1' or val == 'true': return 1
            if val is False or val == 0 or val == '0' or val == 'false': return 0
            return val
            
        user_override_count = 0
        try: last_llm_features = json.loads(last_llm_features_str) if last_llm_features_str else {}
        except (json.JSONDecodeError, TypeError): last_llm_features = {}
        try: last_llm_technique = json.loads(last_llm_technique_str) if last_llm_technique_str else {}
        except (json.JSONDecodeError, TypeError): last_llm_technique = {}
        
        for key in config.BOOLEAN_FEATURE_KEYS:
            if normalize_bool(current_features.get(key)) != normalize_bool(last_llm_features.get(key)): user_override_count += 1
        for key in config.BOOLEAN_TECHNIQUE_KEYS:
            if normalize_bool(current_technique.get(key)) != normalize_bool(last_llm_technique.get(key)): user_override_count += 1
        for field in ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']:
            if normalize_bool(locals()[f'current_{field}']) != normalize_bool(locals()[f'last_llm_{field}']): user_override_count += 1

        update_fields.append("changed = ?")
        update_values.append(changed_timestamp)
        update_fields.append("changed_by = ?")
        update_values.append(changed_by)
        update_fields.append("user_override_count = ?")
        update_values.append(user_override_count)
        update_fields.append("main_certainty = ?")
        update_values.append(json.dumps(certainty_map))

        # Log Building
        def db_to_bool(val):
            if val == 1: return True
            elif val == 0: return False
            else: return None
            
        user_log_output = {
            "is_offtopic": db_to_bool(updated_main_fields.get('is_offtopic', current_is_offtopic)),
            "relevance": current_relevance,
            "is_survey": db_to_bool(updated_main_fields.get('is_survey', current_is_survey)),
            "is_through_hole": db_to_bool(updated_main_fields.get('is_through_hole', current_is_through_hole)),
            "is_smt": db_to_bool(updated_main_fields.get('is_smt', current_is_smt)),
            "is_x_ray": db_to_bool(updated_main_fields.get('is_x_ray', current_is_x_ray)),
            "features": current_features if current_features else {},
            "technique": current_technique if current_technique else {},
            "verified": db_to_bool(current_verified),
            "verified_by": current_verified_by,
            "estimated_score": current_estimated_score
        }
        # === If verification was reset, update user_log_output to reflect it ===

        if changed_by == "user" and not user_set_verified and not user_set_verified_by:
            was_llm_verified = (original_verified_by and
                                original_verified_by.strip() != '' and
                                original_verified_by != 'user')
            if was_llm_verified:
                user_log_output['verified'] = None
                user_log_output['estimated_score'] = None

        user_log_entry = {
            "timestamp": changed_timestamp,
            "type": "user",
            "model": "user",
            "trace": current_user_trace or "",
            "output": json.dumps(user_log_output),
            "valid": True,
            "certainty_map": certainty_map
        }
        
        if existing_log and existing_log[-1].get('type') == 'user':
            last_user_entry = existing_log[-1]
            last_user_entry['output'] = json.dumps(user_log_output)
            last_user_entry['trace'] = current_user_trace or ""
            last_user_entry['timestamp'] = changed_timestamp
            last_user_entry['certainty_map'] = certainty_map
        else:
            existing_log.append(user_log_entry)
            
        update_fields.append("llm_log = ?")
        update_values.append(json.dumps(existing_log))

        if update_fields:
            update_values.append(paper_id)
            cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values)
            # ================================================================
            # CRITICAL FIX: Commit BEFORE reading back.
            #
            # The OLD version called conn.commit() then conn.close() before
            # calling get_paper_by_id(). The NEW version's get_db() context
            # manager only commits when the with-block exits, which is AFTER
            # get_paper_by_id() opens a separate connection and reads stale
            # (uncommitted) data. This caused:
            #   1. Verified cell updates appearing to fail (UI reverts)
            #   2. History entries not updating in the response
            #   3. If get_paper_by_id raises, the except block ROLLS BACK
            #      the entire transaction, truly losing the user's changes
            # ================================================================ 
        conn.commit()
        rows_affected = cursor.rowcount

    # === OUTSIDE the with block: connection is committed and closed ===
    # get_paper_by_id() now opens a fresh connection that sees committed data.
    
        if rows_affected > 0:
            updated_paper = get_paper_by_id(paper_id)
            if updated_paper:
                updated_paper['changed_formatted'] = format_changed_timestamp(updated_paper.get('changed'))
                return {
                    'status': 'success',
                    'changed': updated_paper.get('changed'),
                    'changed_formatted': updated_paper.get('changed_formatted'),
                    'changed_by': updated_paper.get('changed_by'),
                    'research_area': updated_paper.get('research_area'),
                    'page_count': updated_paper.get('page_count'),
                    'is_survey': updated_paper.get('is_survey'),
                    'is_offtopic': updated_paper.get('is_offtopic'),
                    'is_through_hole': updated_paper.get('is_through_hole'),
                    'is_smt': updated_paper.get('is_smt'),
                    'is_x_ray': updated_paper.get('is_x_ray'),
                    'relevance': updated_paper.get('relevance'),
                    'features': updated_paper.get('features', {}),
                    'technique': updated_paper.get('technique', {}),
                    'user_trace': updated_paper.get('user_trace'),
                    'user_override_count': updated_paper.get('user_override_count'),
                    'verified': updated_paper.get('verified'),
                    'verified_by': updated_paper.get('verified_by'),
                    'estimated_score': updated_paper.get('estimated_score'),
                    'main_certainty': certainty_map,
                    'pdf_state': updated_paper.get('pdf_state'),
                    'pdf_filename': updated_paper.get('pdf_filename')
                }
            else:
                return {'status': 'error', 'message': 'Paper not found after update.'}
        else:
            return {'status': 'error', 'message': 'No rows updated.'}

def update_set_cache(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid, log_type="classifier", reset_verification=False):
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{set_num}_last_llm_'
        
        update_fields = []
        update_values = []
        
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            if field in llm_data:
                val = llm_data[field]
                update_fields.append(f"{prefix}{field} = ?")
                update_values.append(1 if val is True else 0 if val is False else None)
        if 'relevance' in llm_data:
            update_fields.append(f"{prefix}relevance = ?"); update_values.append(llm_data['relevance'])
        if 'features' in llm_data:
            update_fields.append(f"{prefix}features = ?"); update_values.append(json.dumps(llm_data['features']))
        if 'technique' in llm_data:
            update_fields.append(f"{prefix}technique = ?"); update_values.append(json.dumps(llm_data['technique']))
            
        if reset_verification:
            update_fields.extend([f"{prefix}verified = ?", f"{prefix}estimated_score = ?"])
            update_values.extend([None, None])
            
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except (json.JSONDecodeError, TypeError): existing_log = []
        
        existing_log.append({"timestamp": timestamp, "type": log_type, "model": model_name, "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid})
        
        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        if update_fields:
            update_values.append(paper_id)
            cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values)

def update_set_verifier(paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid):
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{set_num}_last_llm_'
        
        update_fields = []
        update_values = []
        
        if 'verified' in llm_data:
            val = llm_data['verified']
            update_fields.append(f"{prefix}verified = ?"); update_values.append(1 if val is True else 0 if val is False else None)
        if 'estimated_score' in llm_data:
            update_fields.append(f"{prefix}estimated_score = ?"); update_values.append(int(llm_data['estimated_score']))
            
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except (json.JSONDecodeError, TypeError): existing_log = []
        
        existing_log.append({"timestamp": timestamp, "type": "verifier", "model": model_name, "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid})
        
        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        if update_fields:
            update_values.append(paper_id)
            cursor.execute(f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?", update_values)

def update_set_log_only(paper_id, set_num, log_type, model_name, reasoning_trace, json_result, valid):
    with get_db() as conn:
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        try: existing_log = json.loads(row[0]) if row and row[0] else []
        except (json.JSONDecodeError, TypeError): existing_log = []
        
        existing_log.append({"timestamp": timestamp, "type": log_type, "model": model_name, "trace": reasoning_trace or "", "output": json_result or "{}", "valid": valid})
        
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))

def recalculate_main_set(paper_id, changed_by="LLM_Averaged", create_log_entry=True):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        paper = cursor.fetchone()
        if not paper: return None
        
        paper = dict(paper)
        changed_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        boolean_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
        
        certainty_map = {}
        main_output = {}
        
        for field in boolean_fields:
            values = [paper.get(f'set_1_last_llm_{field}'), paper.get(f'set_2_last_llm_{field}'), paper.get(f'set_3_last_llm_{field}')]
            main_value, certainty = calculate_field_certainty(values)
            certainty_map[field] = certainty
            main_output[field] = main_value
            cursor.execute(f"UPDATE papers SET {field} = ? WHERE id = ?", (main_value, paper_id))
            
        relevance_values = [paper.get('set_1_last_llm_relevance'), paper.get('set_2_last_llm_relevance'), paper.get('set_3_last_llm_relevance')]
        relevance_valid = [v for v in relevance_values if v is not None]
        main_relevance = sum(relevance_valid) / len(relevance_valid) if relevance_valid else None
        main_output['relevance'] = main_relevance
        cursor.execute("UPDATE papers SET relevance = ? WHERE id = ?", (main_relevance, paper_id))
        
        score_values = [paper.get('set_1_last_llm_estimated_score'), paper.get('set_2_last_llm_estimated_score'), paper.get('set_3_last_llm_estimated_score')]
        verified_from_score = []
        for score in score_values:
            if score is None: verified_from_score.append(None)
            elif score >= 7: verified_from_score.append(1)
            else: verified_from_score.append(0)
            
        main_verified, verified_certainty = calculate_field_certainty(verified_from_score)
        certainty_map['verified'] = verified_certainty
        main_output['verified'] = main_verified
        cursor.execute("UPDATE papers SET verified = ? WHERE id = ?", (main_verified, paper_id))
        
        score_valid = [v for v in score_values if v is not None]
        main_score = sum(score_valid) / len(score_valid) if score_valid else None
        main_output['estimated_score'] = int(main_score) if main_score is not None else None
        cursor.execute("UPDATE papers SET estimated_score = ? WHERE id = ?", (main_output['estimated_score'], paper_id))
        
        main_features = {}
        for feature_key in config.BOOLEAN_FEATURE_KEYS:
            values = []
            for sn in [1, 2, 3]:
                feat_str = paper.get(f'set_{sn}_last_llm_features')
                try: feat = json.loads(feat_str) if feat_str else {}
                except: feat = {}
                if feat is None: feat = {}
                values.append(feat.get(feature_key))
                
            main_value, certainty = calculate_field_certainty(values)
            field_name = f'features_{feature_key}'
            certainty_map[field_name] = certainty
            main_features[feature_key] = main_value
            
        main_output['features'] = main_features
        cursor.execute("UPDATE papers SET features = ? WHERE id = ?", (json.dumps(main_features), paper_id))
        
        main_technique = {}
        for tech_key in config.DEFAULT_TECHNIQUE.keys():
            if tech_key in ['model', 'available_dataset']: continue
            values = []
            for sn in [1, 2, 3]:
                tech_str = paper.get(f'set_{sn}_last_llm_technique')
                try: tech = json.loads(tech_str) if tech_str else {}
                except: tech = {}
                if tech is None: tech = {}
                values.append(tech.get(tech_key))
                
            main_value, certainty = calculate_field_certainty(values)
            field_name = f'technique_{tech_key}'
            certainty_map[field_name] = certainty
            main_technique[tech_key] = main_value
            
        try:
            tech1_str = paper.get('set_1_last_llm_technique')
            tech1 = json.loads(tech1_str) if tech1_str else {}
            main_technique['model'] = tech1.get('model')
            main_technique['available_dataset'] = tech1.get('available_dataset')
        except:
            main_technique['model'] = None
            main_technique['available_dataset'] = None
            
        main_output['technique'] = main_technique
        cursor.execute("UPDATE papers SET technique = ? WHERE id = ?", (json.dumps(main_technique), paper_id))
        
        cursor.execute("UPDATE papers SET main_certainty = ? WHERE id = ?", (json.dumps(certainty_map), paper_id))
        
        cursor.execute("""
            UPDATE papers SET 
                last_llm_features = features, last_llm_technique = technique,
                last_llm_is_offtopic = is_offtopic, last_llm_is_survey = is_survey,
                last_llm_is_through_hole = is_through_hole, last_llm_is_smt = is_smt,
                last_llm_is_x_ray = is_x_ray, last_llm_relevance = relevance,
                last_llm_verified = verified, last_llm_estimated_score = estimated_score
            WHERE id = ?
        """, (paper_id,))
        
        cursor.execute("""UPDATE papers SET changed = ?, changed_by = ? WHERE id = ?""", (changed_timestamp, changed_by, paper_id))
        
        if create_log_entry:
            row = cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,)).fetchone()
            try: existing_log = json.loads(row[0]) if row and row[0] else []
            except: existing_log = []
            
            log_entry = {
                "timestamp": changed_timestamp, "type": "averaged_llm", "model": "averaged_3_sets",
                "trace": "Averaged from 3 classification sets", 
                "output": json.dumps({**main_output, "certainty_map": certainty_map}), 
                "valid": True, "certainty_map": certainty_map
            }
            
            # FIX: Always append for AI events. Do not overwrite user entries!
            existing_log.append(log_entry)
            cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
            
        return certainty_map