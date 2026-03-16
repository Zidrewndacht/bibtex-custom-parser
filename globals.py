# globals.py
# v1.2nightly13 - Configuration and shared utilities
import requests
import json
import sqlite3
import re
import threading
import os
from datetime import datetime

LLM_SERVER_URL = "http://localhost:8086"
QUEUE_MANAGER_URL = "http://localhost:5001"

# Maximum concurrent limits for homogeneous workloads (only one task type running)
MAX_CONCURRENT_WORKERS_CLASSIFY = 256
MAX_CONCURRENT_WORKERS_VERIFY = 480
MAX_CONCURRENT_WORKERS_RECLASSIFY = 96
MIN_CONCURRENT_WORKERS = 32     # Minimum concurrent limit for mixed workloads

MAX_CONSENSUS_ITERATIONS = 12
FRESH_CLASSIFY_FALLBACK_ITERATION = 8

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_TEMPLATES_DIR = os.path.join(BASE_DIR, 'prompt_templates')

PROMPT_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'classify_template.txt')
VERIFIER_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'verify_template.txt')
RECLASSIFY_PROMPT_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'reclassify_template.txt')

LLM_API_KEY = None
DATABASE_FILE = os.path.join(os.getcwd(), 'data', 'db.sqlite')
os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)

PDF_STORAGE_DIR = os.path.join(os.getcwd(), 'data', 'pdf')
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)

ANNOTATED_PDF_STORAGE_DIR = os.path.join(os.getcwd(), 'data', 'pdf_annotated')
os.makedirs(ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)

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

BOOLEAN_FEATURE_KEYS = [
    "tracks", "holes", "bare_pcb_other", "solder_insufficient",
    "solder_excess", "solder_void", "solder_crack", "solder_other",
    "orientation", "wrong_component", "missing_component",
    "component_other", "cosmetic"
]

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

TYPE_EMOJIS = {
    'article': '📄',
    'inproceedings': '📚',
    'incollection': '📖',
    'book': '📘',
    'phdthesis': '🎓',
    'mastersthesis': '🎓',
    'techreport': '📋',
    'misc': '📁',
}

DEFAULT_TYPE_EMOJI = '📄'

PDF_EMOJIS = {
    'PDF': '📕',
    'annotated': '📗',
    'paywalled': '💰',
    'none': '❔'
}

# Global Shutdown Flag
shutdown_lock = threading.Lock()
shutdown_flag = False

def set_shutdown_flag():
    global shutdown_flag
    with shutdown_lock:
        shutdown_flag = True

def is_shutdown_flag_set():
    global shutdown_flag
    with shutdown_lock:
        return shutdown_flag

def signal_handler(sig, frame):
    print("\nReceived Ctrl+C. Killing all threads...")
    set_shutdown_flag()
    os._exit(1)

PERFORMANCE_LOG_FILE = os.path.join(os.getcwd(), 'data', 'performance_log.jsonl')
os.makedirs(os.path.dirname(PERFORMANCE_LOG_FILE), exist_ok=True)

def log_performance_event(event_type, data):
    log_entry = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'event_type': event_type,
        **data
    }
    try:
        with open(PERFORMANCE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"Warning: Failed to write performance log: {e}")

# ============================================================================
# TRIPLE-CLASSIFICATION SYSTEM
# ============================================================================

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

def recalculate_main_set(paper_id, db_path=None, changed_by="LLM_Averaged", create_log_entry=True):
    if db_path is None:
        db_path = DATABASE_FILE
    
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        paper = cursor.fetchone()
        if not paper:
            conn.close()
            return None
        
        paper = dict(paper)
        changed_timestamp = datetime.utcnow().isoformat() + 'Z'
        
        boolean_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
        certainty_map = {}
        main_output = {}
        
        for field in boolean_fields:
            values = [
                paper.get(f'set_1_last_llm_{field}'),
                paper.get(f'set_2_last_llm_{field}'),
                paper.get(f'set_3_last_llm_{field}'),
            ]
            main_value, certainty = calculate_field_certainty(values)
            certainty_map[field] = certainty
            main_output[field] = main_value
            cursor.execute(f"UPDATE papers SET {field} = ? WHERE id = ?", (main_value, paper_id))
        
        relevance_values = [
            paper.get('set_1_last_llm_relevance'),
            paper.get('set_2_last_llm_relevance'),
            paper.get('set_3_last_llm_relevance'),
        ]
        relevance_valid = [v for v in relevance_values if v is not None]
        main_relevance = sum(relevance_valid) / len(relevance_valid) if relevance_valid else None
        main_output['relevance'] = main_relevance
        cursor.execute("UPDATE papers SET relevance = ? WHERE id = ?", (main_relevance, paper_id))
        
        score_values = [
            paper.get('set_1_last_llm_estimated_score'),
            paper.get('set_2_last_llm_estimated_score'),
            paper.get('set_3_last_llm_estimated_score'),
        ]
        verified_from_score = []
        for score in score_values:
            if score is None:
                verified_from_score.append(None)
            elif score >= 7:
                verified_from_score.append(1)
            else:
                verified_from_score.append(0)
        
        main_verified, verified_certainty = calculate_field_certainty(verified_from_score)
        certainty_map['verified'] = verified_certainty
        main_output['verified'] = main_verified
        cursor.execute("UPDATE papers SET verified = ? WHERE id = ?", (main_verified, paper_id))
        
        score_valid = [v for v in score_values if v is not None]
        main_score = sum(score_valid) / len(score_valid) if score_valid else None
        main_output['estimated_score'] = int(main_score) if main_score is not None else None
        cursor.execute("UPDATE papers SET estimated_score = ? WHERE id = ?", (main_output['estimated_score'], paper_id))
        
        main_features = {}
        for feature_key in BOOLEAN_FEATURE_KEYS:
            values = []
            # In recalculate_main_set(), around line 240-250:
            for sn in [1, 2, 3]:
                feat_key = f'set_{sn}_last_llm_features'
                feat_str = paper.get(feat_key)
                try:
                    feat = json.loads(feat_str) if feat_str else {}
                except:
                    feat = {}
                if feat is None:
                    feat = {}
                
                values.append(feat.get(feature_key))

            main_value, certainty = calculate_field_certainty(values)
            field_name = f'features_{feature_key}'
            certainty_map[field_name] = certainty
            main_features[feature_key] = main_value
        main_output['features'] = main_features
        cursor.execute("UPDATE papers SET features = ? WHERE id = ?", (json.dumps(main_features), paper_id))
        
        main_technique = {}
        for tech_key in DEFAULT_TECHNIQUE.keys():
            if tech_key in ['model', 'available_dataset']:
                continue
            values = []
            for sn in [1, 2, 3]:
                tech_key_db = f'set_{sn}_last_llm_technique'
                tech_str = paper.get(tech_key_db)
                try:
                    tech = json.loads(tech_str) if tech_str else {}
                except:
                    tech = {}
                
                # ← ADD THIS: Handle case where json.loads returns None
                if tech is None:
                    tech = {}
                
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
            last_llm_features = features,
            last_llm_technique = technique,
            last_llm_is_offtopic = is_offtopic,
            last_llm_is_survey = is_survey,
            last_llm_is_through_hole = is_through_hole,
            last_llm_is_smt = is_smt,
            last_llm_is_x_ray = is_x_ray,
            last_llm_relevance = relevance,
            last_llm_verified = verified,
            last_llm_estimated_score = estimated_score
            WHERE id = ?
        """, (paper_id,))
        
        cursor.execute("""
            UPDATE papers SET
            changed = ?,
            changed_by = ?
            WHERE id = ?
        """, (changed_timestamp, changed_by, paper_id))
        
        if create_log_entry:
            cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,))
            row = cursor.fetchone()
            try:
                existing_log = json.loads(row[0]) if row and row[0] else []
            except:
                existing_log = []
            
            log_entry = {
                "timestamp": changed_timestamp,
                "type": "averaged_llm",
                "model": "averaged_3_sets",
                "trace": f"Averaged from 3 classification sets",
                "output": json.dumps({**main_output, "certainty_map": certainty_map}),
                "valid": True,
                "certainty_map": certainty_map
            }
            
            if existing_log and existing_log[-1].get('type') == 'user':
                existing_log[-1] = log_entry
            else:
                existing_log.append(log_entry)
            
            cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(existing_log), paper_id))
        
        conn.commit()
        conn.close()
        return certainty_map
    
    finally:
        if conn:
            conn.close()

def get_set_data(paper_data, set_num):
    prefix = f'set_{set_num}_last_llm_'
    data = {}
    for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', 'relevance', 'verified', 'estimated_score']:
        data[field] = paper_data.get(f'{prefix}{field}')
    
    features_str = paper_data.get(f'{prefix}features')
    technique_str = paper_data.get(f'{prefix}technique')
    try:
        data['features'] = json.loads(features_str) if features_str else {}
    except:
        data['features'] = {}
    try:
        data['technique'] = json.loads(technique_str) if technique_str else {}
    except:
        data['technique'] = {}
    
    return data

def get_model_alias(server_url_base):
    models_url = f"{server_url_base.rstrip('/')}/v1/models"
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    try:
        response = requests.get(models_url, headers=headers, timeout=30)
        response.raise_for_status()
        models_data = response.json()
        if models_data and isinstance(models_data.get('data'), list) and models_data['data']:
            model_alias = models_data['data'][0].get('id')
            if model_alias:
                print(f"Detected model alias: '{model_alias}'")
                return model_alias
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to LLM server: {e}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
    
    fallback_alias = "Unknown_LLM"
    print(f"Using fallback model alias: '{fallback_alias}'")
    return fallback_alias

def load_prompt_template(template_path):
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Prompt template file '{template_path}' not found.")
        raise
    except Exception as e:
        print(f"Error reading prompt template file '{template_path}': {e}")
        raise

def get_paper_by_id(db_path, paper_id):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        if conn:
            conn.close()

def get_best_set_for_text_fields(paper_data):
    set_scores = []
    for set_num in [1, 2, 3]:
        verified = paper_data.get(f'set_{set_num}_last_llm_verified')
        score = paper_data.get(f'set_{set_num}_last_llm_estimated_score')
        
        if verified == 1 and score is not None:
            set_scores.append((set_num, score + 1000))
        elif verified == 1:
            set_scores.append((set_num, 1000))
        elif score is not None:
            set_scores.append((set_num, score))
        else:
            set_scores.append((set_num, 0))
    
    best_set = max(set_scores, key=lambda x: x[1])[0]
    return best_set

def send_prompt_to_llm(prompt_text, server_url_base=None, model_name="default", is_verification=False):
    if server_url_base is None:
        server_url_base = LLM_SERVER_URL
    
    chat_url = f"{server_url_base.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0,
        "max_tokens": 32768,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": True}
    }
    
    context = "verification " if is_verification else ""
    
    try:
        if is_shutdown_flag_set():
            return None, None, None
        
        response = requests.post(chat_url, headers=headers, json=payload, timeout=2400)
        
        if is_shutdown_flag_set():
            return None, None, None
        
        response.raise_for_status()
        response_data = response.json()
        model_name_from_response = response_data.get('model', model_name)
        
        if 'choices' in response_data and response_data['choices']:
            reasoning_content = None
            message = response_data['choices'][0]['message']
            
            reasoning_content_raw = message.get('reasoning', '')
            if reasoning_content_raw is None or reasoning_content_raw == '':
                reasoning_content_raw = message.get('reasoning_content', '')
            
            if reasoning_content_raw is not None and reasoning_content_raw != '':
                reasoning_content = reasoning_content_raw.strip()
            else:
                reasoning_content = ''
            
            content_raw = message.get('content', '')
            content = content_raw.strip() if content_raw is not None else ''
            
            if not reasoning_content and content:
                think_pattern = r'<think>(.*?)</think>'
                think_matches = re.findall(think_pattern, content, re.DOTALL | re.IGNORECASE)
                if think_matches:
                    reasoning_content = think_matches[0].strip()
                    content = re.sub(think_pattern, '', content, flags=re.DOTALL | re.IGNORECASE).strip()
                    content = re.sub(r'\n\s*\n', '\n', content)
                    content = content.strip()
            
            return content, model_name_from_response, reasoning_content
        else:
            print(f"Warning: Unexpected LLM {context}response structure: {response_data}")
            return None, model_name_from_response, None
    
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection Error: Could not connect to LLM server at {server_url_base}. {str(e)}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except requests.exceptions.Timeout as e:
        error_msg = f"Timeout Error: LLM server did not respond within the timeout period. {str(e)}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Request Error: {str(e)}"
        if hasattr(e, 'response') and e.response:
            error_msg += f"\nResponse Text: {e.response.text}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"JSON Decode Error: {str(e)}"
        if 'response' in locals():
            error_msg += f"\nResponse Text: {response.text}"
        print(f"Error decoding JSON {context}response: {error_msg}")
        return None, model_name, error_msg
    except Exception as e:
        error_msg = f"Unexpected Error: {type(e).__name__}: {str(e)}"
        print(f"Error during {context}LLM request: {error_msg}")
        return None, model_name, error_msg