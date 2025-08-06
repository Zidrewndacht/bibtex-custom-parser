import requests
import json
import sqlite3

# BIBTEX_FILE = "all.bib" # não implementado em import_bibtex

# LLM_SERVER_URL = "http://localhost:8080/v1/chat/completions" # Default endpoint
LLM_SERVER_URL = "http://localhost:8080" # Default endpoint

MAX_CONCURRENT_WORKERS = 24 # Match your server slots
DATABASE_FILE = "all.sqlite"
GRAMMAR_FILE = "output.gbnf"
PROMPT_TEMPLATE = "prompt_template.txt"
VERIFIER_TEMPLATE = "verifier_template.txt"

# Define default JSON structures for features and technique
DEFAULT_FEATURES = {
    "solder": None,
    "polarity": None,
    "wrong_component": None,
    "missing_component": None,
    "tracks": None,
    "holes": None,
    "other": None
}
DEFAULT_TECHNIQUE = {
    "classic_computer_graphics_based": None,
    "machine_learning_based": None,
    "hybrid": None,
    "model": None,
    "available_dataset": None
}

# mover para client-side?
# --- Define emoji mapping for publication types ---
TYPE_EMOJIS = {
    'article': '📄',        # Page facing up
    'inproceedings': '📚',  # Books (representing conference proceedings)
    'incollection': '📖',   # Open book (representing book chapters/collections)
    'inbook': '📘',         # Blue book
    'phdthesis': '🎓',      # Graduation cap
    'mastersthesis': '🎓',  # Graduation cap (using the same for simplicity)
    'techreport': '📋',     # Clipboard
    'misc': '📁',           # File folder
}
# Default emoji for unknown types
DEFAULT_TYPE_EMOJI = '📄' # Using article as default


#usado por automate and verify:
def get_model_alias(server_url_base):
    """Fetches the model alias from the LLM server's /v1/models endpoint."""
    models_url = f"{server_url_base.rstrip('/')}/v1/models"
    headers = {"Content-Type": "application/json"}

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


#usado por automate and verify:
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
