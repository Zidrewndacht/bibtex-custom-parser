# verify_classification.py
# This should be agnostic to changes inside features and techniques:
import sqlite3
import json
import argparse
import time
import os
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import signal
import globals  # Import for global settings and shared functions
from datetime import datetime

def build_verification_prompt(paper_data, classification_data, template_content):
    """Builds the verification prompt string for a single paper using a loaded template."""
    # Prepare data for insertion into the template
    # Include original paper data
    format_data = {
        'title': paper_data.get('title', ''),
        'abstract': paper_data.get('abstract', ''),
        'keywords': paper_data.get('keywords', ''),
        'authors': paper_data.get('authors', ''),
        'year': paper_data.get('year', ''),
        'type': paper_data.get('type', ''),
        'journal': paper_data.get('journal', ''),
        'relevance': paper_data.get('relevance', ''),
    }
    
    # Include the LLM-generated classification data for verification
    # Convert complex fields (features, technique) back to JSON strings for template insertion
    classification_for_template = classification_data.copy()
    if isinstance(classification_for_template.get('features'), dict):
        classification_for_template['features'] = json.dumps(classification_for_template['features'], indent=2)
    if isinstance(classification_for_template.get('technique'), dict):
        classification_for_template['technique'] = json.dumps(classification_for_template['technique'], indent=2)
        
    # Add classification fields to format data
    format_data.update(classification_for_template)

    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"Error formatting verification prompt: Missing key {e} in paper/classification data or template expects it.")
        raise

# verify_classification.py - Replace update_paper_verification function

def update_paper_verification(db_path, paper_id, verification_result, verified_by="LLM", reasoning_trace=None, success_flag=False, json_result_str="", model_name_used="Unknown"):
    """Updates verification fields and the continuous log. Does NOT touch user_override_count or last_llm_*."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # --- Fetch current llm_log for logging ---
    cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    if not row:
        print(f"Error: Paper {paper_id} not found for verification update.")
        conn.close()
        return False
    
    current_llm_log_str = row[0]
    try:
        existing_log = json.loads(current_llm_log_str) if current_llm_log_str else []
    except json.JSONDecodeError:
        existing_log = []
    
    # --- Prepare LLM Log Entry (ALWAYS created, even on failure) ---
    llm_log_entry = {
        "timestamp": changed_timestamp,
        "type": "verifier",
        "model": model_name_used,
        "trace": reasoning_trace or "",
        "output": json_result_str,
        "valid": success_flag
    }
    
    # --- Append Log Entry ---
    existing_log.append(llm_log_entry)
    
    # --- Prepare Database Updates ---
    update_fields = []
    update_values = []
    
    if success_flag and verification_result:
        verified = verification_result.get('verified')
        if verified is True:
            verified_db_value = 1
        elif verified is False:
            verified_db_value = 0
        else:
            verified_db_value = None
        
        estimated_score = verification_result.get('estimated_score')
        if isinstance(estimated_score, (int, float)):
            estimated_score_db_value = max(0, min(100, int(estimated_score)))
        else:
            estimated_score_db_value = None
        
        # Only update verification fields (NOT changed_by, NOT user_override_count, NOT last_llm_*)
        update_fields.extend(["verified = ?", "estimated_score = ?", "verified_by = ?"])
        update_values.extend([verified_db_value, estimated_score_db_value, verified_by])
    else:
        # On failure, just update verifier_trace if available
        pass
    
    # Add verifier_trace if provided
    if reasoning_trace is not None:
        update_fields.append("verifier_trace = ?")
        update_values.append(reasoning_trace)
    
    # --- Update Database ---
    update_values.extend([json.dumps(existing_log), paper_id])
    update_query = f"UPDATE papers SET {', '.join(update_fields)}, llm_log = ? WHERE id = ?"
    cursor.execute(update_query, update_values)
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    
    return rows_affected > 0

def process_paper_verification_worker(
    db_path,
    verification_prompt_template_content,
    paper_id_queue,
    progress_lock,
    processed_count,
    total_papers,
    model_alias
):
    """Worker function executed by each thread for verification."""
    while True:
        try:
            paper_id = paper_id_queue.get(timeout=1)
        except queue.Empty:
            if globals.is_shutdown_flag_set():
                return
            continue

        if paper_id is None:
            return

        if globals.is_shutdown_flag_set():
            return

        print(f"[Thread-{threading.get_ident()}] Verifying paper ID: {paper_id}")

        try:
            # 1. Fetch paper data and current classification from DB
            paper_data = globals.get_paper_by_id(db_path, paper_id)
            if not paper_data:
                error_msg = f"Paper {paper_id} not found in DB for verification."
                print(f"[Thread-{threading.get_ident()}] Error: {error_msg}")
                # Log the error
                update_paper_verification(
                    db_path,
                    paper_id,
                    {},
                    verified_by="Error",
                    reasoning_trace=error_msg,
                    success_flag=False,
                    json_result_str="",
                    model_name_used=model_alias
                )
                continue

            # Prepare classification data for the prompt
            classification_data = {}
            bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
            for field in bool_fields:
                db_val = paper_data.get(field)
                if db_val == 1:
                    classification_data[field] = True
                elif db_val == 0:
                    classification_data[field] = False
                else:
                    classification_data[field] = None

            classification_data['research_area'] = paper_data.get('research_area')

            # Handle JSON fields
            try:
                classification_data['features'] = json.loads(paper_data.get('features', '{}')) if paper_data.get('features') else {}
            except json.JSONDecodeError:
                classification_data['features'] = {}
                print(f"[Thread-{threading.get_ident()}] Warning: Could not parse features JSON for {paper_id}")

            try:
                classification_data['technique'] = json.loads(paper_data.get('technique', '{}')) if paper_data.get('technique') else {}
            except json.JSONDecodeError:
                classification_data['technique'] = {}
                print(f"[Thread-{threading.get_ident()}] Warning: Could not parse technique JSON for {paper_id}")

            # 2. Build the verification prompt
            prompt_text = build_verification_prompt(paper_data, classification_data, verification_prompt_template_content)

            if globals.is_shutdown_flag_set():
                return

            # 3. Send prompt to LLM
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                prompt_text,
                server_url_base=globals.LLM_SERVER_URL,
                model_name=model_alias,
                is_verification=True
            )

            if globals.is_shutdown_flag_set():
                return

            # 4. Process LLM response
            if json_result_str:
                try:
                    llm_verification_result = json.loads(json_result_str)
                    # 5. Update database with verification result
                    if reasoning_trace:
                        reasoning_trace = f"As verified by {model_name_used}\n{reasoning_trace}"
                    else:
                        reasoning_trace = f"As verified by {model_name_used}"

                    success = update_paper_verification(
                        db_path,
                        paper_id,
                        llm_verification_result,
                        verified_by=model_name_used,
                        reasoning_trace=reasoning_trace,
                        success_flag=True,
                        json_result_str=json_result_str,
                        model_name_used=model_name_used
                    )

                    if success:
                        print(f"[Thread-{threading.get_ident()}] Verified paper {paper_id} (Model: {model_name_used})")
                    else:
                        print(f"[Thread-{threading.get_ident()}] Failed to verify paper {paper_id} (DB error)")

                except json.JSONDecodeError as e:
                    error_msg = f"Error parsing LLM verification output: {str(e)}\n\nLLM Output:\n{json_result_str}"
                    print(f"[Thread-{threading.get_ident()}] {error_msg}")
                    # Log the parsing error
                    update_paper_verification(
                        db_path,
                        paper_id,
                        {},
                        verified_by=model_name_used,
                        reasoning_trace=error_msg,
                        success_flag=False,
                        json_result_str=json_result_str,
                        model_name_used=model_name_used
                    )
            else:
                # --- LLM Call Failed (No Response) ---
                error_msg = "No LLM verification response received. Check server connection."
                print(f"[Thread-{threading.get_ident()}] {error_msg}")
                # Log the failure
                update_paper_verification(
                    db_path,
                    paper_id,
                    {},
                    verified_by=model_name_used,
                    reasoning_trace=error_msg,
                    success_flag=False,
                    json_result_str="",
                    model_name_used=model_name_used
                )

        except Exception as e:
            error_msg = f"Exception during verification: {type(e).__name__}: {str(e)}"
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] {error_msg}")
            # Log the exception as a failure
            update_paper_verification(
                db_path,
                paper_id,
                {},
                verified_by="Error",
                reasoning_trace=error_msg,
                success_flag=False,
                json_result_str="",
                model_name_used=model_alias
            )
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Progress] Verified {processed_count[0]}/{total_papers} papers.")

def run_verification(mode='remaining', paper_id=None, db_file=None, prompt_template=None, server_url=None):
    """
    Runs the LLM verification process.

    Args:
        mode (str): 'all', 'remaining', or 'id'. Defaults to 'remaining'.
        paper_id (int, optional): The specific paper ID to verify (required if mode='id').
        db_file (str): Path to the SQLite database.
        prompt_template (str): Path to the verification prompt template file.
        server_url (str): Base URL of the LLM server.
    """
    if db_file is None:
        db_file = globals.DATABASE_FILE
    if prompt_template is None:
        prompt_template = globals.VERIFIER_TEMPLATE
    if server_url is None:
        server_url = globals.LLM_SERVER_URL

    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False

    try:
        verification_prompt_template_content = globals.load_prompt_template(prompt_template)
        print(f"Loaded verification prompt template from '{prompt_template}'")
    except Exception as e:
        print(f"Error loading verification prompt template: {e}")
        return False

    print(f"Connecting to database '{db_file}' to fetch papers for verification...")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        if mode == 'all': #All classified papers (there's no sense in verifying classification of papers that weren't even classified)
            print("Fetching ALL classified papers for re-verification (most recent to oldest)...")
            cursor.execute("SELECT id FROM papers WHERE (changed_by IS NOT NULL AND changed_by != '') ORDER BY year DESC")
        elif mode == 'id':
            if paper_id is None:
                print("Error: Mode 'id' requires a specific paper ID.")
                conn.close()
                return False
            print(f"Fetching specific paper ID: {paper_id} for verification...")
            cursor.execute("SELECT id FROM papers WHERE id = ? ORDER BY year DESC", (paper_id,))
            if not cursor.fetchone():
                 print(f"Warning: Paper ID {paper_id} not found or not classified.")
                 conn.close()
                 return True
            cursor.execute("SELECT id FROM papers WHERE id = ? ORDER BY year DESC", (paper_id,))
        else: # Default to 'remaining'
            print("Fetching classified but unverified papers (most recent to oldest)...")
            cursor.execute("""
                SELECT id 
                FROM papers 
                WHERE (changed_by IS NOT NULL AND changed_by != '') 
                AND (verified_by IS NULL OR verified_by = '' OR verified = 'unknown' OR verified = '')
                ORDER BY year DESC
            """) #added  OR verified_by = 'unknown' to verify to manually set to ?
            
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        total_papers = len(paper_ids)
        print(f"Found {total_papers} paper(s) to verify based on mode '{mode}'.")

        # Remove any None values that might have been included due to missing years
        paper_ids = [pid for pid in paper_ids if pid is not None]
    except Exception as e:
        print(f"Error fetching paper IDs: {e}")
        return False

    print("Fetching model alias from LLM server for verification...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print("Error: Could not determine model alias for verification. Exiting.")
        return False

    if not paper_ids:
        print("No papers found matching the verification criteria. Nothing to process.")
        return True

    paper_id_queue = queue.Queue()
    for pid in paper_ids:
        paper_id_queue.put(pid)

    # Add poison pills for each worker thread
    for _ in range(globals.MAX_CONCURRENT_WORKERS_VERIFY):
        paper_id_queue.put(None)

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with up to {globals.MAX_CONCURRENT_WORKERS_VERIFY} workers for verification...")
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS_VERIFY) as executor:
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS_VERIFY):
                future = executor.submit(
                    process_paper_verification_worker,
                    db_file,
                    verification_prompt_template_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias
                )
                futures.append(future)
            
            print("Verification processing started. Press Ctrl+C to abort.")
            
            while not globals.is_shutdown_flag_set():
                if all(f.done() for f in futures):
                    break
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught in run_verification. Setting shutdown flag.")
        globals.set_shutdown_flag()
    except Exception as e:
        print(f"Error in main verification execution loop: {e}")
        globals.set_shutdown_flag()
    finally:
        end_time = time.time()
        final_count = 0
        if progress_lock:
            with progress_lock:
                final_count = processed_count[0] if processed_count else 0
        print(f"\n--- Verification Summary ---")
        print(f"Papers verified: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Verification run finished.")
        return not globals.is_shutdown_flag_set()
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verify LLM classifications for papers in the database.')
    parser.add_argument('--mode', '-m', choices=['all', 'remaining', 'id'], default='remaining',
                        help="Verification mode: 'all' (verify all classified), 'remaining' (verify unverified), 'id' (verify a specific paper). Default: 'remaining'.")
    parser.add_argument('--paper_id', '-i', type=int, help='Paper ID to verify (required if --mode id).')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--prompt_template', '-t', default=globals.VERIFIER_TEMPLATE,
                       help=f'Path to the verification prompt template file (default: {globals.VERIFIER_TEMPLATE})')
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL,
                       help=f'Base URL of the LLM server (default: {globals.LLM_SERVER_URL})')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, globals.signal_handler)

    if args.mode == 'id' and args.paper_id is None:
        parser.error("--mode 'id' requires --paper_id to be specified.")

    success = run_verification(
        mode=args.mode,
        paper_id=args.paper_id,
        db_file=args.db_file,
        prompt_template=args.prompt_template,
        server_url=args.server_url
    )

    if not success and not globals.is_shutdown_flag_set():
        exit(1)