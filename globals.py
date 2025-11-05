# globals.py
# **** This *has to be updated* when features or techniques change 
# See DEFAULT_FEATURES and DEFAULT_TECHNIQUE below. ****

import requests
import json
import sqlite3
import re
import threading
import os

LLM_SERVER_URL = "http://localhost:8086"
MAX_CONCURRENT_WORKERS = 256 # vLLM go brrr
MAX_CONCURRENT_WORKERS_VERIFY = 480 # vLLM go brrr
MAX_CONCURRENT_WORKERS_CONSENSUS = 96 # vLLM go brrr


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_TEMPLATES_DIR = os.path.join(BASE_DIR, 'prompt_templates')

# Update the paths
PROMPT_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'classify_template.txt') # Replace with your actual filename
VERIFIER_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'verify_template.txt') # Replace with your actual filename
RECLASSIFY_PROMPT_TEMPLATE = os.path.join(PROMPT_TEMPLATES_DIR, 'reclassify_template.txt') # Replace with your actual filename

# Optional API key support
LLM_API_KEY = None

DATABASE_FILE = os.path.join(os.getcwd(), 'data', 'db.sqlite')
os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)  # Ensure the directory exists

PDF_STORAGE_DIR = os.path.join(os.getcwd(), 'data', 'pdf')
os.makedirs(PDF_STORAGE_DIR, exist_ok=True) # Ensure the directory exists

ANNOTATED_PDF_STORAGE_DIR = os.path.join(os.getcwd(), 'data', 'pdf_annotated')
os.makedirs(ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)

# Define default JSON structures for features and technique
DEFAULT_FEATURES = {
    "tracks": None,
    "holes": None,
    "bare_pcb_other": None,         #new
    "solder_insufficient": None,
    "solder_excess": None,
    "solder_void": None,
    "solder_crack": None,
    "solder_other": None,           #new
    "orientation": None,
    "wrong_component": None,
    "missing_component": None,
    "component_other": None,        #new
    "cosmetic": None,
    "other": None   #text
}
BOOLEAN_FEATURE_KEYS = [    # for no_features re-classification
    "tracks",
    "holes",
    "bare_pcb_other",
    "solder_insufficient",
    "solder_excess",
    "solder_void",
    "solder_crack",
    "solder_other",
    "orientation",
    "wrong_component",
    "missing_component",
    "component_other",
    "cosmetic"
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
    "model": None,   #text
    "available_dataset": None  
}

# mover para client-side?
# --- Define emoji mapping for publication types ---
TYPE_EMOJIS = {
    'article': '📄',        # Page facing up
    'inproceedings': '📚',  # Books (representing conference proceedings)
    'incollection': '📖',   # Open book (representing book chapters/collections)
    'book': '📘',         # Blue book
    'phdthesis': '🎓',      # Graduation cap
    'mastersthesis': '🎓',  # Graduation cap (using the same for simplicity)
    'techreport': '📋',     # Clipboard
    'misc': '📁',           # File folder
}
# Default emoji for unknown types
DEFAULT_TYPE_EMOJI = '📄' # Using article as default

PDF_EMOJIS = {
    'PDF': '📕',        
    'annotated': '📗',
    'paywalled': '💰',
    'none': '❔'
}

# --- Global Shutdown Flag for Instant Shutdown (using Lock for atomicity) ---
# This provides a common mechanism for scripts to handle Ctrl+C gracefully.
shutdown_lock = threading.Lock()
shutdown_flag = False

def set_shutdown_flag():
    """Sets the global shutdown flag to True in a thread-safe manner."""
    global shutdown_flag
    with shutdown_lock:
        shutdown_flag = True

def is_shutdown_flag_set():
    """Checks the global shutdown flag in a thread-safe manner."""
    global shutdown_flag
    with shutdown_lock:
        return shutdown_flag

def signal_handler(sig, frame):
    """Standard signal handler for SIGINT (Ctrl+C). Sets shutdown flag and forces exit."""
    print("\nReceived Ctrl+C. Killing all threads...")
    set_shutdown_flag()
    # Use os._exit for immediate shutdown across all threads
    os._exit(1)
    
#usados por automate and verify:
def get_model_alias(server_url_base):
    """Fetches the model alias from the LLM server's /v1/models endpoint."""
    models_url = f"{server_url_base.rstrip('/')}/v1/models"
    headers = {"Content-Type": "application/json"}
    
    # Add authorization header if API key is provided
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        response = requests.get(models_url, headers=headers, timeout=30)
        response.raise_for_status()
        models_data = response.json()

        # Simplified model alias detection
        if models_data and isinstance(models_data.get('data'), list) and models_data['data']:
            model_alias = models_data['data'][0].get('id')
            if model_alias:
                print(f"Detected model alias: '{model_alias}'")
                return model_alias

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to LLM server: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response Text: {e.response.text}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        if 'response' in locals():
            print(f"Response Text: {response.text}")

    fallback_alias = "Unknown_LLM"
    print(f"Using fallback model alias: '{fallback_alias}'")
    return fallback_alias

def load_prompt_template(template_path):
    """Loads the prompt template from a file."""
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
    """Fetches a single paper's data from the database by its ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def send_prompt_to_llm(prompt_text, server_url_base=None, model_name="default", is_verification=False):
    """
    Sends a prompt to the LLM via the OpenAI-compatible API. 
    Returns (content_str, model_name_used, reasoning_trace).
    Supports both separate reasoning_content field and <think></think> tags in content.
    """
    if server_url_base is None:
        server_url_base = LLM_SERVER_URL  # Now this will work
    
    chat_url = f"{server_url_base.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    
    # Add authorization header if API key is provided
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    
    payload = { #official recommended parameters from Qwen3 - Temperature=0.6 for Qwwen3-thinking, 1.0 for Qwen3VL-thinking
        "model": model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.6, 
        "top_p": 0.95, 
        "top_k": 20, 
        "min_p": 0,
        "max_tokens": 32768,
        "stream": False
    }
    context = "verification " if is_verification else ""
    
    try:
        if is_shutdown_flag_set():
            return None, None, None
        response = requests.post(chat_url, headers=headers, json=payload, timeout=1800) #30 minutes as the inference engine may have a long queue during batch processing.
        if is_shutdown_flag_set():
            return None, None, None
        response.raise_for_status()
        response_data = response.json()
        
        model_name_from_response = response_data.get('model', model_name)
        if 'choices' in response_data and response_data['choices']:
            # Extract reasoning_content safely
            reasoning_content = None
            message = response_data['choices'][0]['message']
            
            # First, try to get reasoning_content from the structured field (for sane inference engines)
            reasoning_content_raw = message.get('reasoning_content', '')
            if reasoning_content_raw is not None and reasoning_content_raw != '':
                reasoning_content = reasoning_content_raw.strip()
            else:
                reasoning_content = ''
                
            content_raw = message.get('content', '')
            if content_raw is not None:
                content = content_raw.strip()
            else:
                content = ''
            
            # If no separate reasoning_content was found, check for <think></think> tags in content
            if not reasoning_content and content:
                # Look for <think>...</think> pattern
                think_pattern = r'<think>(.*?)</think>'
                think_matches = re.findall(think_pattern, content, re.DOTALL | re.IGNORECASE)
                
                if think_matches:
                    # Extract the reasoning content from the first <think> tag
                    reasoning_content = think_matches[0].strip()
                    
                    # Remove the <think>...</think> section from the main content
                    content = re.sub(think_pattern, '', content, flags=re.DOTALL | re.IGNORECASE).strip()
                    # Clean up any extra whitespace that might remain
                    content = re.sub(r'\n\s*\n', '\n\n', content)  # Normalize multiple newlines
                    content = content.strip()
            
            return content, model_name_from_response, reasoning_content
        else:
            print(f"Warning: Unexpected LLM {context}response structure: {response_data}")
            return None, model_name_from_response, None
    except requests.exceptions.RequestException as e:
        if is_shutdown_flag_set():
            return None, None, None
        print(f"Error sending {context}request to LLM server: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response Text: {e.response.text}")
        return None, None, None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON {context}response: {e}")
        if 'response' in locals():
            print(f"Response Text: {response.text}")
        return None, None, None
    except KeyError as e:
        print(f"Unexpected {context}response structure, missing key: {e}")
        print(f"Response Data: {response_data}")
        return None, None, None