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
    # Extract latest classifier and verifier traces from llm_log
    latest_classifier_trace = ''
    latest_verifier_trace = ''
    try:
        llm_log = json.loads(paper_data.get('llm_log', '[]')) if paper_data.get('llm_log') else []
        # Find most recent classifier/consensus entry
        for entry in reversed(llm_log):
            if entry.get('type') in ['classifier', 'consensus'] and entry.get('valid'):
                latest_classifier_trace = entry.get('trace', '')
                break
        # Find most recent verifier entry
        for entry in reversed(llm_log):
            if entry.get('type') == 'verifier' and entry.get('valid'):
                latest_verifier_trace = entry.get('trace', '')
                break
    except (json.JSONDecodeError, TypeError):
        pass

    format_data = {
        'title': paper_data.get('title', ''),
        'abstract': paper_data.get('abstract', ''),
        'keywords': paper_data.get('keywords', ''),
        'authors': paper_data.get('authors', ''),
        'year': paper_data.get('year', ''),
        'type': paper_data.get('type', ''),
        'journal': paper_data.get('journal', ''),
        'previous_classification_json': json.dumps(classification_data, indent=2),
        'reasoning_trace': latest_classifier_trace,
        'verifier_trace': latest_verifier_trace,
        'estimated_score': paper_data.get('estimated_score', ''),
        'user_trace': paper_data.get('user_comments', '') or ''  # Assuming a user_comments field might exist
    }
    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"Error formatting reclassification prompt: Missing key {e} in paper data or template expects it.")
        raise

# automate_classification.py - Replace update_paper_from_llm function

def update_paper_from_llm(db_path, paper_id, llm_data, changed_by="LLM", reasoning_trace=None, success_flag=False, json_result_str="", model_name_used="Unknown"):
    """Updates paper classification fields and the continuous log in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # --- Fetch current state for logging ---
    cursor.execute("SELECT llm_log FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    if not row:
        print(f"Error: Paper {paper_id} not found for LLM update.")
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
        "type": "classifier",
        "model": model_name_used,
        "trace": reasoning_trace or "",
        "output": json_result_str if json_result_str else "{}",  # ← Never None/empty
        "valid": success_flag
    }
        
    # --- Append Log Entry ---
    existing_log.append(llm_log_entry)
    
    # --- Prepare Database Updates ---
    update_fields = []
    update_values = []
    
    if success_flag and llm_data:
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
        
        # Features (Merge with existing)
        if 'features' in llm_data and isinstance(llm_data['features'], dict):
            cursor.execute("SELECT features FROM papers WHERE id = ?", (paper_id,))
            row = cursor.fetchone()
            current_features = json.loads(row[0]) if row and row[0] else {}
            current_features.update(llm_data['features'])
            update_fields.append("features = ?")
            update_values.append(json.dumps(current_features))
        
        # Technique (Merge with existing)
        if 'technique' in llm_data and isinstance(llm_data['technique'], dict):
            cursor.execute("SELECT technique FROM papers WHERE id = ?", (paper_id,))
            row = cursor.fetchone()
            current_technique = json.loads(row[0]) if row and row[0] else {}
            current_technique.update(llm_data['technique'])
            update_fields.append("technique = ?")
            update_values.append(json.dumps(current_technique))
        
        # Reset verification fields on new classification
        update_fields.extend(["verified = ?", "estimated_score = ?", "verified_by = ?"])
        update_values.extend([None, None, ""])
        
        # Audit fields
        update_fields.extend(["changed = ?", "changed_by = ?"])
        update_values.extend([changed_timestamp, changed_by])
        
        # Reset user override count (LLM overwrites user state)
        update_fields.append("user_override_count = ?")
        update_values.append(0)
        
        # Update last_llm_* cache fields (mirror main field updates)
        for field in main_bool_fields:
            if field in llm_data:
                value = llm_data[field]
                update_fields.append(f"last_llm_{field} = ?")
                update_values.append(1 if value is True else 0 if value is False else None)
        
        if 'features' in llm_data and isinstance(llm_data['features'], dict):
            update_fields.append("last_llm_features = ?")
            update_values.append(json.dumps(current_features))
        if 'technique' in llm_data and isinstance(llm_data['technique'], dict):
            update_fields.append("last_llm_technique = ?")
            update_values.append(json.dumps(current_technique))
        if 'relevance' in llm_data:
            update_fields.append("last_llm_relevance = ?")
            update_values.append(llm_data['relevance'])
    else:
        # On failure, still update audit fields
        update_fields.extend(["changed = ?", "changed_by = ?"])
        update_values.extend([changed_timestamp, changed_by])
    
    # --- Update Database ---
    update_values.extend([json.dumps(existing_log), paper_id])
    update_query = f"UPDATE papers SET {', '.join(update_fields)}, llm_log = ? WHERE id = ?"
    cursor.execute(update_query, update_values)
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    
    return rows_affected > 0

def process_paper_worker(db_path, prompt_template_content, paper_id_queue, progress_lock, processed_count, total_papers, model_alias, reclassification_mode=False):
    """Worker function executed by each thread."""
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

        print(f"[Thread-{threading.get_ident()}] Processing paper ID: {paper_id}")

        try:
            paper_data = globals.get_paper_by_id(db_path, paper_id)
            if not paper_data:
                error_msg = f"Paper {paper_id} not found in DB."
                print(f"[Thread-{threading.get_ident()}] Error: {error_msg}")
                # Log the error
                update_paper_from_llm(
                    db_path,
                    paper_id,
                    {},
                    changed_by="Error",
                    reasoning_trace=error_msg,
                    success_flag=False,
                    json_result_str="",
                    model_name_used=model_alias
                )
                continue

            if reclassification_mode:
                prompt_text = build_reclassification_prompt(paper_data, prompt_template_content)
            else:
                prompt_text = build_prompt(paper_data, prompt_template_content)

            if globals.is_shutdown_flag_set():
                return

            # --- LLM Call ---
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                prompt_text,
                server_url_base=globals.LLM_SERVER_URL,
                model_name=model_alias,
                is_verification=False
            )

            if globals.is_shutdown_flag_set():
                return

            # --- Process Result (Success OR Failure) ---
            if json_result_str:
                try:
                    llm_classification = json.loads(json_result_str)
                    if reasoning_trace:
                        reasoning_trace = f"As classified by {model_name_used}\n{reasoning_trace}"
                    else:
                        reasoning_trace = f"As classified by {model_name_used}"

                    success = update_paper_from_llm(
                        db_path,
                        paper_id,
                        llm_classification,
                        changed_by=model_name_used,
                        reasoning_trace=reasoning_trace,
                        success_flag=True,
                        json_result_str=json_result_str,
                        model_name_used=model_name_used
                    )

                    if success:
                        print(f"[Thread-{threading.get_ident()}] Updated paper {paper_id} (Model: {model_name_used})")
                    else:
                        print(f"[Thread-{threading.get_ident()}] Failed to update paper {paper_id} (DB error)")

                except json.JSONDecodeError as e:
                    error_msg = f"Error parsing LLM output: {str(e)}\n\nLLM Output:\n{json_result_str}"
                    print(f"[Thread-{threading.get_ident()}] {error_msg}")
                    # Log the parsing error
                    update_paper_from_llm(
                        db_path,
                        paper_id,
                        {},
                        changed_by=model_name_used,
                        reasoning_trace=error_msg,
                        success_flag=False,
                        json_result_str=json_result_str,
                        model_name_used=model_name_used
                    )
            else:
                # --- LLM Call Failed (No Response) ---
                error_msg = "No LLM response received. Check server connection."
                print(f"[Thread-{threading.get_ident()}] {error_msg}")
                # Log the failure
                update_paper_from_llm(
                    db_path,
                    paper_id,
                    {},
                    changed_by=model_name_used,
                    reasoning_trace=error_msg,
                    success_flag=False,
                    json_result_str="",
                    model_name_used=model_name_used
                )

        except Exception as e:
            error_msg = f"Exception during processing: {type(e).__name__}: {str(e)}"
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] {error_msg}")
            # Log the exception as a failure
            update_paper_from_llm(
                db_path,
                paper_id,
                {},
                changed_by="Error",
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
    
    start_time = time.time()

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
            
        # Log batch start
        globals.log_performance_event('classification_batch_start', {
            'mode': mode,
            'total_papers': total_papers,
            'model_alias': model_alias,
            'max_concurrent_workers': globals.MAX_CONCURRENT_WORKERS
        })
        
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
    print(f"Starting ThreadPoolExecutor with up to {globals.MAX_CONCURRENT_WORKERS} workers...")
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
        
        # Log batch completion
        globals.log_performance_event('classification_batch_complete', {
            'mode': mode,
            'papers_total': total_papers,
            'papers_processed': final_count,
            'duration_seconds': end_time - start_time,
            'model_alias': model_alias
        })
        
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
    consensus_start_time = time.time()
    iteration = 0
    total_consensus_papers = 0
    consensus_iterations = []

    while True:
        iteration += 1
        print(f"\n--- Consensus Iteration {iteration} ---")
            
            
        # --- NEW: Check iteration limit ---
        if iteration > globals.MAX_CONSENSUS_ITERATIONS:
            print(f"\nConsensus iteration limit ({globals.MAX_CONSENSUS_ITERATIONS}) reached.")
            # Export problematic papers for analysis
            return False
        
        # --- NEW: Fresh classification fallback ---
        if iteration == globals.FRESH_CLASSIFY_FALLBACK_ITERATION:
            print(f"\nIteration {iteration}: Switching to fresh classification (breaking consensus loop). This may fix stuck papers.")
            globals.log_performance_event('consensus_fresh_fallback', {
                'iteration': iteration,
                'papers_affected': len(misclassified_paper_ids),
                'paper_ids': misclassified_paper_ids
            })
            
            # Run fresh classification instead of consensus prompt
            fresh_classify_success = run_classification(
                mode='id',  # Only re-classify the stuck papers
                paper_id=None,  # Will use misclassified_paper_ids
                db_file=db_file,
                prompt_template=globals.PROMPT_TEMPLATE,  # Normal classifier prompt, NOT consensus
                server_url=server_url
            )
            
            # Then verify the fresh classifications
            verify_classification.run_verification(
                mode='remaining',
                db_file=db_file,
                prompt_template=globals.VERIFIER_TEMPLATE,
                server_url=server_url
            )
            
            # Continue normal consensus check after fallback
            continue
        

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
        

        # Log consensus iteration
        globals.log_performance_event('consensus_iteration', {
            'iteration': iteration,
            'papers_remaining': len(misclassified_paper_ids),
            'papers_processed_this_iteration': len(misclassified_paper_ids)
        })
        
        consensus_iterations.append({
            'iteration': iteration,
            'papers_remaining': len(misclassified_paper_ids)
        })
        

        if not misclassified_paper_ids:
            print("No more misclassified papers found. Consensus reached!")
            
            # Log consensus complete
            consensus_end_time = time.time()
            globals.log_performance_event('consensus_complete', {
                'total_iterations': iteration,
                'total_duration_seconds': consensus_end_time - consensus_start_time,
                'iterations_detail': consensus_iterations,
                'model_alias': globals.get_model_alias(server_url)
            })
            
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
            
            # Log consensus aborted
            globals.log_performance_event('consensus_aborted', {
                'iterations_completed': iteration,
                'papers_remaining': len(misclassified_paper_ids),
                'total_duration_seconds': time.time() - consensus_start_time,
                'iterations_detail': consensus_iterations
            })
            
            return False
        
def run_reclassification_batch(paper_ids, db_file, server_url):
    """
    Runs reclassification on a batch of paper IDs.
    """
    total_papers = len(paper_ids)
    if total_papers == 0:
        print("No papers to reclassify in this batch.")
        return True
    
    start_time = time.time()
    
    # Log reclassification batch start
    globals.log_performance_event('reclassification_batch_start', {
        'papers_total': total_papers,
        'max_concurrent_workers': globals.MAX_CONCURRENT_WORKERS_CONSENSUS
    })
    
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
        
        # Log reclassification batch complete
        globals.log_performance_event('reclassification_batch_complete', {
            'papers_total': total_papers,
            'papers_processed': final_count,
            'duration_seconds': end_time - start_time,
            'model_alias': model_alias
        })
        
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