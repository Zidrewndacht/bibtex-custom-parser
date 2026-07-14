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
        self.max_iterations = config.MAX_CONSENSUS_ITERATIONS
        self.fresh_fallback = config.FRESH_CLASSIFY_FALLBACK_ITERATION
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