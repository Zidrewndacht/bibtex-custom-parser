#automate_classification
import sqlite3
import json
import argparse
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import signal

import globals  #globals.py for global settings and variables used by multiple files.

# Using a simple boolean guarded by a lock for absolute immediacy
shutdown_lock = threading.Lock()
shutdown_flag = False

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
        print(f"Error formatting prompt: Missing key {e} in paper data or template expects it.")
        raise

def update_paper_from_llm(db_path, paper_id, llm_data, changed_by="LLM", reasoning_trace=None):
    """Updates paper classification fields in the database based on LLM output."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    update_fields = []
    update_values = []
    
    if reasoning_trace is not None:
        update_fields.append("reasoning_trace = ?")
        update_values.append(reasoning_trace)

    # Main Boolean Fields
    main_bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in main_bool_fields:
        if field in llm_data:
            value = llm_data[field]
            update_fields.append(f"{field} = ?")
            update_values.append(1 if value is True else 0 if value is False else None)
    
    # Research Area
    if 'research_area' in llm_data:
        update_fields.append("research_area = ?")
        update_values.append(llm_data['research_area'])
    
    # Features
    cursor.execute("SELECT features FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    current_features = json.loads(row[0]) if row and row[0] else {}
    if 'features' in llm_data and isinstance(llm_data['features'], dict):
        current_features.update(llm_data['features'])
        update_fields.append("features = ?")
        update_values.append(json.dumps(current_features))
    
    # Techniques
    cursor.execute("SELECT technique FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    current_technique = json.loads(row[0]) if row and row[0] else {}
    if 'technique' in llm_data and isinstance(llm_data['technique'], dict):
        current_technique.update(llm_data['technique'])
        update_fields.append("technique = ?")
        update_values.append(json.dumps(current_technique))
    
    # Audit fields
    update_fields.append("changed = ?")
    update_values.append(changed_timestamp)
    update_fields.append("changed_by = ?")
    update_values.append(changed_by)
    
    if update_fields:
        update_query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
        update_values.append(paper_id)
        cursor.execute(update_query, update_values)
        conn.commit()
        rows_affected = cursor.rowcount
    else:
        rows_affected = 0
    conn.close()
    return rows_affected > 0

def process_paper_worker(db_path, grammar_content, prompt_template_content, paper_id_queue, progress_lock, processed_count, total_papers, model_alias):
    """Worker function executed by each thread."""
    while True:
        try:
            # Use timeout to periodically check for shutdown
            paper_id = paper_id_queue.get(timeout=1)
        except queue.Empty:
            # Check if we should shutdown periodically
            if globals.is_shutdown_flag_set():
                return
            continue

        # Poison pill - time to die
        if paper_id is None:
            return

        # Check for shutdown before processing
        if globals.is_shutdown_flag_set():
            return

        print(f"[Thread-{threading.get_ident()}] Processing paper ID: {paper_id}")
        
        try:
            paper_data = globals.get_paper_by_id(db_path, paper_id)
            if not paper_data:
                print(f"[Thread-{threading.get_ident()}] Error: Paper {paper_id} not found in DB.")
                continue
                
            prompt_text = build_prompt(paper_data, prompt_template_content)
            if globals.is_shutdown_flag_set():
                return
                
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                prompt_text, 
                grammar_text=grammar_content, 
                server_url_base=globals.LLM_SERVER_URL, 
                model_name=model_alias,
                is_verification=False
            )
            
            if globals.is_shutdown_flag_set():
                return
                
            if json_result_str:
                try:
                    llm_classification = json.loads(json_result_str)
                    # Prepend model info to reasoning_trace
                    if reasoning_trace:
                        reasoning_trace = f"As classified by {model_name_used}\n\n{reasoning_trace}"
                    else:
                        reasoning_trace = f"As classified by {model_name_used}"

                    success = update_paper_from_llm(
                        db_path, 
                        paper_id, 
                        llm_classification, 
                        changed_by=model_name_used,
                        reasoning_trace=reasoning_trace
                    )
                    if success:
                        print(f"[Thread-{threading.get_ident()}] Updated paper {paper_id} (Model: {model_name_used})")
                    else:
                        print(f"[Thread-{threading.get_ident()}] No changes for paper {paper_id}")
                except json.JSONDecodeError as e:
                    print(f"[Thread-{threading.get_ident()}] Error parsing LLM output for {paper_id}: {e}")
                    print(f"LLM Output: {json_result_str}")
                except Exception as e:
                    print(f"[Thread-{threading.get_ident()}] Error updating DB for {paper_id}: {e}")
            else:
                if not globals.is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No LLM response for {paper_id}")
        except Exception as e:
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error processing {paper_id}: {e}")
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Progress] Processed {processed_count[0]}/{total_papers} papers.")

def run_classification(mode='remaining', paper_id=None, db_file=None, grammar_file=None, prompt_template=None, server_url=None):
    """
    Runs the LLM classification process.

    Args:
        mode (str): 'all', 'remaining', or 'id'. Defaults to 'remaining'.
        paper_id (int, optional): The specific paper ID to classify (required if mode='id').
        db_file (str): Path to the SQLite database.
        grammar_file (str): Path to the GBNF grammar file.
        prompt_template (str): Path to the prompt template file.
        server_url (str): Base URL of the LLM server.
    """
    # Use globals for defaults if not provided
    if db_file is None:
        db_file = globals.DATABASE_FILE
    if grammar_file is None:
        grammar_file = globals.GRAMMAR_FILE
    if prompt_template is None:
        prompt_template = globals.PROMPT_TEMPLATE
    if server_url is None:
        server_url = globals.LLM_SERVER_URL

    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False

    try:
        prompt_template_content = globals.load_prompt_template(prompt_template)
        print(f"Loaded prompt template from '{prompt_template}'")
    except Exception as e:
        print(f"Failed to load prompt template: {e}")
        return False

    grammar_content = None
    if grammar_file:
        try:
            grammar_content = globals.load_grammar(grammar_file)
            print(f"Loaded GBNF grammar from '{grammar_file}'")
        except Exception as e:
            print(f"Error reading grammar file '{grammar_file}': {e}")
            grammar_content = None

    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        return False

    print(f"Connecting to database '{db_file}'...")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        if mode == 'all':
            print("Fetching ALL papers for re-classification...")
            cursor.execute("SELECT id FROM papers")
        elif mode == 'id':
            if paper_id is None:
                print("Error: Mode 'id' requires a specific paper ID.")
                conn.close()
                return False
            print(f"Fetching specific paper ID: {paper_id} for classification...")
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
            if not cursor.fetchone():
                 print(f"Warning: Paper ID {paper_id} not found in the database.")
                 conn.close()
                 return True
            cursor.execute("SELECT id FROM papers WHERE id = ?", (paper_id,))
        else: # Default to 'remaining'
            print("Fetching unprocessed papers (changed_by IS NULL or blank)...")
            cursor.execute("SELECT id FROM papers WHERE changed_by IS NULL OR changed_by = ''")
            
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        total_papers = len(paper_ids)
        print(f"Found {total_papers} paper(s) to process based on mode '{mode}'.")

        if not paper_ids:
            print("No papers found matching the criteria. Nothing to process.")
            return True

        paper_id_queue = queue.Queue()
        for pid in paper_ids:
            paper_id_queue.put(pid)

        # Add poison pills for each worker thread
        for _ in range(globals.MAX_CONCURRENT_WORKERS):
            paper_id_queue.put(None)

    except Exception as e:
        print(f"Error fetching paper IDs: {e}")
        return False

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers...")
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            # Submit worker tasks
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                future = executor.submit(
                    process_paper_worker,
                    db_file,
                    grammar_content,
                    prompt_template_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias
                )
                futures.append(future)
            
            print("Processing started. Press Ctrl+C to abort.")
            
            while not globals.is_shutdown_flag_set():
                if all(f.done() for f in futures):
                    break
                time.sleep(0.1)
            
            if globals.is_shutdown_flag_set():
                print("\nShutdown signal received. Waiting for threads to finish...")

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught in run_classification. Setting shutdown flag.")
        globals.set_shutdown_flag()
    except Exception as e:
        print(f"Error in main execution loop: {e}")
        globals.set_shutdown_flag()
    finally:
        end_time = time.time()
        final_count = 0
        if progress_lock:
            with progress_lock:
                final_count = processed_count[0] if processed_count else 0
        print(f"\n--- Classification Summary ---")
        print(f"Papers processed: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Classification run finished.")
        return not globals.is_shutdown_flag_set()
    
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification for papers in the database.')
    parser.add_argument('--mode', '-m', choices=['all', 'remaining', 'id'], default='remaining',
                        help="Processing mode: 'all' (classify everything), 'remaining' (classify unprocessed), 'id' (classify a specific paper). Default: 'remaining'.")
    parser.add_argument('--paper_id', '-i', type=int, help='Paper ID to classify (required if --mode id).')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--grammar_file', '-g', default=globals.GRAMMAR_FILE,
                       help=f'Path to the GBNF grammar file (default: {globals.GRAMMAR_FILE})')
    parser.add_argument('--prompt_template', '-t', default=globals.PROMPT_TEMPLATE,
                       help=f'Path to the prompt template file (default: {globals.PROMPT_TEMPLATE})')
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL,
                       help=f'Base URL of the LLM server (default: {globals.LLM_SERVER_URL})')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, globals.signal_handler)

    if args.mode == 'id' and args.paper_id is None:
        parser.error("--mode 'id' requires --paper_id to be specified.")

    success = run_classification(
        mode=args.mode,
        paper_id=args.paper_id,
        db_file=args.db_file,
        grammar_file=args.grammar_file,
        prompt_template=args.prompt_template,
        server_url=args.server_url
    )

    # Exit code is less critical now as signal_handler does os._exit(1)
    # But good practice to indicate success/failure for non-abort cases
    if not success and not globals.is_shutdown_flag_set():
        exit(1) 
    # If shutdown_flag is set, signal_handler already called os._exit(1)
    # Normal exit code 0 is implicit
