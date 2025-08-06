LLM_SERVER_URL = "http://localhost:8080/v1/chat/completions" # Default endpoint
MAX_CONCURRENT_WORKERS = 18 # Match your server slots

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

