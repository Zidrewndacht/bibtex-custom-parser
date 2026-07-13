# queue/logging_utils.py
import json
import os
from datetime import datetime, timezone
from colorama import init, Fore, Style

init(autoreset=True)

# ============================================================================
# FILE LOGGING (Append-only JSON lines, separate files by category)
# ============================================================================

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _log_to_file(filename: str, **fields):
    """Append a single-line JSON log entry. Thread-safe for append-only writes."""
    try:
        filepath = os.path.join(LOG_DIR, filename)
        entry = {"_ts": datetime.now(timezone.utc).isoformat(), **fields}
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass  # Never let logging failures crash the app

# Category-specific wrappers for clarity
def log_file_dispatch(task_id, task_type, paper_id, set_num):
    _log_to_file('dispatcher.log', event='dispatch', task_id=task_id, task_type=task_type, paper_id=paper_id, set_num=set_num)

def log_file_complete(task_id, task_type, success, model_name=None, error=None):
    _log_to_file('tasks.log', event='complete', task_id=task_id, task_type=task_type, success=success, model_name=model_name, error=error)

def log_file_error(context, error, task_id=None, paper_id=None, set_num=None):
    _log_to_file('errors.log', event='error', context=context, error=str(error), task_id=task_id, paper_id=paper_id, set_num=set_num)

def log_file_request(endpoint, client, mode, paper_id=None):
    _log_to_file('requests.log', event='request', endpoint=endpoint, client=client, mode=mode, paper_id=paper_id)

def log_file_queue_status(queue_size, total_in_flight, classify, verify, reclassify, mode):
    _log_to_file('dispatcher.log', event='queue_status', queue_size=queue_size, in_flight_total=total_in_flight, in_flight_classify=classify, in_flight_verify=verify, in_flight_reclassify=reclassify, mode=mode)

# ============================================================================
# COLOR CONSTANTS FOR LOGGING (black-background friendly - LIGHT COLORS ONLY)
# ============================================================================
class Colors:
    """Semantic colors for log prefixes and mode words only.
    
    ALL colors use LIGHT*_EX variants for visibility on black backgrounds.
    No deep/dark/saturated colors (e.g., Fore.BLUE, Fore.RED) are used.
    """
    # Prefix labels - bright/light colors only
    DISPATCHER = Fore.LIGHTCYAN_EX
    REQUEST = Fore.LIGHTYELLOW_EX
    VLLM_SEND = Fore.LIGHTGREEN_EX
    VLLM_COMPLETE = Fore.LIGHTGREEN_EX
    ERROR = Fore.LIGHTRED_EX          # Light red, not deep red
    QUEUE_STATUS = Fore.LIGHTBLUE_EX  # Light blue, NOT Fore.BLUE
    CLASSIFY = Fore.LIGHTGREEN_EX
    VERIFY = Fore.LIGHTMAGENTA_EX     # Light magenta, not deep
    CONSENSUS = Fore.LIGHTCYAN_EX
    BATCH = Fore.LIGHTYELLOW_EX
    DB = Fore.LIGHTBLUE_EX
    
    # Mode words - light colors only
    MODE_CLASSIFY = Fore.LIGHTGREEN_EX
    MODE_VERIFY = Fore.LIGHTMAGENTA_EX
    MODE_RECLASSIFY = Fore.LIGHTCYAN_EX
    MODE_CONSENSUS = Fore.LIGHTCYAN_EX
    MODE_ID = Fore.LIGHTWHITE_EX
    MODE_ALL = Fore.LIGHTWHITE_EX
    MODE_REMAINING = Fore.LIGHTWHITE_EX
    MODE_NO_FEATURES = Fore.LIGHTWHITE_EX
    MODE_ON_TOPIC = Fore.LIGHTWHITE_EX
    
    # Queue status mode keywords - color only the mode word itself
    MODE_QUEUE_MIXED = Fore.LIGHTWHITE_EX
    MODE_QUEUE_HOMOGENEOUS_CLASSIFY = Fore.LIGHTGREEN_EX
    MODE_QUEUE_HOMOGENEOUS_VERIFY = Fore.LIGHTMAGENTA_EX
    MODE_QUEUE_HOMOGENEOUS_RECLASSIFY = Fore.LIGHTCYAN_EX
    # Timestamp - subtle but still readable: white at lower intensity
    TIMESTAMP = Fore.LIGHTBLACK_EX  # Or keep LIGHTBLACK_EX if your terminal renders it well


def _color_prefix(prefix: str, color: str) -> str:
    """Color only the prefix word (e.g., 'DISPATCH:') not the whole line."""
    return f"{color}{prefix}{Style.RESET_ALL}"

def _color_queue_mode(status_line: str) -> str:
    """Color only the queue mode keyword in status lines like:
    """
    if status_line.startswith("HOMOGENEOUS_CLASSIFY"):
        return f"{Colors.MODE_QUEUE_HOMOGENEOUS_CLASSIFY}HOMOGENEOUS_CLASSIFY{Style.RESET_ALL}" + status_line[len("HOMOGENEOUS_CLASSIFY"):]
    elif status_line.startswith("HOMOGENEOUS_VERIFY"):
        return f"{Colors.MODE_QUEUE_HOMOGENEOUS_VERIFY}HOMOGENEOUS_VERIFY{Style.RESET_ALL}" + status_line[len("HOMOGENEOUS_VERIFY"):]
    elif status_line.startswith("HOMOGENEOUS_RECLASSIFY"):
        return f"{Colors.MODE_QUEUE_HOMOGENEOUS_RECLASSIFY}HOMOGENEOUS_RECLASSIFY{Style.RESET_ALL}" + status_line[len("HOMOGENEOUS_RECLASSIFY"):]
    elif status_line.startswith("MIXED"):
        return f"{Colors.MODE_QUEUE_MIXED}MIXED{Style.RESET_ALL}" + status_line[len("MIXED"):]
    else:
        return status_line  # Fallback: return unchanged
    
def _color_mode(mode: str) -> str:
    """Color the mode word value itself based on semantic meaning."""
    mode_map = {
        'classify': Colors.MODE_CLASSIFY,
        'verify': Colors.MODE_VERIFY,
        'reclassify': Colors.MODE_RECLASSIFY,
        'consensus': Colors.MODE_CONSENSUS,
        'id': Colors.MODE_ID,
        'all': Colors.MODE_ALL,
        'remaining': Colors.MODE_REMAINING,
        'no_features': Colors.MODE_NO_FEATURES,
        'on_topic_implementation': Colors.MODE_ON_TOPIC,
    }
    color = mode_map.get(mode, Fore.LIGHTWHITE_EX)
    return f"{color}{mode}{Style.RESET_ALL}"

def log(msg: str):
    """Print timestamped message to console."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    timestamp_part = f"{Colors.TIMESTAMP}[{timestamp}]{Style.RESET_ALL}"
    print(f"{timestamp_part} {msg}", flush=True)