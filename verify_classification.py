# verify_classification.py
# v1.2 - Unified task queue with dynamic admission control
# 1 task = 1 set verification = 1 vLLM request
# Verifies data from set_{N}_last_llm_* cached columns, NOT history
# After each set verification, triggers main recalculation via globals.recalculate_main_set()

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
class VerifyTask:
    """Represents a single set verification task (1 vLLM request)."""
    def __init__(self, paper_id, set_num, prompt_template_content, db_path,
                 model_alias, server_url, max_retries=3):
        self.paper_id = paper_id
        self.set_num = set_num  # 1, 2, or 3
        self.prompt_template_content = prompt_template_content
        self.db_path = db_path
        self.model_alias = model_alias
        self.server_url = server_url
        self.max_retries = max_retries
        self.task_type = globals.TASK_TYPE_VERIFY
        self.created_at = time.time()
    
    def __repr__(self):
        return f"VerifyTask(paper={self.paper_id}, set={self.set_num})"

# ============================================================================
# VALIDATION HELPERS
# ============================================================================
REQUIRED_VERIFIER_FIELDS = ['verified', 'estimated_score']

def _is_verification_output_valid(output: dict) -> tuple:
    """Validate that a verification output dict has all required fields."""
    if not isinstance(output, dict):
        return False, ['output_not_dict']
    
    missing = [f for f in REQUIRED_VERIFIER_FIELDS if f not in output]
    if missing:
        return False, missing
    
    # Validate estimated_score is numeric
    score = output.get('estimated_score')
    if score is not None and not isinstance(score, (int, float)):
        return False, ['estimated_score_not_numeric']
    
    # Validate verified is boolean or null
    verified = output.get('verified')
    if verified is not None and not isinstance(verified, bool):
        return False, ['verified_not_boolean']
    
    return True, []

# ============================================================================
# ATOMIC SET UPDATE HELPER
# ============================================================================
def _update_set_verification(
    db_path, paper_id, set_num, llm_data, model_name,
    reasoning_trace, success_flag, json_result_str
):
    """Atomically update a single verification set's cache columns and log."""
    conn = None
    cursor = None
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)  # ← 30 second timeout
        conn.execute("PRAGMA journal_mode=WAL")  # ← Enable WAL PER CONNECTION
        conn.execute("PRAGMA busy_timeout=30000")  # ← 30 second busy timeout
        cursor = conn.cursor()
        
        prefix = f'set_{set_num}_last_llm_'
        update_fields = []
        update_values = []
        
        if success_flag and llm_data:
            # Verified field (convert boolean to 1/0/None)
            if 'verified' in llm_data:
                val = llm_data['verified']
                db_val = 1 if val is True else 0 if val is False else None
                update_fields.append(f"{prefix}verified = ?")
                update_values.append(db_val)
            
            # Estimated score
            if 'estimated_score' in llm_data:
                score = llm_data['estimated_score']
                db_score = int(score) if isinstance(score, (int, float)) else None
                update_fields.append(f"{prefix}estimated_score = ?")
                update_values.append(db_score)
            
            # Set verifier tracking (for history purposes)
            update_fields.append(f"{prefix}verified_by = ?")
            update_values.append(model_name)
        
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
            "type": "verifier",
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
            cursor.execute(query, update_values)
            conn.commit()
            return True
        
        return True
    
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            print(f"[{datetime.utcnow().isoformat()}] [DB LOCKED] Paper {paper_id} set {set_num}: {e}")
        else:
            print(f"[{datetime.utcnow().isoformat()}] [DB ERROR] Paper {paper_id} set {set_num}: {e}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return False
    
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] [DB EXCEPTION] Paper {paper_id} set {set_num}: {type(e).__name__}: {e}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return False
    
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================================================
# SINGLE SET VERIFICATION WITH RETRY (NO INTERNAL THREADING)
# ============================================================================
def _verify_single_set(task):
    """
    Verify a single set for a paper with retry logic.
    This is a SINGLE vLLM request - no internal threading.
    Returns True if verification succeeded and was saved, False otherwise.
    """
    paper_id = task.paper_id
    set_num = task.set_num
    prompt_template_content = task.prompt_template_content
    db_path = task.db_path
    model_alias = task.model_alias
    server_url = task.server_url
    max_retries = task.max_retries
    
    # Fetch paper data
    paper_data = None
    try:
        paper_data = globals.get_paper_by_id(db_path, paper_id)
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] [FETCH ERROR] Paper {paper_id} set {set_num}: {type(e).__name__}: {e}")
    
    if not paper_data:
        _update_set_verification(
            db_path, paper_id, set_num, None, model_alias,
            f"Paper {paper_id} not found in DB", False, ""
        )
        return False
    
    # Build verification prompt from set-specific cached data
    try:
        prompt_text = _build_verification_prompt(paper_data, set_num, prompt_template_content)
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] [PROMPT ERROR] Paper {paper_id} set {set_num}: {type(e).__name__}: {e}")
        _update_set_verification(
            db_path, paper_id, set_num, None, model_alias,
            f"Prompt build error: {type(e).__name__}: {e}", False, ""
        )
        return False
    
    for attempt in range(max_retries + 1):
        if globals.is_shutdown_flag_set():
            return False
        
        # SINGLE vLLM call - this is what goes through admission control
        json_result_str, model_used, reasoning_trace = globals.send_prompt_to_llm(
            prompt_text,
            server_url_base=server_url,
            model_name=model_alias,
            is_verification=True
        )
        
        if globals.is_shutdown_flag_set():
            return False
        
        # Process result
        if json_result_str:
            try:
                llm_output = json.loads(json_result_str)
                is_valid, missing = _is_verification_output_valid(llm_output)
                
                if is_valid:
                    # Success: update set data
                    trace_msg = f"As verified by {model_used}\n{reasoning_trace or ''}".strip()
                    success = _update_set_verification(
                        db_path, paper_id, set_num, llm_output,
                        model_used, trace_msg, True, json_result_str
                    )
                    if success:
                        # Trigger main set recalculation
                        globals.recalculate_main_set(paper_id, db_path, changed_by=f"LLM_Verify_Set{set_num}")
                        return True
                    else:
                        # DB update failed - log and retry
                        error_msg = "DB update failed"
                        _update_set_verification(
                            db_path, paper_id, set_num, None, model_alias,
                            error_msg, False, json_result_str
                        )
                else:
                    # Invalid output - log failure and retry
                    error_msg = f"Invalid output: missing {missing}"
                    _update_set_verification(
                        db_path, paper_id, set_num, None, model_alias,
                        error_msg, False, json_result_str
                    )
            except json.JSONDecodeError as e:
                error_msg = f"JSON parse error: {e}"
                _update_set_verification(
                    db_path, paper_id, set_num, None, model_alias,
                    error_msg, False, json_result_str or ""
                )
        else:
            # No response from LLM
            _update_set_verification(
                db_path, paper_id, set_num, None, model_alias,
                "No LLM response received", False, ""
            )
        
        # Retry logic
        if attempt < max_retries:
            time.sleep(0.5)  # Brief backoff
    
    return False

# ============================================================================
# PROMPT BUILDING
# ============================================================================
def _build_verification_prompt(paper_data, set_num, template_content):
    """
    Build verification prompt from set-specific cached columns.
    Reads from set_{N}_last_llm_* columns, NOT main columns.
    """
    prefix = f'set_{set_num}_last_llm_'
    
    # Start with paper metadata
    format_data = {
        'title': paper_data.get('title', ''),
        'abstract': paper_data.get('abstract', ''),
        'keywords': paper_data.get('keywords', ''),
        'authors': paper_data.get('authors', ''),
        'year': paper_data.get('year', ''),
        'type': paper_data.get('type', ''),
        'journal': paper_data.get('journal', ''),
        'set_number': set_num,
    }
    
    # Extract classification data from set-specific cached columns
    # Boolean fields - add DIRECTLY to format_data
    bool_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in bool_fields:
        db_val = paper_data.get(f'{prefix}{field}')
        if db_val == 1:
            format_data[field] = True
        elif db_val == 0:
            format_data[field] = False
        else:
            format_data[field] = None
    
    # Numeric fields - add DIRECTLY to format_data
    format_data['relevance'] = paper_data.get(f'{prefix}relevance')
    
    # Research area - from MAIN column (not set-specific)
    format_data['research_area'] = paper_data.get('research_area')
    
    # JSON fields - add DIRECTLY to format_data
    features_str = paper_data.get(f'{prefix}features')
    technique_str = paper_data.get(f'{prefix}technique')
    
    try:
        format_data['features'] = json.loads(features_str) if features_str else {}
    except (json.JSONDecodeError, TypeError):
        format_data['features'] = {}
    
    try:
        format_data['technique'] = json.loads(technique_str) if technique_str else {}
    except (json.JSONDecodeError, TypeError):
        format_data['technique'] = {}
    
    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"[{datetime.utcnow().isoformat()}] [PROMPT FORMAT ERROR] Missing key {e}")
        raise

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
                print(f"[{datetime.utcnow().isoformat()}] [Worker {worker_id}] Task {task} admission timeout, requeuing")
                task_queue.put(task)
                task_queue.task_done()
                continue
            
            try:
                # Execute single set verification (1 vLLM request)
                success = _verify_single_set(task)
                print(f"[{datetime.utcnow().isoformat()}] [Worker {worker_id}] {task} completed: {'✓' if success else '✗'}")
            finally:
                # Release admission slot
                controller.release(task.task_type)
                task_queue.task_done()
        
        except Exception as e:
            print(f"[{datetime.utcnow().isoformat()}] [Worker {worker_id}] Error: {type(e).__name__}: {e}")
            if globals.is_shutdown_flag_set():
                break

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
def run_verification(
    mode='remaining',
    paper_id=None,
    db_file=None,
    prompt_template=None,
    server_url=None
):
    """
    Runs the LLM verification process with unified task queue.
    Each task = 1 set verification = 1 vLLM request.
    """
    start_time = time.time()
    
    if db_file is None:
        db_file = globals.DATABASE_FILE
    if prompt_template is None:
        prompt_template = globals.VERIFIER_TEMPLATE
    if server_url is None:
        server_url = globals.LLM_SERVER_URL
    
    if not os.path.exists(db_file):
        print(f"[{datetime.utcnow().isoformat()}] Error: Database file '{db_file}' not found.")
        return False
    
    # Load prompt template
    try:
        prompt_template_content = globals.load_prompt_template(prompt_template)
        print(f"[{datetime.utcnow().isoformat()}] Loaded verification prompt template from '{prompt_template}'")
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] Failed to load prompt template: {e}")
        return False
    
    # Get model alias
    print(f"[{datetime.utcnow().isoformat()}] Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print(f"[{datetime.utcnow().isoformat()}] Error: Could not determine model alias. Exiting.")
        return False
    
    # Fetch paper IDs based on mode
    print(f"[{datetime.utcnow().isoformat()}] Connecting to database '{db_file}'...")
    try:
        conn = sqlite3.connect(db_file, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()
        
        if mode == 'all':
            # Verify all classified papers (all 3 sets for each paper)
            cursor.execute("""
                SELECT id FROM papers
                WHERE (changed_by IS NOT NULL AND changed_by != '')
                AND (is_offtopic IS NOT NULL AND is_offtopic != '')
            """)
        elif mode == 'id':
            if paper_id is None:
                print(f"[{datetime.utcnow().isoformat()}] Error: Mode 'id' requires a specific paper ID.")
                conn.close()
                return False
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
            if not cursor.fetchone():
                print(f"[{datetime.utcnow().isoformat()}] Warning: Paper ID {paper_id} not found.")
                conn.close()
                return True
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
        else:  # Default to 'remaining'
            # Verify papers that have classification but no verification yet
            # Check all 3 sets - if any set lacks verification, include the paper
            cursor.execute("""
                SELECT id FROM papers
                WHERE (changed_by IS NOT NULL AND changed_by != '')
                AND (is_offtopic IS NOT NULL AND is_offtopic != '')
                AND (
                    (set_1_last_llm_verified IS NULL OR set_1_last_llm_verified = '')
                    OR (set_2_last_llm_verified IS NULL OR set_2_last_llm_verified = '')
                    OR (set_3_last_llm_verified IS NULL OR set_3_last_llm_verified = '')
                )
            """)
        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        total_papers = len(paper_ids)
        total_tasks = total_papers * 3  # 3 sets per paper
        
        print(f"[{datetime.utcnow().isoformat()}] Found {total_papers} paper(s) to process based on mode '{mode}'.")
        print(f"[{datetime.utcnow().isoformat()}] Total set verification tasks: {total_tasks} (3 sets per paper)")
        
        globals.log_performance_event('verification_batch_start', {
            'mode': mode,
            'total_papers': total_papers,
            'total_tasks': total_tasks,
            'model_alias': model_alias
        })
    
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] Error fetching paper IDs: {type(e).__name__}: {e}")
        return False
    
    if not paper_ids:
        print(f"[{datetime.utcnow().isoformat()}] No papers found matching the criteria. Nothing to process.")
        return True
    
    # Create unified task queue
    task_queue = queue.Queue()
    controller = globals.get_task_queue_controller()
    
    # Create 3 tasks per paper (one for each set)
    for pid in paper_ids:
        for set_num in [1, 2, 3]:
            task = VerifyTask(
                paper_id=pid,
                set_num=set_num,
                prompt_template_content=prompt_template_content,
                db_path=db_file,
                model_alias=model_alias,
                server_url=server_url
            )
            task_queue.put(task)
    
    # Add poison pills for workers
    num_workers = globals.MAX_CONCURRENT_WORKERS_VERIFY
    for _ in range(num_workers):
        task_queue.put(None)
    
    # Start worker threads
    workers = []
    for i in range(num_workers):
        t = threading.Thread(target=_worker, args=(task_queue, controller, i), daemon=True)
        t.start()
        workers.append(t)
    
    print(f"[{datetime.utcnow().isoformat()}] Started {num_workers} workers with unified task queue.")
    print(f"[{datetime.utcnow().isoformat()}] Processing started. Press Ctrl+C to abort.")
    
    try:
        # Monitor progress
        while not globals.is_shutdown_flag_set():
            remaining = task_queue.qsize()
            stats = controller.get_stats()
            papers_done = (total_tasks - remaining) // 3
            print(f"\r[{datetime.utcnow().isoformat()}] [Progress] Queue: {remaining} | Running: {stats['total']} ({stats['state']}) | ", end='', flush=True)
            
            if task_queue.empty() and all(not t.is_alive() for t in workers):
                break
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print(f"\n[{datetime.utcnow().isoformat()}] KeyboardInterrupt caught. Setting shutdown flag.")
        globals.set_shutdown_flag()
        controller.shutdown()
    
    finally:
        # Wait for queue to drain
        task_queue.join()
        
        end_time = time.time()
        globals.log_performance_event('verification_batch_complete', {
            'mode': mode,
            'papers_total': total_papers,
            'tasks_total': total_tasks,
            'duration_seconds': end_time - start_time,
            'model_alias': model_alias
        })
        
        print(f"\n[{datetime.utcnow().isoformat()}] --- Verification Summary ---")
        print(f"[{datetime.utcnow().isoformat()}] Papers processed: {total_papers}")
        print(f"[{datetime.utcnow().isoformat()}] Total vLLM requests: {total_tasks}")
        print(f"[{datetime.utcnow().isoformat()}] Time taken: {end_time - start_time:.2f} seconds")
        print(f"[{datetime.utcnow().isoformat()}] Verification run finished.")
    
    return not globals.is_shutdown_flag_set()

# ============================================================================
# CLI ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM verification.')
    parser.add_argument('--mode', '-m',
                       choices=['all', 'remaining', 'id'],
                       default='remaining')
    parser.add_argument('--paper_id', '-i', type=str)
    parser.add_argument('--db_file', default=globals.DATABASE_FILE)
    parser.add_argument('--prompt_template', '-t', default=globals.VERIFIER_TEMPLATE)
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL)
    parser.add_argument('--exit-on-complete', action='store_true')
    
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, globals.signal_handler)
    
    if args.mode == 'id' and args.paper_id is None:
        parser.error("--mode 'id' requires --paper_id")
    
    success = run_verification(
        mode=args.mode,
        paper_id=args.paper_id,
        db_file=args.db_file,
        prompt_template=args.prompt_template,
        server_url=args.server_url
    )
    
    if not success and not globals.is_shutdown_flag_set() and args.exit_on_complete:
        exit(1)
    
    if not args.exit_on_complete:
        input("Press Enter to continue...")