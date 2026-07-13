# globals.py
# v1.2nightly16 - Configuration and shared utilities
import requests
import json
import re
import threading
import os
import sys
from datetime import datetime, timezone

LLM_SERVER_URL = "http://localhost:8086"

QUEUE_MANAGER_HOST = "localhost"
QUEUE_MANAGER_PORT = 6001
QUEUE_MANAGER_URL = f"http://{QUEUE_MANAGER_HOST}:{QUEUE_MANAGER_PORT}"

# Maximum concurrent limits for homogeneous workloads (only one task type running)
MAX_CONCURRENT_WORKERS_CLASSIFY = 5 #256 #27B 60 
MAX_CONCURRENT_WORKERS_VERIFY = 5  #480 #27B 90
MAX_CONCURRENT_WORKERS_RECLASSIFY = 5 #180 #27B 48
MIN_CONCURRENT_WORKERS = 5     # Minimum concurrent limit for mixed workloads


MAX_CONSENSUS_ITERATIONS = 15
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

# Calculate user_override_count
BOOLEAN_FEATURE_KEYS = [
    'tracks', 'holes', 'bare_pcb_other', 'solder_insufficient',
    'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
    'orientation', 'wrong_component', 'missing_component',
    'component_other', 'cosmetic'
]
BOOLEAN_TECHNIQUE_KEYS = [
    'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
    'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
    'dl_other', 'hybrid', 'available_dataset'
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
    sys.exit(1)

PERFORMANCE_LOG_FILE = os.path.join(os.getcwd(), 'data', 'performance_log.jsonl')
os.makedirs(os.path.dirname(PERFORMANCE_LOG_FILE), exist_ok=True)

def log_performance_event(event_type, data):
    log_entry = {
        'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
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