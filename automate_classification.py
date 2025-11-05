# automate_classification
# This should be agnostic to changes inside features and techniques:
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
import verify_classification

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

def build_reclassification_prompt(paper_data, template_content):
    """Builds the reclassification prompt string for a single paper using a loaded template."""
    # Extract classification data from paper record
    classification_data = {}
    bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in bool_fields:
        # Convert DB integers (1,0,None) back to boolean/None for prompt clarity
        db_val = paper_data.get(field)
        if db_val == 1:
            classification_data[field] = True
        elif db_val == 0:
            classification_data[field] = False
        else:  # None or unexpected
            classification_data[field] = None
    classification_data['research_area'] = paper_data.get('research_area')
    classification_data['relevance'] = paper_data.get('relevance')
    # Handle JSON fields
    try:
        classification_data['features'] = json.loads(paper_data.get('features', '{}')) if paper_data.get('features') else {}
    except json.JSONDecodeError:
        classification_data['features'] = {}
    try:
        classification_data['technique'] = json.loads(paper_data.get('technique', '{}')) if paper_data.get('technique') else {}
    except json.JSONDecodeError:
        classification_data['technique'] = {}
    
    format_data = {
        'title': paper_data.get('title', ''),
        'abstract': paper_data.get('abstract', ''),
        'keywords': paper_data.get('keywords', ''),
        'authors': paper_data.get('authors', ''),
        'year': paper_data.get('year', ''),
        'type': paper_data.get('type', ''),
        'journal': paper_data.get('journal', ''),
        'previous_classification_json': json.dumps(classification_data, indent=2),
        'reasoning_trace': paper_data.get('reasoning_trace', ''),
        'estimated_score': paper_data.get('estimated_score', ''),
        'verifier_trace': paper_data.get('verifier_trace', ''),
        'user_trace': paper_data.get('user_comments', '') or ''  # Assuming a user_comments field might exist
    }
    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"Error formatting reclassification prompt: Missing key {e} in paper data or template expects it.")
        raise

def update_paper_from_llm(db_path, paper_id, llm_data, changed_by="LLM", reasoning_trace=None):
    """Updates paper classification fields in the database based on LLM output."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    update_fields = []
    update_values = []
    
    # Update reasoning_trace if provided
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
    
    # Research Area and Relevance
    if 'research_area' in llm_data:
        update_fields.append("research_area = ?")
        update_values.append(llm_data['research_area'])
    if 'relevance' in llm_data:
        update_fields.append("relevance = ?")
        update_values.append(llm_data['relevance'])
    
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
    
    # Reset verification fields when classification is updated
    # This ensures verified status is cleared after re-classification
    update_fields.append("verified = ?")
    update_values.append(None)
    update_fields.append("estimated_score = ?")
    update_values.append(None)
    update_fields.append("verified_by = ?")
    update_values.append("")
    update_fields.append("verifier_trace = ?")
    update_values.append("")
    
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

def process_paper_worker(db_path, prompt_template_content, paper_id_queue, progress_lock, processed_count, total_papers, model_alias, reclassification_mode=False):
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
            
            if reclassification_mode:
                prompt_text = build_reclassification_prompt(paper_data, prompt_template_content)
            else:
                prompt_text = build_prompt(paper_data, prompt_template_content)
                
            if globals.is_shutdown_flag_set():
                return
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                prompt_text, 
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
                        print(f"[Thread-{threading.get_ident()}] Failed to update paper {paper_id} (DB error)")
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

def run_classification(mode='remaining', paper_id=None, db_file=None, prompt_template=None, server_url=None):
    """
    Runs the LLM classification process.
    Args:
        mode (str): 'all', 'remaining', 'id', 'no_features', 'on_topic_implementation', 'consensus'. Defaults to 'remaining'.
        paper_id (int, optional): The specific paper ID to classify (required if mode='id').
        db_file (str): Path to the SQLite database.
        prompt_template (str): Path to the prompt template file.
        server_url (str): Base URL of the LLM server.
    """
    # Use globals for defaults if not provided
    if db_file is None:
        db_file = globals.DATABASE_FILE
    if prompt_template is None:
        prompt_template = globals.PROMPT_TEMPLATE
    if server_url is None:
        server_url = globals.LLM_SERVER_URL
    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False

    if mode == 'consensus':
        return run_consensus_classification(db_file, server_url)
    
    try:
        prompt_template_content = globals.load_prompt_template(prompt_template)
        print(f"Loaded prompt template from '{prompt_template}'")
    except Exception as e:
        print(f"Failed to load prompt template: {e}")
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
        elif mode == 'no_features':
            # Goal: Re-classify on-topic papers that LLM failed to assign any defect/features to.
            # Off-topic papers are excluded by design (they have no features intentionally).        
            print("Fetching on-topic papers with no boolean features set to true...")
            conditions = [
                f"(JSON_EXTRACT(features, '$.{key}') IS NULL OR JSON_EXTRACT(features, '$.{key}') = 0)"
                for key in globals.BOOLEAN_FEATURE_KEYS
            ]
            # Group all "no features" cases
            no_features_expr = f"""
                (features IS NULL 
                 OR features = '' 
                 OR features = '{{}}'
                 OR ({' AND '.join(conditions)}))
            """
            # Only include if NOT off-topic (i.e., on-topic or unreviewed)
            where_clause = f"""
                {no_features_expr}
                AND (is_offtopic = 0 OR is_offtopic IS NULL)
            """
            cursor.execute(f"SELECT id FROM papers WHERE {where_clause}")
        elif mode == 'on_topic_implementation':
            # Goal: Re-classify papers that are currently marked as on-topic AND non-survey.
            print("Fetching papers marked as on-topic and non-survey for re-classification...")
            cursor.execute("""
                SELECT id FROM papers
                WHERE (is_offtopic = 0)
                AND (is_survey = 0 OR is_survey IS NULL)
                AND (changed_by IS NOT 'user')
            """)
        else: # Default to 'remaining'
            print("Fetching unprocessed papers (changed_by IS NULL or blank)...")
            cursor.execute("SELECT id FROM papers WHERE changed_by IS NULL OR changed_by = '' OR is_offtopic = '' OR is_offtopic IS NULL ") #set to reclassify when manually removing offtopic status
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

    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        return False
        
    progress_lock = threading.Lock()
    processed_count = [0]
    print(f"Starting ThreadPoolExecutor with up to {globals.MAX_CONCURRENT_WORKERS} workers...")
    start_time = time.time()
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            # Submit worker tasks
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                future = executor.submit(
                    process_paper_worker,
                    db_file,
                    prompt_template_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias,
                    reclassification_mode=False  # Not reclassification mode
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

def run_consensus_classification(db_file, server_url):
    """
    Runs the consensus classification process.
    Starts with classify remaining and verify remaining, then re-classifies misclassifications (score <= 8) until consensus is reached.
    """
    iteration = 0
    while True:
        iteration += 1
        print(f"\n--- Consensus Iteration {iteration} ---")
        
        # First, classify any remaining unprocessed papers
        print("\n--- Starting Initial Classification of Remaining Papers ---")
        initial_classification_success = run_classification(
            mode='remaining',
            db_file=db_file,
            prompt_template=globals.PROMPT_TEMPLATE,
            server_url=server_url
        )
        if not initial_classification_success:
            print("Initial classification failed. Stopping consensus process.")
            return False
        
        # Then, verify all remaining unverified papers
        print("\n--- Starting Verification of All Unverified Papers ---")
        verification_success = verify_classification.run_verification(
            mode='remaining',
            db_file=db_file,
            prompt_template=globals.VERIFIER_TEMPLATE,
            server_url=server_url
        )
        if not verification_success:
            print("Initial verification failed. Stopping consensus process.")
            return False
        
        # Now check for misclassifications (papers with verified=0 and low scores)
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM papers 
            WHERE verified = 0 
            AND (estimated_score IS NULL OR estimated_score <= 8)
            ORDER BY estimated_score ASC
        """)
        misclassified_paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if not misclassified_paper_ids:
            print("No more misclassified papers found. Consensus reached!")
            return True
        
        print(f"Found {len(misclassified_paper_ids)} misclassified papers for re-classification.")
        
        # Run reclassification on misclassified papers
        reclassification_success = run_reclassification_batch(misclassified_paper_ids, db_file, server_url)
        if not reclassification_success:
            print("Reclassification batch failed. Stopping consensus process.")
            return False
        
        # After reclassification, run verification again on the re-classified papers
        print("\n--- Starting Verification for Re-classified Papers ---")
        verification_success = verify_classification.run_verification(
            mode='remaining',
            db_file=db_file,
            prompt_template=globals.VERIFIER_TEMPLATE,
            server_url=server_url
        )
        if not verification_success:
            print("Verification after reclassification failed. Stopping consensus process.")
            return False
        
        # Check if user wants to abort
        if globals.is_shutdown_flag_set():
            print("Shutdown signal received. Stopping consensus process.")
            return False
        
def run_reclassification_batch(paper_ids, db_file, server_url):
    """
    Runs reclassification on a batch of paper IDs.
    """
    total_papers = len(paper_ids)
    if total_papers == 0:
        print("No papers to reclassify in this batch.")
        return True
    
    print(f"Reclassifying {total_papers} papers...")
    
    try:
        # Load the reclassification prompt template
        reclassification_prompt_template = globals.RECLASSIFY_PROMPT_TEMPLATE
        reclassification_prompt_content = globals.load_prompt_template(reclassification_prompt_template)
        print(f"Loaded reclassification prompt template from '{reclassification_prompt_template}'")
    except Exception as e:
        print(f"Failed to load reclassification prompt template: {e}")
        return False
    
    print("Fetching model alias from LLM server for reclassification...")
    model_alias = globals.get_model_alias(server_url)
    if not model_alias:
        print("Error: Could not determine model alias for reclassification. Exiting.")
        return False
    
    # Create queue with paper IDs
    paper_id_queue = queue.Queue()
    for pid in paper_ids:
        paper_id_queue.put(pid)
    # Add poison pills for each worker thread
    for _ in range(globals.MAX_CONCURRENT_WORKERS_CONSENSUS):
        paper_id_queue.put(None)
    
    progress_lock = threading.Lock()
    processed_count = [0]
    
    print(f"Starting ThreadPoolExecutor with up to {globals.MAX_CONCURRENT_WORKERS_CONSENSUS} workers for reclassification...")
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS_CONSENSUS) as executor:
            # Submit worker tasks
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS_CONSENSUS):
                future = executor.submit(
                    process_paper_worker,
                    db_file,
                    reclassification_prompt_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias,
                    reclassification_mode=True  # This is reclassification mode
                )
                futures.append(future)
            
            print("Reclassification processing started. Press Ctrl+C to abort.")
            while not globals.is_shutdown_flag_set():
                if all(f.done() for f in futures):
                    break
                time.sleep(0.1)
            if globals.is_shutdown_flag_set():
                print("\nShutdown signal received during reclassification. Waiting for threads to finish...")
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught in run_reclassification_batch. Setting shutdown flag.")
        globals.set_shutdown_flag()
    except Exception as e:
        print(f"Error in reclassification execution loop: {e}")
        globals.set_shutdown_flag()
    finally:
        end_time = time.time()
        final_count = 0
        if progress_lock:
            with progress_lock:
                final_count = processed_count[0] if processed_count else 0
        print(f"\n--- Reclassification Summary ---")
        print(f"Papers reclassified: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Reclassification batch finished.")
        return not globals.is_shutdown_flag_set()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification for papers in the database.')
    parser.add_argument('--mode', '-m',
                choices=['all', 'remaining', 'id', 'no_features', 'on_topic_implementation', 'consensus'],
                default='remaining',
                help="Processing mode: 'all', 'remaining', 'id', 'no_features', 'on_topic_implementation', or 'consensus'. Default: 'remaining'.")
    parser.add_argument('--paper_id', '-i', type=int, help='Paper ID to classify (required if --mode id).')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--prompt_template', '-t', default=globals.PROMPT_TEMPLATE,
                       help=f'Path to the prompt template file (default: {globals.PROMPT_TEMPLATE})')
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL,
                       help=f'Base URL of the LLM server (default: {globals.LLM_SERVER_URL})')
    parser.add_argument('--no-verify', action='store_true',
                        help="Skip automatic verification run after classification finishes.")
    parser.add_argument('--exit-on-complete', action='store_true',
                        help="Exit immediately when complete (for command-line usage). Default is to stay alive for web interface.")
    args = parser.parse_args()
    signal.signal(signal.SIGINT, globals.signal_handler)
    if args.mode == 'id' and args.paper_id is None:
        parser.error("--mode 'id' requires --paper_id to be specified.")
    
    success = run_classification(
        mode=args.mode,
        paper_id=args.paper_id,
        db_file=args.db_file,
        prompt_template=args.prompt_template,
        server_url=args.server_url
    )
    
    # NEW: Conditional verification run
    if success and not globals.is_shutdown_flag_set() and not args.no_verify and args.mode != 'consensus':
        print("\n--- Starting Automatic Verification ---")
        # Determine the verification mode based on the classification mode
        # 'remaining' and 'no_features' in classification might correspond to 'remaining' in verification
        # 'all' in classification corresponds to 'all' in verification
        # 'id' in classification means only that specific paper was classified, so verify only that ID if it was updated
        # 'on_topic_implementation' in classification might correspond to 'remaining' in verification (or could be 'all' if re-classified)
        # Using 'remaining' as default for verification seems safest after classification modes like 'remaining', 'no_features', 'on_topic_implementation'
        verification_mode = 'remaining' # Default
        verification_paper_id = None
        if args.mode == 'all':
            verification_mode = 'all'
        elif args.mode == 'id':
            # Only verify the specific paper ID if the classification run was successful
            verification_mode = 'id'
            verification_paper_id = args.paper_id
        # Call the verification run function directly
        verification_success = verify_classification.run_verification(
            mode=verification_mode,
            paper_id=verification_paper_id, # Will be None for modes other than 'id'
            db_file=args.db_file,
            prompt_template=globals.VERIFIER_TEMPLATE, # Use the dedicated verifier template
            server_url=args.server_url
        )
        if verification_success:
            print("\n--- Automatic Verification Completed Successfully ---")
        else:
            print("\n--- Automatic Verification Finished (Possibly with Errors or Shutdown) ---")
    elif args.no_verify:
        print("\n--- Automatic Verification Skipped as Requested (--no-verify) ---")
    elif args.mode == 'consensus':
        print("\n--- Consensus mode completed (verification already handled within consensus loop) ---")
    else:
        print("\n--- Skipping Automatic Verification due to Classification Failure or Shutdown ---")

    # At the very end, after all processing:
    if not success and not globals.is_shutdown_flag_set() and args.exit_on_complete:
        exit(1)

    # For web usage, don't close the prompt on finish so user can see what happened afterwards:
    if not hasattr(args, 'exit_on_complete') or not args.exit_on_complete:
        input("Press Enter to continue...")  # Only if running in interactive terminal