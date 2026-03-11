# automate_classification.py
# v1.2 - Unified task queue with dynamic admission control
# 1 task = 1 set classification = 1 vLLM request

import sqlite3
import json
import argparse
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import threading
import signal
import globals

# ============================================================================
# TASK DEFINITION
# ============================================================================
class Task:
    """Represents a single set classification task (1 vLLM request)."""
    
    def __init__(self, paper_id, set_num, prompt_template_content, db_path, 
                 model_alias, server_url, max_retries=3):
        self.paper_id = paper_id
        self.set_num = set_num  # 1, 2, or 3
        self.prompt_template_content = prompt_template_content
        self.db_path = db_path
        self.model_alias = model_alias
        self.server_url = server_url
        self.max_retries = max_retries
        self.task_type = globals.TASK_TYPE_CLASSIFY
        self.created_at = time.time()
    
    def __repr__(self):
        return f"Task(paper={self.paper_id}, set={self.set_num})"

# ============================================================================
# VALIDATION HELPERS
# ============================================================================
REQUIRED_CLASSIFICATION_FIELDS = [
    'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
    'relevance', 'features', 'technique'
]

def _is_classification_output_valid(output: dict) -> tuple:
    """Validate that a classification output dict has all required fields."""
    if not isinstance(output, dict):
        return False, ['output_not_dict']
    
    missing = [f for f in REQUIRED_CLASSIFICATION_FIELDS if f not in output]
    if missing:
        return False, missing
    
    if 'features' in output and not isinstance(output['features'], dict):
        return False, ['features_not_dict']
    if 'technique' in output and not isinstance(output['technique'], dict):
        return False, ['technique_not_dict']
    
    return True, []

# ============================================================================
# ATOMIC SET UPDATE HELPER
# ============================================================================
def _update_set_classification(
    db_path, paper_id, set_num, llm_data, model_name, 
    reasoning_trace, success_flag, json_result_str
):
    """Atomically update a single classification set's cache columns and log."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    prefix = f'set_{set_num}_last_llm_'
    update_fields = []
    update_values = []
    
    if success_flag and llm_data:
        # Boolean classification fields
        bool_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
        for field in bool_fields:
            val = llm_data.get(field)
            db_val = 1 if val is True else 0 if val is False else None
            update_fields.append(f"{prefix}{field} = ?")
            update_values.append(db_val)
        
        # Numeric fields
        if 'relevance' in llm_data:
            update_fields.append(f"{prefix}relevance = ?")
            update_values.append(llm_data['relevance'])
        
        if 'estimated_score' in llm_data:
            score = llm_data['estimated_score']
            db_score = int(score) if isinstance(score, (int, float)) else None
            update_fields.append(f"{prefix}estimated_score = ?")
            update_values.append(db_score)
            
            # Verified derived from score
            verified_val = 1 if score >= 7 else 0
            update_fields.append(f"{prefix}verified = ?")
            update_values.append(verified_val)
        else:
            update_fields.append(f"{prefix}verified = ?")
            update_values.append(None)
        
        # JSON fields
        if 'features' in llm_data:
            feat_val = json.dumps(llm_data['features']) if isinstance(llm_data['features'], dict) else None
            update_fields.append(f"{prefix}features = ?")
            update_values.append(feat_val)
        
        if 'technique' in llm_data:
            tech_val = json.dumps(llm_data['technique']) if isinstance(llm_data['technique'], dict) else None
            update_fields.append(f"{prefix}technique = ?")
            update_values.append(tech_val)
    
    # Update set log (ALWAYS done, even on failure)
    log_field = f'set_{set_num}_llm_log'
    cursor.execute(f"SELECT {log_field} FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    
    try:
        existing_log = json.loads(row[0]) if row and row[0] else []
    except (json.JSONDecodeError, TypeError):
        existing_log = []
    
    log_entry = {
        "timestamp": changed_timestamp,
        "type": "classifier",
        "model": model_name,
        "trace": reasoning_trace or "",
        "output": json_result_str if json_result_str else "{}",
        "valid": success_flag
    }
    existing_log.append(log_entry)
    
    update_fields.append(f"{log_field} = ?")
    update_values.append(json.dumps(existing_log))
    
    if update_fields:
        update_values.append(paper_id)
        query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
        try:
            cursor.execute(query, update_values)
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB Error] Failed to update set {set_num} for paper {paper_id}: {e}")
            conn.rollback()
            return False
    
    conn.close()
    return True

# ============================================================================
# SINGLE SET CLASSIFICATION WITH RETRY (NO INTERNAL THREADING)
# ============================================================================
def _classify_single_set(task):
    """
    Classify a single set for a paper with retry logic.
    This is a SINGLE vLLM request - no internal threading.
    
    Returns True if classification succeeded and was saved, False otherwise.
    """
    paper_id = task.paper_id
    set_num = task.set_num
    prompt_template_content = task.prompt_template_content
    db_path = task.db_path
    model_alias = task.model_alias
    server_url = task.server_url
    max_retries = task.max_retries
    
    paper_data = globals.get_paper_by_id(db_path, paper_id)
    if not paper_data:
        _update_set_classification(
            db_path, paper_id, set_num, None, model_alias,
            f"Paper {paper_id} not found in DB", False, ""
        )
        return False
    
    prompt_text = build_prompt(paper_data, prompt_template_content)
    
    for attempt in range(max_retries + 1):
        if globals.is_shutdown_flag_set():
            return False
        
        # SINGLE vLLM call - this is what goes through admission control
        json_result_str, model_used, reasoning_trace = globals.send_prompt_to_llm(
            prompt_text,
            server_url_base=server_url,
            model_name=model_alias,
            is_verification=False
        )
        
        if globals.is_shutdown_flag_set():
            return False
        
        # Process result
        if json_result_str:
            try:
                llm_output = json.loads(json_result_str)
                is_valid, missing = _is_classification_output_valid(llm_output)
                
                if is_valid:
                    # Success: update set data
                    trace_msg = f"As classified by {model_used}\n{reasoning_trace or ''}".strip()
                    success = _update_set_classification(
                        db_path, paper_id, set_num, llm_output,
                        model_used, trace_msg, True, json_result_str
                    )
                    if success:
                        # Trigger main set recalculation
                        globals.recalculate_main_set(paper_id, db_path, changed_by=f"LLM_Set{set_num}")
                        return True
                else:
                    # Invalid output - log failure and retry
                    error_msg = f"Invalid output: missing {missing}"
                    _update_set_classification(
                        db_path, paper_id, set_num, None, model_alias,
                        error_msg, False, json_result_str
                    )
            except json.JSONDecodeError as e:
                error_msg = f"JSON parse error: {e}"
                _update_set_classification(
                    db_path, paper_id, set_num, None, model_alias,
                    error_msg, False, json_result_str or ""
                )
        else:
            # No response from LLM
            _update_set_classification(
                db_path, paper_id, set_num, None, model_alias,
                "No LLM response received", False, ""
            )
        
        # Retry logic
        if attempt < max_retries:
            time.sleep(0.5)  # Brief backoff
    
    return False

# ============================================================================
# WORKER FUNCTION - Each worker processes individual set tasks
# ============================================================================
def _worker(task_queue, controller, worker_id):
    """Worker thread that pulls tasks from unified queue and executes them."""
    while True:
        try:
            # Get task from queue
            try:
                task = task_queue.get(timeout=0.5)
            except queue.Empty:
                if globals.is_shutdown_flag_set() or controller._shutdown:
                    break
                continue
            
            if task is None:  # Poison pill
                task_queue.task_done()
                break
            
            # Wait for admission control (1 slot per vLLM request)
            admitted = controller.acquire(task.task_type, timeout=300)
            if not admitted:
                print(f"[Worker {worker_id}] Task {task} admission timeout, requeuing")
                task_queue.put(task)
                task_queue.task_done()
                continue
            
            try:
                # Execute single set classification (1 vLLM request)
                success = _classify_single_set(task)
                print(f"[Worker {worker_id}] {task} completed: {'✓' if success else '✗'}")
            finally:
                # Release admission slot
                controller.release(task.task_type)
                task_queue.task_done()
                
        except Exception as e:
            print(f"[Worker {worker_id}] Error: {e}")
            if globals.is_shutdown_flag_set():
                break

# ============================================================================
# PROMPT BUILDING
# ============================================================================
def build_prompt(paper_data, template_content):
    """Builds the prompt string for a single paper using a loaded template."""
    format_data = {
        'title': paper_data.get('title', ''),
        'abstract': paper_data.get('abstract', ''),
        'keywords': paper_data.get('keywords', ''),
        'authors': paper_data.get('authors', ''),
        'year': paper_data.get('year', ''),
        'type': paper_data.get('type', ''),
        'journal': paper_data.get('journal', ''),
    }
    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"Error formatting prompt: Missing key {e}")
        raise

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
def run_classification(
    mode='remaining',
    paper_id=None,
    db_file=None,
    prompt_template=None,
    server_url=None
):
    """
    Runs the LLM classification process with unified task queue.
    Each task = 1 set classification = 1 vLLM request.
    """
    start_time = time.time()
    
    if db_file is None:
        db_file = globals.DATABASE_FILE
    if prompt_template is None:
        prompt_template = globals.PROMPT_TEMPLATE
    if server_url is None:
        server_url = globals.LLM_SERVER_URL
    
    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False
    
    # Load prompt template
    try:
        prompt_template_content = globals.load_prompt_template(prompt_template)
        print(f"Loaded prompt template from '{prompt_template}'")
    except Exception as e:
        print(f"Failed to load prompt template: {e}")
        return False
    
    # Get model alias
    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        return False
    
    # Fetch paper IDs based on mode
    print(f"Connecting to database '{db_file}'...")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        if mode == 'all':
            cursor.execute("SELECT id FROM papers")
        elif mode == 'id':
            if paper_id is None:
                print("Error: Mode 'id' requires a specific paper ID.")
                conn.close()
                return False
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
            if not cursor.fetchone():
                print(f"Warning: Paper ID {paper_id} not found.")
                conn.close()
                return True
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
        elif mode == 'no_features':
            conditions = [
                f"(JSON_EXTRACT(features, '$.{key}') IS NULL OR JSON_EXTRACT(features, '$.{key}') = 0)"
                for key in globals.BOOLEAN_FEATURE_KEYS
            ]
            no_features_expr = f"""
                (features IS NULL OR features = '' OR features = '{{}}'
                OR ({' AND '.join(conditions)}))
            """
            where_clause = f"{no_features_expr} AND (is_offtopic = 0 OR is_offtopic IS NULL)"
            cursor.execute(f"SELECT id FROM papers WHERE {where_clause}")
        elif mode == 'on_topic_implementation':
            cursor.execute("""
                SELECT id FROM papers
                WHERE (is_offtopic = 0)
                AND (is_survey = 0 OR is_survey IS NULL)
                AND (changed_by IS NOT 'user')
            """)
        else:  # Default to 'remaining'
            cursor.execute("""
                SELECT id FROM papers 
                WHERE changed_by IS NULL OR changed_by = '' 
                OR is_offtopic = '' OR is_offtopic IS NULL
            """)
        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        total_papers = len(paper_ids)
        total_tasks = total_papers * 3  # 3 sets per paper
        print(f"Found {total_papers} paper(s) to process based on mode '{mode}'.")
        print(f"Total set classification tasks: {total_tasks} (3 sets per paper)")
        
        globals.log_performance_event('classification_batch_start', {
            'mode': mode,
            'total_papers': total_papers,
            'total_tasks': total_tasks,
            'model_alias': model_alias
        })
        
    except Exception as e:
        print(f"Error fetching paper IDs: {e}")
        return False
    
    if not paper_ids:
        print("No papers found matching the criteria. Nothing to process.")
        return True
    
    # Create unified task queue
    task_queue = queue.Queue()
    controller = globals.get_task_queue_controller()
    
    # Create 3 tasks per paper (one for each set)
    for pid in paper_ids:
        for set_num in [1, 2, 3]:
            task = Task(
                paper_id=pid,
                set_num=set_num,
                prompt_template_content=prompt_template_content,
                db_path=db_file,
                model_alias=model_alias,
                server_url=server_url
            )
            task_queue.put(task)
    
    # Add poison pills for workers
    num_workers = globals.MAX_CONCURRENT_WORKERS_CLASSIFY
    for _ in range(num_workers):
        task_queue.put(None)
    
    # Start worker threads
    workers = []
    for i in range(num_workers):
        t = threading.Thread(target=_worker, args=(task_queue, controller, i), daemon=True)
        t.start()
        workers.append(t)
    
    print(f"Started {num_workers} workers with unified task queue.")
    print("Processing started. Press Ctrl+C to abort.")
    
    try:
        # Monitor progress
        while not globals.is_shutdown_flag_set():
            remaining = task_queue.qsize()
            stats = controller.get_stats()
            papers_done = (total_tasks - remaining) // 3
            print(f"\r[Progress] Queue: {remaining} | Running: {stats['total']} ({stats['state']}) | ", end='', flush=True)
            
            if task_queue.empty() and all(not t.is_alive() for t in workers):
                break
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught. Setting shutdown flag.")
        globals.set_shutdown_flag()
        controller.shutdown()
    finally:
        # Wait for queue to drain
        task_queue.join()
        
        end_time = time.time()
        globals.log_performance_event('classification_batch_complete', {
            'mode': mode,
            'papers_total': total_papers,
            'tasks_total': total_tasks,
            'duration_seconds': end_time - start_time,
            'model_alias': model_alias
        })
        
        print(f"\n\n--- Classification Summary ---")
        print(f"Papers processed: {total_papers}")
        print(f"Total vLLM requests: {total_tasks}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Classification run finished.")
        
        return not globals.is_shutdown_flag_set()

# ============================================================================
# CLI ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification.')
    parser.add_argument('--mode', '-m',
        choices=['all', 'remaining', 'id', 'no_features', 'on_topic_implementation'],
        default='remaining')
    parser.add_argument('--paper_id', '-i', type=str)
    parser.add_argument('--db_file', default=globals.DATABASE_FILE)
    parser.add_argument('--prompt_template', '-t', default=globals.PROMPT_TEMPLATE)
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL)
    parser.add_argument('--no-verify', action='store_true')
    parser.add_argument('--exit-on-complete', action='store_true')
    
    args = parser.parse_args()
    signal.signal(signal.SIGINT, globals.signal_handler)
    
    if args.mode == 'id' and args.paper_id is None:
        parser.error("--mode 'id' requires --paper_id")
    
    success = run_classification(
        mode=args.mode, paper_id=args.paper_id, db_file=args.db_file,
        prompt_template=args.prompt_template, server_url=args.server_url
    )
    
    if success and not globals.is_shutdown_flag_set() and not args.no_verify:
        print("\n--- Starting Automatic Verification ---")
        import verify_classification
        verify_classification.run_verification(
            mode='remaining' if args.mode != 'id' else 'id',
            paper_id=args.paper_id, db_file=args.db_file,
            prompt_template=globals.VERIFIER_TEMPLATE, server_url=args.server_url
        )
    
    if not success and not globals.is_shutdown_flag_set() and args.exit_on_complete:
        exit(1)
    
    if not args.exit_on_complete:
        input("Press Enter to continue...")