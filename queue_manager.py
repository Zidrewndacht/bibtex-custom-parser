# queue_manager.py
"""
Queue Manager - Flask HTTP server for LLM classification/verification.
Single dispatcher thread, callback-driven state machines, no blocking.
"""

import sqlite3
import json
import threading
import signal
from datetime import datetime, timezone
from collections import deque
import os 
import globals
import time
from flask import Flask, request, jsonify

# ============================================================================
# CONFIGURATION
# ============================================================================

DB_PATH = globals.DATABASE_FILE

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
    """Print timestamped message to console."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)  # ← Add flush=True

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
        
    log(f"QUEUE STATUS: queue_size={queue_size} \t in_flight={total_in_flight} \t classify={classify_in_flight} \t verify={verify_in_flight} \t reclassify={reclassify_in_flight} \t mode={mode}")
    
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
# ADMISSION CONTROL
# ============================================================================

def can_admit_task(task_type):
    """
    Homogeneous/mixed concurrency logic.
    If 255 classifications in-flight:
      → 256th classification: ADMIT immediately
      → Incoming verification: WAIT until total ≤ 32
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

# ============================================================================
# STATE MACHINES
# ============================================================================

class ClassificationStateMachine:
    """State machine for classifying a single paper (3 sets in parallel)."""
    
    def __init__(self, paper_id, prompt_template, model_alias):
        self.paper_id = paper_id
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.pending_sets = {1, 2, 3}
        self.completion_callback = None
        self.lock = threading.Lock()
    
    def get_prompts(self):
        """Generate 3 classification tasks (one per set)."""
        paper = globals.get_paper_by_id(DB_PATH, self.paper_id)
        if not paper:
            return []
        
        tasks = []
        for set_num in [1, 2, 3]:
            task = {
                'task_type': TASK_CLASSIFY,
                'task_id': f"{self.paper_id}_set{set_num}_classify",
                'paper_id': self.paper_id,
                'set_num': set_num,
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
            tasks.append(task)
        return tasks
    
    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when a set classification completes."""
        with self.lock:
            self.pending_sets.discard(set_num)
            remaining = len(self.pending_sets)
        
        if success and llm_data:
            self._update_set_cache(set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
            globals.recalculate_main_set(self.paper_id, DB_PATH, changed_by=f"LLM_Classify_Set{set_num}")
        else:
            self._update_set_log(set_num, model_name, reasoning_trace, json_result, valid=False)
        
        # Check if all 3 sets completed
        if remaining == 0 and self.completion_callback:
            self.completion_callback(self.paper_id, success)
    
    def _update_set_cache(self, set_num, llm_data, model_name, reasoning_trace, json_result, valid):
        """Update set_*_last_llm_* columns and set log."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{set_num}_last_llm_'
        
        update_fields = []
        update_values = []
        
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            if field in llm_data:
                val = llm_data[field]
                update_fields.append(f"{prefix}{field} = ?")
                update_values.append(1 if val is True else 0 if val is False else None)
        
        if 'relevance' in llm_data:
            update_fields.append(f"{prefix}relevance = ?")
            update_values.append(llm_data['relevance'])
        
        if 'features' in llm_data:
            update_fields.append(f"{prefix}features = ?")
            update_values.append(json.dumps(llm_data['features']))
        
        if 'technique' in llm_data:
            update_fields.append(f"{prefix}technique = ?")
            update_values.append(json.dumps(llm_data['technique']))
        
        # Update log
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "classifier",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        if update_fields:
            update_values.append(self.paper_id)
            query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, update_values)
            conn.commit()
        
        conn.close()
    
    def _update_set_log(self, set_num, model_name, reasoning_trace, json_result, valid):
        """Update only the set log (for invalid/malformed responses)."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "classifier",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?",
                      (json.dumps(existing_log), self.paper_id))
        conn.commit()
        conn.close()


class VerificationStateMachine:
    """State machine for verifying a single paper (3 sets in parallel)."""
    
    def __init__(self, paper_id, prompt_template, model_alias):
        self.paper_id = paper_id
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.pending_sets = {1, 2, 3}
        self.completion_callback = None
        self.lock = threading.Lock()
    
    def get_prompts(self):
        """Generate 3 verification tasks (one per set)."""
        paper = globals.get_paper_by_id(DB_PATH, self.paper_id)
        if not paper:
            return []
        
        tasks = []
        for set_num in [1, 2, 3]:
            prefix = f'set_{set_num}_last_llm_'
            
            # Convert DB values to proper types for template
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
            
            # Boolean classification fields
            for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
                db_val = paper.get(f'{prefix}{field}')
                format_data[field] = True if db_val == 1 else (False if db_val == 0 else None)
            
            # JSON fields - parse from DB strings
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
                'task_id': f"{self.paper_id}_set{set_num}_verify",
                'paper_id': self.paper_id,
                'set_num': set_num,
                'model_alias': self.model_alias,
                'prompt': self.prompt_template.format(**format_data),
                'state_machine': self
            }
            tasks.append(task)
        return tasks
    
    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when a set verification completes."""
        with self.lock:
            self.pending_sets.discard(set_num)
            remaining = len(self.pending_sets)
        
        if success and llm_data:
            self._update_set_verifier(set_num, llm_data, model_name, reasoning_trace, json_result, valid=True)
            globals.recalculate_main_set(self.paper_id, DB_PATH, changed_by=f"LLM_Verify_Set{set_num}")
        else:
            self._update_set_log(set_num, model_name, reasoning_trace, json_result, valid=False)
        
        if remaining == 0 and self.completion_callback:
            self.completion_callback(self.paper_id, success)
    
    def _update_set_verifier(self, set_num, llm_data, model_name, reasoning_trace, json_result, valid):
        """Update set verifier columns and log."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{set_num}_last_llm_'
        
        update_fields = []
        update_values = []
        
        if 'verified' in llm_data:
            val = llm_data['verified']
            update_fields.append(f"{prefix}verified = ?")
            update_values.append(1 if val is True else 0 if val is False else None)
        
        if 'estimated_score' in llm_data:
            update_fields.append(f"{prefix}estimated_score = ?")
            update_values.append(int(llm_data['estimated_score']))
        
        # Update log
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "verifier",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        update_fields.append(f"set_{set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        if update_fields:
            update_values.append(self.paper_id)
            query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, update_values)
            conn.commit()
        
        conn.close()
    
    def _update_set_log(self, set_num, model_name, reasoning_trace, json_result, valid):
        """Update only the set log (for invalid/malformed responses)."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        cursor.execute(f"SELECT set_{set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "verifier",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        cursor.execute(f"UPDATE papers SET set_{set_num}_llm_log = ? WHERE id = ?",
                      (json.dumps(existing_log), self.paper_id))
        conn.commit()
        conn.close()


class ConsensusStateMachine:
    """State machine for classify-until-consensus on a single paper×set."""
    
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
        paper = globals.get_paper_by_id(DB_PATH, self.paper_id)
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
        
        # Build format_data matching VerificationStateMachine.get_prompts()
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
        
        # Boolean classification fields - convert DB integers to Python booleans
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            db_val = paper.get(f'{prefix}{field}')
            format_data[field] = True if db_val == 1 else (False if db_val == 0 else None)
        
        # JSON fields - parse from DB strings
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
        
        # Build classification data from set-specific cached columns
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
        
        # Parse JSON fields
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
        
        # Extract latest classifier and verifier traces from main llm_log
        latest_classifier_trace = ''
        latest_verifier_trace = ''
        try:
            llm_log_str = paper.get('llm_log', '[]')
            llm_log = json.loads(llm_log_str) if llm_log_str else []
            # Find most recent classifier/consensus entry
            for entry in reversed(llm_log):
                if entry.get('type') in ['classifier', 'consensus', 'averaged_llm'] and entry.get('valid'):
                    latest_classifier_trace = entry.get('trace', '')
                    break
            # Find most recent verifier entry
            for entry in reversed(llm_log):
                if entry.get('type') == 'verifier' and entry.get('valid'):
                    latest_verifier_trace = entry.get('trace', '')
                    break
        except:
            pass
        
        # Build format_data matching v1.0's build_reclassification_prompt
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
                # FIX: Pass reset_verification=True to trigger verification on next iteration
                self._update_set_cache(llm_data, model_name, reasoning_trace, json_result, valid=True, reset_verification=True)
                globals.recalculate_main_set(self.paper_id, DB_PATH, changed_by=f"Consensus_Classify_{self.iteration}")
            elif self.current_task_type == TASK_VERIFY:
                self._update_set_verifier(llm_data, model_name, reasoning_trace, json_result, valid=True)
                globals.recalculate_main_set(self.paper_id, DB_PATH, changed_by=f"Consensus_Verify_{self.iteration}")
        else:
            self._update_set_log(model_name, reasoning_trace, json_result, valid=False)
        
        next_task = self.get_next_task()
        if next_task:
            state.enqueue(next_task)
        elif self.completion_callback:
            self.completion_callback(self.paper_id, self.set_num, success)
    
    def _update_set_cache(self, llm_data, model_name, reasoning_trace, json_result, valid, reset_verification=False):
        """Update set cache columns.
        
        Args:
            reset_verification: If True, also reset verified/estimated_score fields
                            (used after classify/reclassify to trigger verification)
        """
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{self.set_num}_last_llm_'
        update_fields = []
        update_values = []
        for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']:
            if field in llm_data:
                val = llm_data[field]
                update_fields.append(f"{prefix}{field} = ?")
                update_values.append(1 if val is True else 0 if val is False else None)
        if 'relevance' in llm_data:
            update_fields.append(f"{prefix}relevance = ?")
            update_values.append(llm_data['relevance'])
        if 'features' in llm_data:
            update_fields.append(f"{prefix}features = ?")
            update_values.append(json.dumps(llm_data['features']))
        if 'technique' in llm_data:
            update_fields.append(f"{prefix}technique = ?")
            update_values.append(json.dumps(llm_data['technique']))
        
        # FIX: Reset verification fields if requested (after classify/reclassify)
        if reset_verification:
            update_fields.append(f"{prefix}verified = ?")
            update_values.append(None)
            update_fields.append(f"{prefix}estimated_score = ?")
            update_values.append(None)
        
        cursor.execute(f"SELECT set_{self.set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        task_type = "consensus" if self.current_task_type == TASK_RECLASSIFY else "classifier"
        log_entry = {
            "timestamp": timestamp,
            "type": task_type,
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        update_fields.append(f"set_{self.set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        if update_fields:
            update_values.append(self.paper_id)
            query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, update_values)
            conn.commit()
        conn.close()
    
    def _update_set_verifier(self, llm_data, model_name, reasoning_trace, json_result, valid):
        """Update set verifier columns."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        prefix = f'set_{self.set_num}_last_llm_'
        
        update_fields = []
        update_values = []
        
        if 'verified' in llm_data:
            val = llm_data['verified']
            update_fields.append(f"{prefix}verified = ?")
            update_values.append(1 if val is True else 0 if val is False else None)
        
        if 'estimated_score' in llm_data:
            update_fields.append(f"{prefix}estimated_score = ?")
            update_values.append(int(llm_data['estimated_score']))
        
        cursor.execute(f"SELECT set_{self.set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "verifier",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        update_fields.append(f"set_{self.set_num}_llm_log = ?")
        update_values.append(json.dumps(existing_log))
        
        if update_fields:
            update_values.append(self.paper_id)
            query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, update_values)
            conn.commit()
        
        conn.close()
    
    def _update_set_log(self, model_name, reasoning_trace, json_result, valid):
        """Update only the set log."""
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        cursor.execute(f"SELECT set_{self.set_num}_llm_log FROM papers WHERE id = ?", (self.paper_id,))
        row = cursor.fetchone()
        try:
            existing_log = json.loads(row[0]) if row and row[0] else []
        except:
            existing_log = []
        
        log_entry = {
            "timestamp": timestamp,
            "type": "error",
            "model": model_name,
            "trace": reasoning_trace or "",
            "output": json_result or "{}",
            "valid": valid
        }
        existing_log.append(log_entry)
        
        cursor.execute(f"UPDATE papers SET set_{self.set_num}_llm_log = ? WHERE id = ?",
                      (json.dumps(existing_log), self.paper_id))
        conn.commit()
        conn.close()

# ============================================================================
# VLLM COMMUNICATION
# ============================================================================

def send_to_vllm(task):
    """Send task to vLLM asynchronously (fire-and-forget)."""
    thread = threading.Thread(target=_send_to_vllm_sync, args=(task,))
    thread.daemon = True
    thread.start()

def _send_to_vllm_sync(task):
    """Synchronous vLLM call (runs in background thread)."""
    task_id = task['task_id']
    task_type = task['task_type']
    paper_id = task['paper_id']
    set_num = task.get('set_num')
    prompt = task['prompt']
    model_alias = task.get('model_alias', 'default')
    state_machine = task.get('state_machine')
    
    log(f"SENDING: task={task_id} type={task_type} paper={paper_id} set={set_num}")
    
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
        log(f"ERROR: task={task_id} error={e}")
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
    
    log(f"COMPLETE: task={task_id} success={success}")
    log_queue_status()

# ============================================================================
# DISPATCHER
# ============================================================================

# def dispatcher_loop():
#     """Single dispatcher thread - never blocks except on completion_event"""
#     log(f"DISPATCHER: Starting dispatcher thread...")
#     log_queue_status()
    
#     while not state.is_shutdown():
#         task = state.peek_queue()
        
#         if task is None:
#             # Queue empty - wait for new tasks
#             state.completion_event.clear()
#             state.completion_event.wait(timeout=1.0)
#             continue
        
#         task_type = task.get('task_type')
#         task_id = task.get('task_id', 'unknown')
        
#         if can_admit_task(task_type):
#             task = state.dequeue()
#             if task:
#                 state.increment_in_flight(task_type)
#                 log(f"DISPATCH: task={task_id} type={task_type}")
#                 log_queue_status()
#                 send_to_vllm(task)  # Fire-and-forget, doesn't block
#         else:
#             # Can't admit - wait for ANY completion
#             state.completion_event.clear()
#             state.completion_event.wait(timeout=0.5)
    
#     log(f"DISPATCHER: Shutdown complete.")

def dispatcher_loop():
    log(f"DISPATCHER: Starting dispatcher thread...")
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
            log(f"DISPATCH: task={task.get('task_id')} type={task_type}")
            log_queue_status()
            send_to_vllm(task)
            admitted_any = True
        
        if admitted_any:
            continue  # Immediately try to admit more
        
        # No work admitted - wait briefly before re-checking
        time.sleep(0.1)  # 100ms poll interval, lightweight yet fast enough.
    
    log(f"DISPATCHER: Shutdown complete.")

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
    
    log(f"REQUEST from {client}: /classify mode={data.get('mode', 'id')} paper_id={data.get('paper_id', 'N/A')}")
    
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    
    try:
        prompt_template = globals.load_prompt_template(globals.PROMPT_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    except Exception as e:
        return jsonify({'error': f'Failed to load prompt template: {e}'}), 500
    
    if mode == 'id' and paper_id:
        # Single paper - create state machine and wait for completion
        log(f"Single paper classification: {paper_id}")
        sm = ClassificationStateMachine(paper_id, prompt_template, model_alias)
        
        completion_event = threading.Event()
        def on_complete(pid, success):
            log(f"COMPLETE: classify paper={pid} success={success}")
            completion_event.set()
        sm.completion_callback = on_complete
        
        # Enqueue 3 classification tasks
        tasks = sm.get_prompts()
        if not tasks:
            log(f"ERROR: No tasks generated for paper {paper_id}")
            return jsonify({'error': 'Failed to generate classification tasks'}), 500
        
        for task in tasks:
            state.enqueue(task)
        log(f"Enqueued {len(tasks)} tasks for paper {paper_id}")
        log_queue_status()
        
        # Wait for completion (no timeout)
        completion_event.wait()
        
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
    
    else:
        # Batch mode - query DB and enqueue (EXACT SAME QUERIES AS v1.0)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if mode == 'all':
            cursor.execute("SELECT id FROM papers")
        
        elif mode == 'remaining':
            cursor.execute("SELECT id FROM papers WHERE changed_by IS NULL OR changed_by = '' OR is_offtopic = '' OR is_offtopic IS NULL")
        
        elif mode == 'no_features':
            # EXACT v1.0 query - check each boolean feature key
            conditions = [
                f"(JSON_EXTRACT(features, '$.{key}') IS NULL OR JSON_EXTRACT(features, '$.{key}') = 0)"
                for key in globals.BOOLEAN_FEATURE_KEYS
            ]
            no_features_expr = f"""
            (features IS NULL
            OR features = ''
            OR features = '{{}}'
            OR ({' AND '.join(conditions)}))
            """
            where_clause = f"""
            {no_features_expr}
            AND (is_offtopic = 0 OR is_offtopic IS NULL)
            """
            cursor.execute(f"SELECT id FROM papers WHERE {where_clause}")
        
        elif mode == 'on_topic_implementation':
            # EXACT v1.0 query - includes changed_by IS NOT 'user' check
            cursor.execute("""
                SELECT id FROM papers
                WHERE (is_offtopic = 0)
                AND (is_survey = 0 OR is_survey IS NULL)
                AND (changed_by IS NOT 'user')
            """)
        
        else:
            conn.close()
            log(f"ERROR: Invalid mode {mode}")
            return jsonify({'error': f'Invalid mode: {mode}'}), 400
        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        log(f"DB QUERY: mode={mode} found {len(paper_ids)} papers")
        
        if not paper_ids:
            log(f"WARNING: No papers found for mode={mode}")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200
        
        # Enqueue all papers
        total_tasks = 0
        for pid in paper_ids:
            sm = ClassificationStateMachine(pid, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                total_tasks += 1
        
        log(f"BATCH ENQUEUE: papers={len(paper_ids)} tasks={total_tasks}")
        log_queue_status()
        
        return jsonify({'status': 'queued', 'papers_queued': len(paper_ids), 'tasks_queued': total_tasks}), 200


@app.route('/verify', methods=['POST'])
def handle_verify_route():
    """Handle verification request (single paper or batch)."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    
    log(f"VERIFY REQUEST from {client}: mode={mode} paper_id={paper_id}")
    
    try:
        prompt_template = globals.load_prompt_template(globals.VERIFIER_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
        log(f"Loaded verifier template: {globals.VERIFIER_TEMPLATE}")
        log(f"Model alias: {model_alias}")
    except Exception as e:
        log(f"ERROR: Failed to load verifier template: {e}")
        return jsonify({'error': f'Failed to load verifier template: {e}'}), 500
    
    if mode == 'id' and paper_id:
        # Single paper - create state machine and wait for completion
        log(f"Single paper verification: {paper_id}")
        sm = VerificationStateMachine(paper_id, prompt_template, model_alias)
        
        completion_event = threading.Event()
        def on_complete(pid, success):
            log(f"COMPLETE: verify paper={pid} success={success}")
            completion_event.set()
        sm.completion_callback = on_complete
        
        tasks = sm.get_prompts()
        if not tasks:
            log(f"ERROR: No tasks generated for paper {paper_id}")
            return jsonify({'error': 'Failed to generate verification tasks'}), 500
        
        for task in tasks:
            state.enqueue(task)
        log(f"Enqueued {len(tasks)} tasks for paper {paper_id}")
        log_queue_status()
        
        completion_event.wait()
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
    
    else:
        # Batch mode - query DB and enqueue
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if mode == 'all':
            cursor.execute("""
                SELECT id FROM papers
                WHERE changed_by IS NOT NULL AND changed_by != ''
            """)
        elif mode == 'remaining':
            cursor.execute("""
                SELECT id FROM papers
                WHERE changed_by IS NOT NULL AND changed_by != ''
                AND (set_1_last_llm_verified IS NULL OR set_2_last_llm_verified IS NULL OR set_3_last_llm_verified IS NULL)
            """)
        else:
            conn.close()
            log(f"ERROR: Invalid mode {mode}")
            return jsonify({'error': f'Invalid mode: {mode}'}), 400
        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        log(f"DB QUERY: mode={mode} found {len(paper_ids)} papers")
        
        if not paper_ids:
            log(f"WARNING: No papers found for mode={mode}")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200
        
        # Enqueue all papers
        total_tasks = 0
        for pid in paper_ids:
            sm = VerificationStateMachine(pid, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                total_tasks += 1
        
        log(f"BATCH ENQUEUE: papers={len(paper_ids)} tasks={total_tasks}")
        log_queue_status()
        
        return jsonify({'status': 'queued', 'papers_queued': len(paper_ids), 'tasks_queued': total_tasks}), 200


@app.route('/consensus', methods=['POST'])
def handle_consensus_route():
    """Handle classify-until-consensus request."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    
    log(f"CONSENSUS REQUEST from {client}: mode={mode} paper_id={paper_id}")
    
    try:
        classify_template = globals.load_prompt_template(globals.PROMPT_TEMPLATE)
        verify_template = globals.load_prompt_template(globals.VERIFIER_TEMPLATE)
        reclassify_template = globals.load_prompt_template(globals.RECLASSIFY_PROMPT_TEMPLATE)
        model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
        log(f"Loaded all 3 prompt templates")
        log(f"Model alias: {model_alias}")
    except Exception as e:
        log(f"ERROR: Failed to load consensus templates: {e}")
        return jsonify({'error': f'Failed to load consensus templates: {e}'}), 500
    
    if mode == 'id' and paper_id:
        # Single paper - create 3 consensus state machines (one per set)
        log(f"Single paper consensus: {paper_id}")
        completion_events = [threading.Event() for _ in range(3)]
        
        for set_num in [1, 2, 3]:
            sm = ConsensusStateMachine(
                paper_id, set_num,
                classify_template, verify_template, reclassify_template,
                model_alias
            )
            
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"[CONSENSUS] paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            
            # Get first task and enqueue
            task = sm.get_next_task()
            if task:
                state.enqueue(task)
                log(f"Enqueued initial task for paper={paper_id} set={set_num} type={task['task_type']}")
        
        log_queue_status()
        
        # Wait for all 3 sets to complete
        for event in completion_events:
            event.wait()
        
        log(f"COMPLETE: consensus paper={paper_id}")
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
    
    else:
        # Batch consensus - query DB for papers needing consensus
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id FROM papers
            WHERE (set_1_last_llm_verified IS NULL OR set_1_last_llm_estimated_score <= 7)
            OR (set_2_last_llm_verified IS NULL OR set_2_last_llm_estimated_score <= 7)
            OR (set_3_last_llm_verified IS NULL OR set_3_last_llm_estimated_score <= 7)
        """)
        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        log(f"DB QUERY: consensus found {len(paper_ids)} papers needing consensus")
        
        if not paper_ids:
            log(f"WARNING: No papers need consensus")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200
        
        # Create state machines for each paper×set
        total_tasks = 0
        for pid in paper_ids:
            for set_num in [1, 2, 3]:
                sm = ConsensusStateMachine(
                    pid, set_num,
                    classify_template, verify_template, reclassify_template,
                    model_alias
                )
                task = sm.get_next_task()
                if task:
                    state.enqueue(task)
                    total_tasks += 1
        
        log(f"BATCH ENQUEUE: consensus papers={len(paper_ids)} initial_tasks={total_tasks}")
        log_queue_status()
        
        return jsonify({'status': 'queued', 'papers_queued': len(paper_ids), 'tasks_queued': total_tasks}), 200


@app.errorhandler(404)
def not_found(e):
    log(f"ERROR: Unknown endpoint {request.path}")
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(400)
def bad_request(e):
    log(f"ERROR: Invalid JSON in request")
    return jsonify({'error': 'Invalid JSON'}), 400


# ============================================================================
# MAIN
# ============================================================================

def signal_handler(sig, frame):
    print("\n[SHUTDOWN] Received shutdown signal...")
    os._exit(1)  # no bullshit.

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
    
    log("=" * 60)
    log("ResearchParça Queue Manager Starting")
    log("=" * 60)
    log(f"Database: {DB_PATH}")
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