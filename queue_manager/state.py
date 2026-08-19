# queue/state.py
import json
import threading
from collections import deque
from shared import config, db
from .logging_utils import (
    Colors, _color_prefix, _color_queue_mode, log, log_file_queue_status
)

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
TASK_CLASSIFY = "classify"
TASK_VERIFY = "verify"
TASK_RECLASSIFY = "reclassify"

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

def log_queue_status():
    """Log current queue and in-flight status."""
    total_in_flight = state.get_total_in_flight()
    classify_in_flight = state.get_in_flight(TASK_CLASSIFY)
    verify_in_flight = state.get_in_flight(TASK_VERIFY)
    reclassify_in_flight = state.get_in_flight(TASK_RECLASSIFY)
    queue_size = len(state.task_queue)
    
    if classify_in_flight == total_in_flight and classify_in_flight > 0:
        mode = f"HOMOGENEOUS_CLASSIFY (limit={config.MAX_CONCURRENT_WORKERS_CLASSIFY})"
    elif verify_in_flight == total_in_flight and verify_in_flight > 0:
        mode = f"HOMOGENEOUS_VERIFY (limit={config.MAX_CONCURRENT_WORKERS_VERIFY})"
    elif reclassify_in_flight == total_in_flight and reclassify_in_flight > 0:
        mode = f"HOMOGENEOUS_RECLASSIFY (limit={config.MAX_CONCURRENT_WORKERS_RECLASSIFY})"
    else:
        mode = f"MIXED (min_threshold={config.MIN_CONCURRENT_WORKERS})"

    log(f"{_color_prefix('QUEUE STATUS:', Colors.QUEUE_STATUS)} queue_size={queue_size} \t in_flight={total_in_flight} \t classify={classify_in_flight} \t verify={verify_in_flight} \t reclassify={reclassify_in_flight} \t mode={_color_queue_mode(mode)}")
    log_file_queue_status(queue_size, total_in_flight, classify_in_flight, verify_in_flight, reclassify_in_flight, mode)

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
            is_valid, invalid_reason = config.validate_llm_output(llm_data, 'classify')
            if is_valid:
                db.update_set_cache(self.paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Classify_Set{set_num}")
            else:
                log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={set_num} reason={invalid_reason}")
                db.update_set_log_only(self.paper_id, set_num, "classifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            db.update_set_log_only(self.paper_id, set_num, "classifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
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
        paper = db.get_paper_by_id(self.paper_id)
        if not paper: return []
        
        # Load the EXACT raw LLM output from the cached DB blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        format_data = {
            'title': paper.get('title', ''), 'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''), 'authors': paper.get('authors', ''),
            'year': paper.get('year', ''), 'type': paper.get('type', ''), 'journal': paper.get('journal', ''),
            # Pass the ENTIRE raw dictionary as a formatted JSON string
            'previous_classification_json': json.dumps(prev_class, indent=2)
        }
        
        task = {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_verify",
            'paper_id': self.paper_id, 'set_num': self.set_num, 'model_alias': self.model_alias,
            'prompt': self.prompt_template.format(**format_data), 'state_machine': self
        }
        return [task]


    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when this single set verification completes."""
        if success and llm_data:
            is_valid, invalid_reason = config.validate_llm_output(llm_data, 'verify')
            if is_valid:
                db.update_set_verifier(self.paper_id, set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Verify_Set{set_num}")
            else:
                log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={set_num} reason={invalid_reason}")
                db.update_set_log_only(self.paper_id, set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            db.update_set_log_only(self.paper_id, set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
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
        self.max_iterations = config.MAX_CONSENSUS_ITERATIONS
        self.fresh_fallback = config.FRESH_CLASSIFY_FALLBACK_ITERATION
        self.current_task_type = None
        self.completion_callback = None
        self.lock = threading.Lock()

    def get_next_task(self):
        """Determine next task based on current paper state."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper: return None
        if self.iteration >= self.max_iterations: return None
        
        # 1. Load the raw LLM blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        # 2. Read UNIVERSAL audit fields to drive the state machine logic
        # (These exist in every domain by design)
        is_offtopic = prev_class.get('is_offtopic')
        verified = prev_class.get('verified')
        score = prev_class.get('estimated_score')

        if is_offtopic is None:
            self.current_task_type = TASK_CLASSIFY
            return self._create_classify_task(paper)
        elif verified is None:
            self.current_task_type = TASK_VERIFY
            return self._create_verify_task(paper)
        elif verified == False or verified == 0 or (score is not None and score <= 7):
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
                title=paper.get('title', ''), abstract=paper.get('abstract', ''),
                keywords=paper.get('keywords', ''), authors=paper.get('authors', ''),
                year=paper.get('year', ''), type=paper.get('type', ''), journal=paper.get('journal', '')
            ),
            'state_machine': self
        }

    def _create_verify_task(self, paper):
        """Create verification task for consensus state machine."""
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        format_data = {
            'title': paper.get('title', ''), 'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''), 'authors': paper.get('authors', ''),
            'year': paper.get('year', ''), 'type': paper.get('type', ''), 'journal': paper.get('journal', ''),
            # Pass the ENTIRE raw dictionary as a formatted JSON string
            'previous_classification_json': json.dumps(prev_class, indent=2)
        }
        return {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_verify_{self.iteration}",
            'paper_id': self.paper_id, 'set_num': self.set_num, 'model_alias': self.model_alias,
            'prompt': self.verify_template.format(**format_data), 'state_machine': self
        }

    def _create_reclassify_task(self, paper):
        """Create reclassification task for consensus state machine."""
        # 1. Load the EXACT raw LLM output from the cached DB blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        # 2. Extract traces dynamically from the main log
        latest_classifier_trace = ''
        latest_verifier_trace = ''
        try:
            llm_log = json.loads(paper.get('llm_log', '[]') or '[]')
            for entry in reversed(llm_log):
                if entry.get('type') in ['classifier', 'consensus', 'averaged_llm'] and entry.get('valid'):
                    latest_classifier_trace = entry.get('trace', '')
                    break
            for entry in reversed(llm_log):
                if entry.get('type') == 'verifier' and entry.get('valid'):
                    latest_verifier_trace = entry.get('trace', '')
                    break
        except Exception: pass

        # 3. Map directly to your validated reclassify_template.txt variables
        format_data = {
            'title': paper.get('title', ''), 'abstract': paper.get('abstract', ''),
            'keywords': paper.get('keywords', ''), 'authors': paper.get('authors', ''),
            'year': paper.get('year', ''), 'type': paper.get('type', ''), 'journal': paper.get('journal', ''),
            
            # Pass the EXACT raw LLM output as the JSON string. 
            # No manual reconstruction needed! The LLM sees exactly what it spit out last time.
            'previous_classification_json': json.dumps(prev_class, indent=2),
            
            'reasoning_trace': latest_classifier_trace,
            'verifier_trace': latest_verifier_trace,
            'user_trace': paper.get('user_trace', '') or '',
        }
        
        return {
            'task_type': TASK_RECLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_reclassify_{self.iteration}",
            'paper_id': self.paper_id, 'set_num': self.set_num, 'model_alias': self.model_alias,
            'prompt': self.reclassify_template.format(**format_data), 'state_machine': self
        }

    def on_task_complete(self, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when a consensus task completes."""
        if success and llm_data:
            if self.current_task_type == TASK_CLASSIFY or self.current_task_type == TASK_RECLASSIFY:
                is_valid, invalid_reason = config.validate_llm_output(llm_data, 'classify')
                log_type = "consensus" if self.current_task_type == TASK_RECLASSIFY else "classifier"
                
                if is_valid:
                    db.update_set_cache(self.paper_id, self.set_num, llm_data, model_name, reasoning_trace, json_result, valid=True, log_type=log_type, reset_verification=True)
                    db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Classify_{self.iteration}")
                else:
                    log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={self.set_num} reason={invalid_reason}")
                    db.update_set_log_only(self.paper_id, self.set_num, log_type, model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
                    
            elif self.current_task_type == TASK_VERIFY:
                is_valid, invalid_reason = config.validate_llm_output(llm_data, 'verify')
                if is_valid:
                    db.update_set_verifier(self.paper_id, self.set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
                    db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Verify_{self.iteration}")
                else:
                    log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={self.set_num} reason={invalid_reason}")
                    db.update_set_log_only(self.paper_id, self.set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            # LLM call failed or returned non-JSON
            log_type = "error"
            if self.current_task_type == TASK_VERIFY: log_type = "verifier"
            elif self.current_task_type == TASK_RECLASSIFY: log_type = "consensus"
            else: log_type = "classifier"
            db.update_set_log_only(self.paper_id, self.set_num, log_type, model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
        next_task = self.get_next_task()
        if next_task:
            state.enqueue(next_task)
        elif self.completion_callback:
            self.completion_callback(self.paper_id, self.set_num, success)