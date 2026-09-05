# shared/config.py
import json
import os
import re
import shutil
import sys
import threading
from datetime import datetime, timezone

import requests
import yaml

DEBUG_MODE = False  # True = Flask Dev Server (auto-reload). False = Waitress (Production).

# --- PATH OVERRIDES (Crucial for Test Isolation) ---
# Allow environment variables to override default paths for testing/isolation
BASE_DIR = os.environ.get("PARSA_BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.environ.get("PARSA_CONFIG_PATH", os.path.join(BASE_DIR, 'config.yaml'))
DOMAIN_CONFIG_PATH = os.environ.get("PARSA_DOMAIN_CONFIG_PATH", os.path.join(BASE_DIR, 'domain_config.yaml'))

EXAMPLE_CONFIG_DIR = os.path.join(BASE_DIR, 'example_config')
EXAMPLE_CONFIG_PATH = os.path.join(EXAMPLE_CONFIG_DIR, 'config.example.yaml')
EXAMPLE_DOMAIN_CONFIG_PATH = os.path.join(EXAMPLE_CONFIG_DIR, 'domain_config.example.yaml')

def ensure_config_files():
    """Copy example configuration files if the actual ones do not exist."""
    if not os.path.exists(CONFIG_PATH):
        if os.path.exists(EXAMPLE_CONFIG_PATH):
            shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
            print(f"[Init] Created {CONFIG_PATH} from example.")
        else:
            raise RuntimeError(f"Fatal: {CONFIG_PATH} not found and example config missing at {EXAMPLE_CONFIG_PATH}.")
            
    if not os.path.exists(DOMAIN_CONFIG_PATH):
        if os.path.exists(EXAMPLE_DOMAIN_CONFIG_PATH):
            shutil.copy(EXAMPLE_DOMAIN_CONFIG_PATH, DOMAIN_CONFIG_PATH)
            print(f"[Init] Created {DOMAIN_CONFIG_PATH} from example.")
        else:
            raise RuntimeError(f"Fatal: {DOMAIN_CONFIG_PATH} not found and example config missing at {EXAMPLE_DOMAIN_CONFIG_PATH}.")

# Ensure files exist before proceeding to load them
ensure_config_files()


DATA_DIR = os.environ.get("PARSA_DATA_DIR", os.path.join(BASE_DIR, 'data'))
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_FILE = os.environ.get("PARSA_DATABASE_FILE", os.path.join(DATA_DIR, 'db.sqlite'))
PDF_STORAGE_DIR = os.environ.get("PARSA_PDF_DIR", os.path.join(DATA_DIR, 'pdf'))
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)
ANNOTATED_PDF_STORAGE_DIR = os.environ.get("PARSA_PDF_ANNOTATED_DIR", os.path.join(DATA_DIR, 'pdf_annotated'))
os.makedirs(ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)
PERFORMANCE_LOG_FILE = os.path.join(DATA_DIR, 'performance_log.jsonl')

# ==============================================================================
# 1. GENERAL CONFIG LOADER (config.yaml)
# ==============================================================================
def load_general_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not cfg or not isinstance(cfg, dict):
        raise RuntimeError(f"Fatal: {CONFIG_PATH} is empty or invalid YAML.")
    return cfg

_general_config = load_general_config()

# --- User-set settings (No defaults. Raises KeyError if user deleted them) ---
DEFAULT_YEAR_FROM = _general_config['default_year_from']
DEFAULT_YEAR_TO = _general_config['default_year_to']
DEFAULT_MIN_PAGE_COUNT = _general_config['default_min_page_count']

FRONTEND_PORT = _general_config['frontend_port']
FRONTEND_HOST = '0.0.0.0'                  # Intentionally hardcoded setting (not meant to be user-set) - do not move to YAML
FRONTEND_WAITRESS_THREADS = 16             # Intentionally hardcoded setting (not meant to be user-set) - do not move to YAML

QUEUE_MANAGER_PORT = _general_config['queue_manager_port']
QUEUE_MANAGER_HOST = "localhost"
QUEUE_MANAGER_URL = f"http://{QUEUE_MANAGER_HOST}:{QUEUE_MANAGER_PORT}"    # Intentionally hardcoded to localhost - do not change
QUEUE_MANAGER_WAITRESS_THREADS = 32        # Intentionally hardcoded setting (not meant to be user-set) - do not move to YAML

MAX_CONCURRENT_WORKERS_CLASSIFY = _general_config['max_concurrent_workers_classify']
MAX_CONCURRENT_WORKERS_VERIFY = _general_config['max_concurrent_workers_verify']
MAX_CONCURRENT_WORKERS_RECLASSIFY = _general_config['max_concurrent_workers_reclassify']
MIN_CONCURRENT_WORKERS = _general_config['min_concurrent_workers']

MAX_CONSENSUS_ITERATIONS = _general_config['max_consensus_iterations']
FRESH_CLASSIFY_FALLBACK_ITERATION = _general_config['fresh_classify_fallback_iteration']

LLM_SERVER_URL = _general_config['llm_server_url']
LLM_API_KEY = _general_config.get('llm_api_key')  # Allowed to be null/missing


# ==============================================================================
# 2. DOMAIN CONFIG & PROMPT ENGINE (domain_config.yaml)
# ==============================================================================
def _load_text_file(path):
    """Helper to load text files safely."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"Fatal: Template file '{path}' not found.")
    except Exception as e:
        raise RuntimeError(f"Fatal: Could not read template file '{path}': {e}")

def assemble_prompt_templates(prompts_cfg):
    """
    Assembles the final prompt templates by injecting configurable sub-templates 
    (defined in domain_config.yaml) into the fixed base templates. 
    Uses .replace() instead of .format() to preserve escaped braces (e.g. `{{` and `}}`).
    """
    base_templates_dir = os.path.join(BASE_DIR, 'prompt_templates', 'base_templates')
    
    classify_inst_path = os.path.join(BASE_DIR, prompts_cfg['classify_instructions'])
    output_tmpl_path = os.path.join(BASE_DIR, prompts_cfg['classify_output_template'])
    few_shot_path = os.path.join(BASE_DIR, prompts_cfg['few_shot_examples'])


    # 2. Load configurable sub-templates
    classify_inst = _load_text_file(classify_inst_path)
    output_tmpl = _load_text_file(output_tmpl_path)
    few_shot = _load_text_file(few_shot_path)

    # 3. Load fixed base templates
    classify_base = _load_text_file(os.path.join(base_templates_dir, 'classify_base_template.txt'))
    verify_base = _load_text_file(os.path.join(base_templates_dir, 'verify_base_template.txt'))
    reclassify_base = _load_text_file(os.path.join(base_templates_dir, 'reclassify_base_template.txt'))

    # 4. Assemble final strings verbatim
    # Classify
    final_classify = classify_base.replace('{configurable_classify_instructions}', classify_inst)
    final_classify = final_classify.replace('{configurable_classify_output_template}', output_tmpl)
    final_classify = final_classify.replace('{configurable_few_shot_examples}', few_shot)

    # Verify
    final_verify = verify_base.replace('{configurable_classify_instructions}', classify_inst)
    final_verify = final_verify.replace('{configurable_classify_output_template}', output_tmpl)

    # Reclassify (Reuses classify_instructions as designed)
    final_reclassify = reclassify_base.replace('{configurable_classify_instructions}', classify_inst)
    final_reclassify = final_reclassify.replace('{configurable_classify_output_template}', output_tmpl)
    final_reclassify = final_reclassify.replace('{configurable_few_shot_examples}', few_shot)

    return final_classify, final_verify, final_reclassify

def generate_theme_css(domain_config):
    """Dynamically converts the 'theme' dict into CSS :root variables."""
    theme = domain_config.get('theme', {})
    if not theme or not isinstance(theme, dict):
        return ""
    css_vars = []
    for key, value in theme.items():
        if value is not None:
            css_var = "--" + str(key).replace('_', '-')
            css_vars.append(f"    {css_var}: {value};")
    if css_vars:
        return ":root {\n" + "\n".join(css_vars) + "\n}"
    return ""

def load_domain_config():
    with open(DOMAIN_CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
        
    if not cfg or not isinstance(cfg, dict):
        raise RuntimeError(f"Fatal: {DOMAIN_CONFIG_PATH} is empty or invalid YAML.")

    # Validate required keys exist (raises KeyError immediately if missing)
    cfg['domain_name']
    cfg['groups']
    cfg['editable_fields']
    prompts_cfg = cfg['prompts']
    
    required_prompts = ['classify_instructions', 'classify_output_template', 'few_shot_examples']
    for key in required_prompts:
        if key not in prompts_cfg:
            raise RuntimeError(f"Fatal: 'prompts' section in {DOMAIN_CONFIG_PATH} is missing required key: '{key}'")

    # Automatically calculate min/max widths based on dynamic columns
    total_dynamic = 0
    for group in cfg['groups']:
        filter_type = group.get('filter_type')
        if filter_type == 'tri_state':
            total_dynamic += 1
        elif filter_type in ['inclusion', 'none']:
            total_dynamic += len(group.get('fields', []))
            
    extra_cells = max(0, total_dynamic - 9)
    min_width = 1140 + (extra_cells * 27)
    max_width = max(1880, min_width + 720)

    # Inject into theme dict so generate_theme_css picks them up as CSS variables
    theme = cfg.get('theme', {})
    if not isinstance(theme, dict):
        theme = {}
    theme['min_width'] = f"{min_width}px"
    theme['max_width'] = f"{max_width}px"
    cfg['theme'] = theme

    # Assemble Prompt Templates
    try:
        assembled_classify, assembled_verify, assembled_reclassify = assemble_prompt_templates(prompts_cfg)
        cfg['PROMPT_TEMPLATE'] = assembled_classify
        cfg['VERIFIER_TEMPLATE'] = assembled_verify
        cfg['RECLASSIFY_PROMPT_TEMPLATE'] = assembled_reclassify
    except Exception as e:
        raise RuntimeError(f"Fatal: Failed to assemble prompt templates: {e}")

    # Inject generated CSS into the config dictionary for templates to use
    cfg["theme_css"] = generate_theme_css(cfg)
    return cfg

_domain_config = load_domain_config()

PROMPT_TEMPLATE = _domain_config.get('PROMPT_TEMPLATE')
VERIFIER_TEMPLATE = _domain_config.get('VERIFIER_TEMPLATE')
RECLASSIFY_PROMPT_TEMPLATE = _domain_config.get('RECLASSIFY_PROMPT_TEMPLATE')

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

# --- Performance Logging ---
PERFORMANCE_LOG_FILE = os.path.join(DATA_DIR, 'performance_log.jsonl')

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

# --- LLM & Utility Functions ---
def get_set_data(paper_data, set_num):
    prefix = f'set_{set_num}_last_llm_'
    data = {}
    for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', 'relevance', 'verified', 'estimated_score']:
        data[field] = paper_data.get(f'{prefix}{field}')
    
    features_str = paper_data.get(f'{prefix}features')
    technique_str = paper_data.get(f'{prefix}technique')
    try:
        data['features'] = json.loads(features_str) if features_str else {}
    except Exception:
        data['features'] = {}
    try:
        data['technique'] = json.loads(technique_str) if technique_str else {}
    except Exception:
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
        # vLLM requests may take hours to complete and should not be discarded. 
        # This is by design, Do NOT reduce this timeout.
        response = requests.post(chat_url, headers=headers, json=payload, timeout=7200)
        
        if is_shutdown_flag_set():
            return None, None, None
            
        response.raise_for_status()
        response_data = response.json()
        model_name_from_response = response_data.get('model', model_name)
        
        if response_data.get('choices'):
            message = response_data['choices'][0]['message']
            reasoning_content_raw = message.get('reasoning', '')
            if reasoning_content_raw is None or reasoning_content_raw == '':
                reasoning_content_raw = message.get('reasoning_content', '')
                
            reasoning_content = reasoning_content_raw.strip() if reasoning_content_raw else ''
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
        error_msg = f"Connection Error: Could not connect to LLM server at {server_url_base}. {e!s}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except requests.exceptions.Timeout as e:
        error_msg = f"Timeout Error: LLM server did not respond within the timeout period. {e!s}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Request Error: {e!s}"
        if hasattr(e, 'response') and e.response:
            error_msg += f"\nResponse Text: {e.response.text}"
        print(f"Error sending {context}request to LLM server: {error_msg}")
        return None, model_name, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"JSON Decode Error: {e!s}"
        if 'response' in locals():
            error_msg += f"\nResponse Text: {response.text}"
        print(f"Error decoding JSON {context}response: {error_msg}")
        return None, model_name, error_msg
    except Exception as e:
        error_msg = f"Unexpected Error: {type(e).__name__}: {e!s}"
        print(f"Error during {context}LLM request: {error_msg}")
        return None, model_name, error_msg


# Load domain config once at module level to derive required fields
_domain_config = load_domain_config()

# --- User-editable prompt template discovery (backup/restore) ---
USER_PROMPT_TEMPLATE_KEYS = (
    (
        "classify_instructions",
        os.path.join("prompt_templates", "configurable_classify_instructions.txt"),
    ),
    (
        "classify_output_template",
        os.path.join("prompt_templates", "configurable_classify_output_template.txt"),
    ),
    (
        "few_shot_examples",
        os.path.join("prompt_templates", "configurable_few_shot_examples.txt"),
    ),
)


def get_user_prompt_template_paths(domain_cfg=None):
    """
    Returns absolute paths of the user-editable prompt fragments.

    These are the configurable pieces injected into the fixed base templates.
    The base templates themselves are intentionally excluded.
    """
    cfg = domain_cfg if isinstance(domain_cfg, dict) else _domain_config
    prompts_cfg = (cfg or {}).get("prompts", {}) or {}

    paths = {}
    for key, default_relpath in USER_PROMPT_TEMPLATE_KEYS:
        relpath = prompts_cfg.get(key, default_relpath)
        paths[key] = os.path.abspath(os.path.join(BASE_DIR, relpath))

    return paths

# --- Trace review (free-form meta-analysis) ---
# Fixed system template. Deliberately NOT part of assemble_prompt_templates /
# domain-config assembly. Loaded on demand and filled at request time.
TRACE_REVIEW_BASE_TEMPLATE_PATH = os.path.join(
    BASE_DIR, 'prompt_templates', 'base_templates', 'trace_review_base_template.txt'
)

def load_trace_review_base_template():
    return _load_text_file(TRACE_REVIEW_BASE_TEMPLATE_PATH)

def get_classify_prompt_fragments():
    """Returns (classify_instructions_text, classify_output_template_text) for the current domain config."""
    prompts_cfg = _domain_config.get('prompts', {}) or {}
    inst_path = os.path.join(BASE_DIR, prompts_cfg.get('classify_instructions', 'prompt_templates/configurable_classify_instructions.txt'))
    tmpl_path = os.path.join(BASE_DIR, prompts_cfg.get('classify_output_template', 'prompt_templates/configurable_classify_output_template.txt'))
    return _load_text_file(inst_path), _load_text_file(tmpl_path)

def get_required_classification_fields():
    fields = set()
    # 1. Universal inferred fields (hardcoded by design)
    fields.add('is_offtopic')
    fields.add('relevance')
    
    # 2. Domain-specific fields dynamically extracted from YAML
    for field in _domain_config.get('editable_fields', []):
        path = field.get('json_path', '')
        if path:
            fields.add(path.split('.')[0]) # Extract top-level key
            
    for group in _domain_config.get('groups', []):
        path = group.get('json_path', '')
        if path:
            fields.add(path.split('.')[0]) # Extract top-level key
            
    return list(fields)

# --- Tri-state boolean validation -----------------------------------------
# A boolean field may be answered in many spellings of true/false, or as an
# explicit "don't know" (null). Anything else ("2", "maybe", 7, a list, ...)
# is an unusable answer and is rejected so the run is retried.
# _TRUE_STRINGS/_FALSE_STRINGS mirror shared/db.py's _BOOL_TRUE/_BOOL_FALSE
# (case is folded here); keep them in sync if you extend either.

_TRUE_STRINGS  = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}
_NULL_STRINGS  = {"", "null", "none", "unknown"}

def _tri_state_verdict(value):
    """Classify an LLM answer for a boolean field -> 'true'/'false'/'null'/'unusable'."""
    if value is True:  return "true"
    if value is False: return "false"
    if value is None:  return "null"                 # third state, NOT cast to False
    if isinstance(value, (int, float)):              # bool already handled above
        if value == 1: return "true"
        if value == 0: return "false"
        return "unusable"                            # 2, 7, 0.5, ...
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE_STRINGS:  return "true"
        if s in _FALSE_STRINGS: return "false"
        if s in _NULL_STRINGS:  return "null"
        return "unusable"                            # "maybe", "2", "mostly", ...
    return "unusable"                                # list, dict, ...

def _get_path(d, path):
    cur = d
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur

def _has_path(d, path):
    """Distinguish 'present-but-null' (valid) from 'absent'."""
    cur, keys = d, path.split(".")
    for key in keys[:-1]:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return False
    return isinstance(cur, dict) and keys[-1] in cur

# Export these for the dispatcher and history renderer
REQUIRED_CLASSIFICATION_FIELDS = get_required_classification_fields()
REQUIRED_VERIFIER_FIELDS = ['verified', 'estimated_score']

def get_boolean_classification_fields():
    """JSON paths declared boolean (tri-state) by the domain config.
    Mirrors meta.agreement_core.discover_boolean_fields exactly, so
    write-time normalization and read-time voting can never drift apart.
    Text-presence fields are excluded."""
    fields = ['is_offtopic']
    for group in _domain_config.get('groups', []):
        ft = group.get('filter_type')
        if ft == 'tri_state':
            path = group.get('json_path', '')
            if path and path not in fields:
                fields.append(path)
        elif ft in ('inclusion', 'none'):
            parent = group.get('json_path', '') or ''
            for fdef in group.get('fields', []):
                if fdef.get('render_type') == 'text_presence':
                    continue
                key = fdef.get('key', '')
                if not key:
                    continue
                full_path = f"{parent}.{key}" if parent else key
                if full_path not in fields:
                    fields.append(full_path)
    return fields


_BOOL_STRINGS = ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off')

def validate_llm_output(llm_data, task_type):
    """
    Unified validation for all LLM outputs.
    Returns: (is_valid: bool, invalid_reason: str or None)

    Field classes:
      * Universal mandatory fields (is_offtopic, relevance, verified,
        estimated_score) require a decisive answer: null is INVALID, and
        unusable values ("2", "maybe", ...) are INVALID -> retry.
      * Domain boolean fields are TRI-STATE: any true/false/null spelling is
        accepted (null = legitimate "unknown"), unusable values are INVALID.
    """
    if not isinstance(llm_data, dict):
        return False, "Output is not a dictionary"

    required = REQUIRED_VERIFIER_FIELDS if task_type == 'verify' else get_required_classification_fields()
    missing = [f for f in required if f not in llm_data]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    if task_type == 'verify':
        # verified: mandatory boolean decision (null not allowed)
        v = llm_data.get('verified')
        verdict = _tri_state_verdict(v)
        if verdict == 'unusable':
            return False, f"Field 'verified' answered {v!r}, which is neither true nor false"
        if verdict == 'null':
            return False, "Field 'verified' is required and must not be null"
        # estimated_score: mandatory number (null not allowed)
        s = llm_data.get('estimated_score')
        if isinstance(s, bool) or s is None:
            return False, "Field 'estimated_score' is required and must be a number"
        try:
            float(s)
        except (TypeError, ValueError):
            return False, f"Field 'estimated_score' must be a number, got {s!r}"
        return True, None

    # ---- classify ----
    # is_offtopic: mandatory boolean (null and unusable both invalid)
    iso = llm_data.get('is_offtopic')
    iso_verdict = _tri_state_verdict(iso)
    if iso_verdict == 'unusable':
        return False, f"Field 'is_offtopic' answered {iso!r}, which is neither true nor false"
    if iso_verdict == 'null':
        return False, "Field 'is_offtopic' is required and must not be null"

    # relevance: mandatory number (null and non-numeric both invalid)
    rel = llm_data.get('relevance')
    if isinstance(rel, bool) or rel is None:
        return False, "Field 'relevance' is required and must be a number"
    try:
        float(rel)
    except (TypeError, ValueError):
        return False, f"Field 'relevance' must be a number, got {rel!r}"

    # Domain boolean fields: tri-state (accept true/false/null, reject unusable)
    for path in get_boolean_classification_fields():
        if path == 'is_offtopic':
            continue                       # already enforced as mandatory above
        if not _has_path(llm_data, path):
            continue                       # absent domain field == unknown, acceptable
        value = _get_path(llm_data, path)
        if _tri_state_verdict(value) == 'unusable':
            return False, f"Field '{path}' answered {value!r}, which is neither true, false, nor null"

    return True, None

def reload_domain_config():
    """Reloads the domain configuration from disk and updates all global references."""
    global _domain_config, PROMPT_TEMPLATE, VERIFIER_TEMPLATE, RECLASSIFY_PROMPT_TEMPLATE, REQUIRED_CLASSIFICATION_FIELDS
    
    # 1. Reload from disk
    _domain_config = load_domain_config()
    
    # 2. Update global prompt paths
    PROMPT_TEMPLATE = _domain_config.get('PROMPT_TEMPLATE')
    VERIFIER_TEMPLATE = _domain_config.get('VERIFIER_TEMPLATE')
    RECLASSIFY_PROMPT_TEMPLATE = _domain_config.get('RECLASSIFY_PROMPT_TEMPLATE')
    
    # 3. Recalculate required fields for validation
    REQUIRED_CLASSIFICATION_FIELDS = get_required_classification_fields()
    
    # 4. Patch the cached domain_config in web.routes_ui if it has been imported
    import sys
    if 'web.routes_ui' in sys.modules:
        sys.modules['web.routes_ui'].domain_config = _domain_config