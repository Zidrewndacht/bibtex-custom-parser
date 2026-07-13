# queue_manager.py
"""
Queue Manager - Flask HTTP server for LLM classification/verification.
Single dispatcher thread, callback-driven state machines, no blocking.
"""

import json
import threading
import signal
from datetime import datetime, timezone
from collections import deque
import os 
import sys
import globals
import time
from flask import Flask, request, jsonify
import db

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

# ============================================================================
# CONFIGURATION
# ============================================================================

# Task types
TASK_CLASSIFY = "classify"
TASK_VERIFY = "verify"
TASK_RECLASSIFY = "reclassify"

# Flask app
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False  # Preserve key order in responses

# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log(msg: str):
    """Print timestamped message to console. Message may contain pre-colored segments."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # Timestamp darker but still readable on black
    timestamp_part = f"{Colors.TIMESTAMP}[{timestamp}]{Style.RESET_ALL}"
    print(f"{timestamp_part} {msg}", flush=True)


def log_queue_status():
    """Log current queue and in-flight status."""
    total_in_flight = state.get_total_in_flight()
    classify_in_flight = state.get_in_flight(TASK_CLASSIFY)
    verify_in_flight = state.get_in_flight(TASK_VERIFY)
    reclassify_in_flight = state.get_in_flight(TASK_RECLASSIFY)
    queue_size = len(state.task_queue)
    
    # Determine current mode
    if classify_in_flight == total_in_flight and classify_in_flight > 0:
        mode = f"HOMOGENEOUS_CLASSIFY (limit={globals.MAX_CONCURRENT_WORKERS_CLASSIFY})"
    elif verify_in_flight == total_in_flight and verify_in_flight > 0:
        mode = f"HOMOGENEOUS_VERIFY (limit={globals.MAX_CONCURRENT_WORKERS_VERIFY})"
    elif reclassify_in_flight == total_in_flight and reclassify_in_flight > 0:
        mode = f"HOMOGENEOUS_RECLASSIFY (limit={globals.MAX_CONCURRENT_WORKERS_RECLASSIFY})"
    else:
        mode = f"MIXED (min_threshold={globals.MIN_CONCURRENT_WORKERS})"
        
    # Color only the mode keyword, not the whole line
    log(f"{_color_prefix('QUEUE STATUS:', Colors.QUEUE_STATUS)} queue_size={queue_size} \t in_flight={total_in_flight} \t classify={classify_in_flight} \t verify={verify_in_flight} \t reclassify={reclassify_in_flight} \t mode={_color_queue_mode(mode)}")
    log_file_queue_status(queue_size, total_in_flight, classify_in_flight, verify_in_flight, reclassify_in_flight, mode)
# ============================================================================
# QUEUE STATE (Thread-Safe)
# ============================================================================

class QueueState:
    def __init__(self):
        self.lock = threading.Lock()
        self.task_queue = deque()
        self.in_flight = {TASK_CLASSIFY: 0, TASK_VERIFY: 0, TASK_RECLASSIFY: 0}
        self.completion_event = threading.Event()
        self.completion_event.set()  # Start set so dispatcher doesn't block on empty queue
        self.shutdown = False
    
    def enqueue(self, task):
        with self.lock:
            self.task_queue.append(task)
        self.completion_event.set()  # Wake dispatcher
    
    def peek_queue(self):
        with self.lock:
            return self.task_queue[0] if self.task_queue else None
    
    def dequeue(self):
        with self.lock:
            return self.task_queue.popleft() if self.task_queue else None
    
    def increment_in_flight(self, task_type):
        with self.lock:
            self.in_flight[task_type] += 1
    
    def decrement_in_flight(self, task_type):
        with self.lock:
            self.in_flight[task_type] -= 1
        self.completion_event.set()  # CRITICAL: Wake dispatcher on ANY completion
    
    def get_total_in_flight(self):
        with self.lock:
            return sum(self.in_flight.values())
    
    def get_in_flight(self, task_type):
        with self.lock:
            return self.in_flight[task_type]
    
    def request_shutdown(self):
        self.shutdown = True
        self.completion_event.set()
    
    def is_shutdown(self):
        return self.shutdown

state = QueueState()

# ============================================================================
# STATE MACHINES
# ============================================================================
class ClassificationStateMachine:
    """State machine for classifying a SINGLE set of a single paper."""
    def __init__(self, paper_id, set_num, prompt_template, model_alias):
        self.paper_id = paper_id
        self.set_num = set_num
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.completion_callback = None
        self.lock = threading.Lock()

    def get_prompts(self):
        """Generate exactly 1 classification task for this specific paper/set."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return []
            
        task = {
            'task_type': TASK_CLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_classify",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'prompt': self.prompt_template.format(
                title=paper.get('title', ''),
                abstract=paper.get('abstract', ''),
                keywords=paper.get('keywords', ''),
                authors=paper.get('authors', ''),
                year=paper.get('year', ''),
                type=paper.get('type', ''),
                journal=paper.get('journal', '')
            ),
            'state_machine': self
        }
        return [task]

    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when this single set classification completes."""
        if success and llm_data:
            db.update_set_cache(self.paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
            db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Classify_Set{set_num}")
        else:
            db.update_set_log_only(self.paper_id, set_num, "classifier", model_name, reasoning_trace, json_result, valid=False)
            
        if self.completion_callback:
            self.completion_callback(self.paper_id, set_num, success)


class VerificationStateMachine:
    """State machine for verifying a SINGLE set of a single paper."""
    def __init__(self, paper_id, set_num, prompt_template, model_alias):
        self.paper_id = paper_id
        self.set_num = set_num
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.completion_callback = None
        self.lock = threading.Lock()

    def get_prompts(self):
        """Generate exactly 1 verification task for this specific paper/set."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return []
            
        prefix = f'set_{self.set_num}_last_llm_'
        format_data = {
            'title': paper.get('title', ''),
            'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            'relevance': paper.get(f'{prefix}relevance'),
            'research_area': paper.get('research_area', ''),
        }
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            db_val = paper.get(f'{prefix}{field}')
            format_data[field] = True if db_val == 1 else (False if db_val == 0 else None)
            
        features_str = paper.get(f'{prefix}features')
        technique_str = paper.get(f'{prefix}technique')
        try:
            format_data['features'] = json.loads(features_str) if features_str else {}
        except:
            format_data['features'] = {}
        try:
            format_data['technique'] = json.loads(technique_str) if technique_str else {}
        except:
            format_data['technique'] = {}
            
        task = {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_verify",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'prompt': self.prompt_template.format(**format_data),
            'state_machine': self
        }
        return [task]

    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when this single set verification completes."""
        if success and llm_data:
            db.update_set_verifier(self.paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
            db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Verify_Set{set_num}")
        else:
            db.update_set_log_only(self.paper_id, set_num, "verifier", model_name, reasoning_trace, json_result, valid=False)
            
        if self.completion_callback:
            self.completion_callback(self.paper_id, set_num, success)


class ConsensusStateMachine:
    """State machine for classify-until-consensus on a single paper/set."""
    def __init__(self, paper_id, set_num, classify_template, verify_template, reclassify_template, model_alias):
        self.paper_id = paper_id
        self.set_num = set_num
        self.classify_template = classify_template
        self.verify_template = verify_template
        self.reclassify_template = reclassify_template
        self.model_alias = model_alias
        self.iteration = 0
        self.max_iterations = globals.MAX_CONSENSUS_ITERATIONS
        self.fresh_fallback = globals.FRESH_CLASSIFY_FALLBACK_ITERATION
        self.current_task_type = None
        self.completion_callback = None
        self.lock = threading.Lock()

    def get_next_task(self):
        """Determine next task based on current paper state."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return None
            
        if self.iteration >= self.max_iterations:
            return None
            
        prefix = f'set_{self.set_num}_last_llm_'
        verified = paper.get(f'{prefix}verified')
        score = paper.get(f'{prefix}estimated_score')
        
        if paper.get(f'{prefix}is_offtopic') is None:
            self.current_task_type = TASK_CLASSIFY
            return self._create_classify_task(paper)
        elif verified is None:
            self.current_task_type = TASK_VERIFY
            return self._create_verify_task(paper)
        elif verified == 0 or (score is not None and score <= 7):
            self.iteration += 1
            if self.iteration == self.fresh_fallback:
                self.current_task_type = TASK_CLASSIFY
                return self._create_classify_task(paper)
            else:
                self.current_task_type = TASK_RECLASSIFY
                return self._create_reclassify_task(paper)
        else:
            return None

    def _create_classify_task(self, paper):
        return {
            'task_type': TASK_CLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_classify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'prompt': self.classify_template.format(
                title=paper.get('title', ''),
                abstract=paper.get('abstract', ''),
                keywords=paper.get('keywords', ''),
                authors=paper.get('authors', ''),
                year=paper.get('year', ''),
                type=paper.get('type', ''),
                journal=paper.get('journal', '')
            ),
            'state_machine': self
        }

    def _create_verify_task(self, paper):
        """Create verification task for consensus state machine."""
        prefix = f'set_{self.set_num}_last_llm_'
        format_data = {
            'title': paper.get('title', ''),
            'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            'relevance': paper.get(f'{prefix}relevance'),
            'research_area': paper.get('research_area', ''),
        }
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            db_val = paper.get(f'{prefix}{field}')
            format_data[field] = True if db_val == 1 else (False if db_val == 0 else None)
            
        features_str = paper.get(f'{prefix}features')
        technique_str = paper.get(f'{prefix}technique')
        try:
            format_data['features'] = json.loads(features_str) if features_str else {}
        except:
            format_data['features'] = {}
        try:
            format_data['technique'] = json.loads(technique_str) if technique_str else {}
        except:
            format_data['technique'] = {}
            
        return {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_verify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'prompt': self.verify_template.format(**format_data),
            'state_machine': self
        }

    def _create_reclassify_task(self, paper):
        """Create reclassification task for consensus state machine."""
        prefix = f'set_{self.set_num}_last_llm_'
        classification_data = {}
        bool_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
        for field in bool_fields:
            db_val = paper.get(f'{prefix}{field}')
            if db_val == 1:
                classification_data[field] = True
            elif db_val == 0:
                classification_data[field] = False
            else:
                classification_data[field] = None
                
        classification_data['research_area'] = paper.get('research_area')
        classification_data['relevance'] = paper.get(f'{prefix}relevance')
        
        features_str = paper.get(f'{prefix}features')
        technique_str = paper.get(f'{prefix}technique')
        try:
            classification_data['features'] = json.loads(features_str) if features_str else {}
        except:
            classification_data['features'] = {}
        try:
            classification_data['technique'] = json.loads(technique_str) if technique_str else {}
        except:
            classification_data['technique'] = {}
            
        latest_classifier_trace = ''
        latest_verifier_trace = ''
        try:
            llm_log_str = paper.get('llm_log', '[]')
            llm_log = json.loads(llm_log_str) if llm_log_str else []
            for entry in reversed(llm_log):
                if entry.get('type') in ['classifier', 'consensus', 'averaged_llm'] and entry.get('valid'):
                    latest_classifier_trace = entry.get('trace', '')
                    break
            for entry in reversed(llm_log):
                if entry.get('type') == 'verifier' and entry.get('valid'):
                    latest_verifier_trace = entry.get('trace', '')
                    break
        except:
            pass
            
        format_data = {
            'title': paper.get('title', ''),
            'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            'previous_classification_json': json.dumps(classification_data, indent=2),
            'reasoning_trace': latest_classifier_trace,
            'verifier_trace': latest_verifier_trace,
            'estimated_score': paper.get(f'{prefix}estimated_score', ''),
            'user_trace': paper.get('user_trace', '') or '',
            'research_area': paper.get('research_area', ''),
        }
        
        return {
            'task_type': TASK_RECLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_reclassify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'prompt': self.reclassify_template.format(**format_data),
            'state_machine': self
        }

    def on_task_complete(self, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when a consensus task completes."""
        if success and llm_data:
            if self.current_task_type == TASK_CLASSIFY or self.current_task_type == TASK_RECLASSIFY:
                log_type = "consensus" if self.current_task_type == TASK_RECLASSIFY else "classifier"
                db.update_set_cache(self.paper_id, self.set_num, llm_data, model_name, reasoning_trace, json_result, valid=True, log_type=log_type, reset_verification=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Classify_{self.iteration}")
            elif self.current_task_type == TASK_VERIFY:
                db.update_set_verifier(self.paper_id, self.set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Verify_{self.iteration}")
        else:
            log_type = "error"
            if self.current_task_type == TASK_VERIFY: log_type = "verifier"
            elif self.current_task_type == TASK_RECLASSIFY: log_type = "consensus"
            else: log_type = "classifier"
            db.update_set_log_only(self.paper_id, self.set_num, log_type, model_name, reasoning_trace, json_result, valid=False)
            
        next_task = self.get_next_task()
        if next_task:
            state.enqueue(next_task)
        elif self.completion_callback:
            self.completion_callback(self.paper_id, self.set_num, success)
            
# ============================================================================
# vLLM COMMUNICATION
# ============================================================================

def _send_to_vllm_sync(task):
    """Synchronous vLLM call (runs in background thread)."""
    task_id = task['task_id']
    task_type = task['task_type']
    paper_id = task['paper_id']
    set_num = task.get('set_num')
    prompt = task['prompt']
    model_alias = task.get('model_alias', 'default')
    state_machine = task.get('state_machine')
    
    log(f"{_color_prefix('SENDING:', Colors.VLLM_SEND)} task={task_id} type={task_type} paper={paper_id} set={set_num}")
    log_file_dispatch(task['task_id'], task['task_type'], task['paper_id'], task.get('set_num'))
        
    try:
        content, model_name, reasoning_trace = globals.send_prompt_to_llm(
            prompt,
            server_url_base=globals.LLM_SERVER_URL,
            model_name=model_alias,
            is_verification=(task_type == TASK_VERIFY)
        )
        
        success = content is not None
        llm_data = json.loads(content) if success and content else None
        
    except Exception as e:
        log(f"{_color_prefix('ERROR:', Colors.ERROR)} task={task_id} error={e}")
        log_file_error('vllm_call', e, task_id=task_id, paper_id=paper_id, set_num=set_num)
        success = False
        llm_data = None
        model_name = "error"
        reasoning_trace = str(e)
        content = ""
    
    # Decrement in-flight AFTER processing
    state.decrement_in_flight(task_type)
    
    # Invoke callback
    if state_machine:
        if hasattr(state_machine, 'on_set_complete'):
            state_machine.on_set_complete(set_num, success, llm_data, model_name, reasoning_trace or "", content or "")
        elif hasattr(state_machine, 'on_task_complete'):
            state_machine.on_task_complete(success, llm_data, model_name, reasoning_trace or "", content or "")
    
    log(f"{_color_prefix('COMPLETE:', Colors.VLLM_COMPLETE)} task={task_id} success={success}")
    log_file_complete(task_id, task_type, success, model_name if success else None, reasoning_trace if not success else None)

    log_queue_status()

def send_to_vllm(task):
    """Send task to vLLM asynchronously (fire-and-forget)."""
    thread = threading.Thread(target=_send_to_vllm_sync, args=(task,))
    thread.daemon = True
    thread.start()

def can_admit_task(task_type):
    """
    Homogeneous/mixed concurrency logic.
    """
    total = state.get_total_in_flight()
    task_in_flight = state.get_in_flight(task_type)
    
    if task_type == TASK_CLASSIFY:
        limit = globals.MAX_CONCURRENT_WORKERS_CLASSIFY
    elif task_type == TASK_VERIFY:
        limit = globals.MAX_CONCURRENT_WORKERS_VERIFY
    elif task_type == TASK_RECLASSIFY:
        limit = globals.MAX_CONCURRENT_WORKERS_RECLASSIFY
    else:
        return False
    
    # Check if we're in homogeneous mode for this task type
    other_types_running = total - task_in_flight
    
    if other_types_running == 0:
        # Homogeneous mode - admit up to type-specific limit
        return task_in_flight < limit
    else:
        # Mixed mode - only admit if we're at or below minimum threshold
        return total < globals.MIN_CONCURRENT_WORKERS

def dispatcher_loop():
    log(f"{_color_prefix('DISPATCHER:', Colors.DISPATCHER)} Starting dispatcher thread...")
    log_queue_status()
    
    while not state.is_shutdown():
        admitted_any = False
        
        # Drain queue as much as admission control allows
        while not state.is_shutdown():
            task = state.peek_queue()
            if task is None:
                break
            
            task_type = task.get('task_type')
            if not can_admit_task(task_type):
                break
            
            task = state.dequeue()
            if not task:
                break
            
            state.increment_in_flight(task_type)
            log(f"{_color_prefix('DISPATCH:', Colors.DISPATCHER)} task={task.get('task_id')} type={task_type}")
            log_queue_status()
            send_to_vllm(task)
            admitted_any = True
        
        if admitted_any:
            continue  # Immediately try to admit more
        
        # No work admitted - wait briefly before re-checking
        time.sleep(0.1)  # 100ms poll interval, lightweight yet fast enough.
    
    log(f"{_color_prefix('DISPATCHER:', Colors.DISPATCHER)} Shutdown complete.")


# ============================================================================
# FLASK HTTP SERVER
# ============================================================================

# Disable Flask's default logging to match original behavior
import logging
werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)
@app.route('/classify', methods=['POST'])
def handle_classify_route():
    """Handle classification request (single paper or batch)."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('REQUEST:', Colors.REQUEST)} from {client}: /classify mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/classify', client, mode, paper_id)

    try:
        prompt_template = globals.load_prompt_template(globals.PROMPT_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    except Exception as e:
        return jsonify({'error': f'Failed to load prompt template: {e}'}), 500

    if mode == 'id' and paper_id:
        # Single paper - NO DB connection held here. 
        # State machines will do their own short-lived DB lookups via db.get_paper_by_id()
        log(f"{_color_prefix('[CLASSIFY]', Colors.CLASSIFY)} Single paper: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = ClassificationStateMachine(paper_id, set_num, prompt_template, model_alias)
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[CLASSIFY]', Colors.CLASSIFY)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            
            # get_prompts() briefly touches the DB, formats the string, and returns
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                
        log(f"Enqueued 3 tasks for paper {paper_id}")
        log_queue_status()
        
        # Wait for background threads OUTSIDE of any DB context
        for event in completion_events:
            event.wait()
            
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200

    else:
        # Batch modes
        # 1. STRICT DB PHASE: Fetch data and immediately release connection
        with db.get_db() as conn:
            cursor = conn.cursor()
            if mode == 'all':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers
                    UNION ALL SELECT id, 2 FROM papers
                    UNION ALL SELECT id, 3 FROM papers
                    ORDER BY id, set_num
                """)
            elif mode == 'remaining':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NULL OR set_1_last_llm_is_offtopic = ''
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NULL OR set_2_last_llm_is_offtopic = ''
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NULL OR set_3_last_llm_is_offtopic = ''
                    ORDER BY id, set_num
                """)
            elif mode == 'no_features':
                set_queries = []
                for sn in [1, 2, 3]:
                    col_name = f'set_{sn}_last_llm_features'
                    conditions = [f"set_{sn}_last_llm_is_offtopic = 0"]
                    for key in globals.BOOLEAN_FEATURE_KEYS:
                        conditions.append(f"""(
                            CASE 
                                WHEN {col_name} IS NULL OR {col_name} = '' THEN 1
                                WHEN json_extract({col_name}, '$.{key}') IS NULL THEN 1
                                WHEN json_extract({col_name}, '$.{key}') = 0 THEN 1
                                ELSE 0
                            END = 1
                        )""")
                    set_queries.append(f"SELECT id, {sn} as set_num FROM papers WHERE {' AND '.join(conditions)}")
                cursor.execute(f" {' UNION ALL '.join(set_queries)} ORDER BY id, set_num")
            elif mode == 'on_topic_implementation':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic = 0 AND (set_1_last_llm_is_survey = 0 OR set_1_last_llm_is_survey IS NULL)
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic = 0 AND (set_2_last_llm_is_survey = 0 OR set_2_last_llm_is_survey IS NULL)
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic = 0 AND (set_3_last_llm_is_survey = 0 OR set_3_last_llm_is_survey IS NULL)
                    ORDER BY id, set_num
                """)
            else:
                return jsonify({'error': f'Invalid mode: {mode}'}), 400

            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            log(f"WARNING: No paper×set pairs found for mode={mode}")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE: Enqueue tasks (get_prompts handles its own micro-DB lookups)
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = ClassificationStateMachine(pid, set_num, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
            total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200

@app.route('/verify', methods=['POST'])
def handle_verify_route():
    """Handle verification request (single paper or batch)."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('VERIFY REQUEST:', Colors.REQUEST)} from {client}: mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/verify', client, mode, paper_id)

    try:
        prompt_template = globals.load_prompt_template(globals.VERIFIER_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to load verifier template: {e}")
        return jsonify({'error': f'Failed to load verifier template: {e}'}), 500

    if mode == 'id' and paper_id:
        log(f"Single paper verification: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = VerificationStateMachine(paper_id, set_num, prompt_template, model_alias)
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[VERIFY]', Colors.VERIFY)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                
        log(f"Enqueued 3 tasks for paper {paper_id}")
        log_queue_status()
        for event in completion_events:
            event.wait()
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
        
    else:
        # 1. STRICT DB PHASE
        with db.get_db() as conn:
            cursor = conn.cursor()
            if mode == 'all':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NOT NULL AND set_1_last_llm_is_offtopic != ''
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NOT NULL AND set_2_last_llm_is_offtopic != ''
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NOT NULL AND set_3_last_llm_is_offtopic != ''
                    ORDER BY id, set_num
                """)
            elif mode == 'remaining':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NOT NULL AND set_1_last_llm_is_offtopic != '' AND (set_1_last_llm_verified IS NULL OR set_1_last_llm_verified = '')
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NOT NULL AND set_2_last_llm_is_offtopic != '' AND (set_2_last_llm_verified IS NULL OR set_2_last_llm_verified = '')
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NOT NULL AND set_3_last_llm_is_offtopic != '' AND (set_3_last_llm_verified IS NULL OR set_3_last_llm_verified = '')
                    ORDER BY id, set_num
                """)
            else:
                return jsonify({'error': f'Invalid mode: {mode}'}), 400

            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = VerificationStateMachine(pid, set_num, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
            total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200

@app.route('/consensus', methods=['POST'])
def handle_consensus_route():
    """Handle classify-until-consensus request."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('CONSENSUS REQUEST:', Colors.REQUEST)} from {client}: mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/consensus', client, mode, paper_id)

    try:
        classify_template = globals.load_prompt_template(globals.PROMPT_TEMPLATE)
        verify_template = globals.load_prompt_template(globals.VERIFIER_TEMPLATE)
        reclassify_template = globals.load_prompt_template(globals.RECLASSIFY_PROMPT_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to load consensus templates: {e}", Colors.ERROR)
        return jsonify({'error': f'Failed to load consensus templates: {e}'}), 500

    if mode == 'id' and paper_id:
        log(f"Single paper consensus: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = ConsensusStateMachine(
                paper_id, set_num,
                classify_template, verify_template, reclassify_template,
                model_alias
            )
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[CONSENSUS]', Colors.CONSENSUS)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            
            task = sm.get_next_task()
            if task:
                state.enqueue(task)
                
        log_queue_status()
        for event in completion_events:
            event.wait()
            
        log(f"COMPLETE: consensus paper={paper_id}")
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
        
    else:
        # 1. STRICT DB PHASE
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, 1 as set_num FROM papers WHERE (set_1_last_llm_verified IS NULL OR set_1_last_llm_estimated_score <= 7)
                UNION ALL SELECT id, 2 FROM papers WHERE (set_2_last_llm_verified IS NULL OR set_2_last_llm_estimated_score <= 7)
                UNION ALL SELECT id, 3 FROM papers WHERE (set_3_last_llm_verified IS NULL OR set_3_last_llm_estimated_score <= 7)
                ORDER BY id, set_num
            """)
            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            log(f"WARNING: No paper×set pairs need consensus")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = ConsensusStateMachine(
                pid, set_num,
                classify_template, verify_template, reclassify_template,
                model_alias
            )
            task = sm.get_next_task()
            if task:
                state.enqueue(task)
                total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200
    
@app.errorhandler(404)
def not_found(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Unknown endpoint {request.path}")
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(400)
def bad_request(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Invalid JSON in request")
    return jsonify({'error': 'Invalid JSON'}), 400


# ============================================================================
# MAIN
# ============================================================================

def signal_handler(sig, frame):
    _log_to_file('dispatcher.log', event='shutdown', signal=sig)
    print("\n[SHUTDOWN] Received shutdown signal...")
    # os._exit(1)  # no bullshit.
    sys.exit(1)

def run_flask_server():
    """Run Flask server with threading enabled."""
    app.run(
        host=globals.QUEUE_MANAGER_HOST,
        port=globals.QUEUE_MANAGER_PORT,
        threaded=True,
        debug=False
    )

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    db.init_db(globals.DATABASE_FILE)

    _log_to_file('dispatcher.log', event='startup', llm_server=globals.LLM_SERVER_URL, http_api=f"{globals.QUEUE_MANAGER_HOST}:{globals.QUEUE_MANAGER_PORT}")
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} {'=' * 52}")
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} ResearchParça Queue Manager Starting")
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} {'=' * 52}")
    log(f"vLLM Server: {globals.LLM_SERVER_URL}")
    log(f"HTTP API: http://{globals.QUEUE_MANAGER_HOST}:{globals.QUEUE_MANAGER_PORT}")
    log(f"Concurrency Limits: classify={globals.MAX_CONCURRENT_WORKERS_CLASSIFY} verify={globals.MAX_CONCURRENT_WORKERS_VERIFY} reclassify={globals.MAX_CONCURRENT_WORKERS_RECLASSIFY} mixed_threshold={globals.MIN_CONCURRENT_WORKERS}")
    log("=" * 60)

    # Start dispatcher thread
    dispatcher_thread = threading.Thread(target=dispatcher_loop, daemon=True)
    dispatcher_thread.start()
    
    # Start Flask HTTP server (blocks)
    try:
        run_flask_server()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()