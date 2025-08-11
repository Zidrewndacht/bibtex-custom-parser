# verify_classification.py
import sqlite3
import json
import argparse
import requests
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import signal
import globals  # Import for global settings and shared functions

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

def update_paper_verification(db_path, paper_id, verification_result, verified_by="LLM", reasoning_trace=None):
    """
    Updates the verification fields (verified, estimated_score, verified_by, verifier_trace)
    in the database for a specific paper.
    Does NOT update 'changed' or 'changed_by' as per requirements.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    verified = verification_result.get('verified')
    # Normalize verified value to database format (1, 0, None)
    if verified is True:
        verified_db_value = 1
    elif verified is False:
        verified_db_value = 0
    else: # None or anything else
        verified_db_value = None

    estimated_score = verification_result.get('estimated_score')
    # Ensure estimated_score is an integer within 0-100 or None
    if isinstance(estimated_score, (int, float)):
        estimated_score_db_value = max(0, min(100, int(estimated_score)))
    else:
        estimated_score_db_value = None

    # --- Prepare update fields and values ---
    update_fields = ["verified = ?", "estimated_score = ?", "verified_by = ?"]
    update_values = [verified_db_value, estimated_score_db_value, verified_by]

    # --- Add verifier_trace if provided ---
    if reasoning_trace is not None:
        update_fields.append("verifier_trace = ?")
        update_values.append(reasoning_trace)

    # --- Construct and execute the query ---
    update_query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
    update_values.append(paper_id) # Add paper_id for the WHERE clause

    try:
        cursor.execute(update_query, update_values) # Pass the combined list of values
        conn.commit()
        rows_affected = cursor.rowcount
    except Exception as e:
        print(f"[Thread-{threading.get_ident()}] Error updating verification for paper {paper_id}: {e}")
        rows_affected = 0
    finally:
        conn.close()
    return rows_affected > 0

def send_verification_prompt_to_llm(prompt_text, grammar_text=None, server_url_base=globals.LLM_SERVER_URL, model_name="default"):
    """
    Sends a verification prompt to the LLM via the OpenAI-compatible API.
    Returns (content_str, model_name_used, reasoning_trace).
    """
    chat_url = f"{server_url_base.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.6,
        "top_p": 0.95, 
        "top_k": 20, 
        "min_p":0,
        "max_tokens": 32768,
        "stream": False
    }
    if grammar_text:
        payload["grammar"] = grammar_text
    try:
        if globals.is_shutdown_flag_set():
            return None, None, None
        response = requests.post(chat_url, headers=headers, json=payload, timeout=600)
        if globals.is_shutdown_flag_set():
            return None, None, None
        response.raise_for_status()
        response_data = response.json()
        
        # Print raw response for debugging
        # print(f"[DEBUG] Raw LLM response: {json.dumps(response_data, indent=2)}")
        
        model_name_from_response = response_data.get('model', model_name)
        if 'choices' in response_data and response_data['choices']:
            # --- Extract reasoning_content more safely ---
            reasoning_content = None
            message = response_data['choices'][0]['message']
            if 'reasoning_content' in message:
                reasoning_content = message.get('reasoning_content', '').strip()
            content = message.get('content', '').strip()
            return content, model_name_from_response, reasoning_content
        else:
            print(f"Warning: Unexpected LLM verification response structure: {response_data}")
            return None, model_name_from_response, None
    except requests.exceptions.RequestException as e:
        if globals.is_shutdown_flag_set():
            return None, None, None
        print(f"Error sending verification request to LLM server: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response Text: {e.response.text}")
        return None, None, None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON verification response: {e}")
        if 'response' in locals():
            print(f"Response Text: {response.text}")
        return None, None, None
    except KeyError as e:
        print(f"Unexpected verification response structure, missing key: {e}")
        print(f"Response Data: {response_data}")
        return None, None, None

def process_paper_verification_worker(
    db_path, 
    grammar_content, 
    verification_prompt_template_content, 
    paper_id_queue, 
    progress_lock, 
    processed_count, 
    total_papers, 
    model_alias
):
    """Worker function executed by each thread for verification."""
    while True:
        if globals.is_shutdown_flag_set():
            return
        try:
            paper_id = paper_id_queue.get_nowait()
        except queue.Empty:
            if globals.is_shutdown_flag_set():
                return
            time.sleep(0.1)
            continue

        print(f"[Thread-{threading.get_ident()}] Verifying paper ID: {paper_id}")
        try:
            # 1. Fetch paper data and current classification from DB
            paper_data = globals.get_paper_by_id(db_path, paper_id)
            if not paper_data:
                print(f"[Thread-{threading.get_ident()}] Error: Paper {paper_id} not found in DB for verification.")
                continue

            # Prepare classification data for the prompt
            # Parse JSON fields back into dicts for the prompt builder
            classification_data = {}
            bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
            for field in bool_fields:
                 # Convert DB integers (1,0,None) back to boolean/None for prompt clarity
                db_val = paper_data.get(field)
                if db_val == 1:
                    classification_data[field] = True
                elif db_val == 0:
                    classification_data[field] = False
                else: # None or unexpected
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
            
            # Print prompt for debugging (first few chars)
            # print(f"[DEBUG] Prompt for {paper_id}: {prompt_text[:200]}...")

            if globals.is_shutdown_flag_set():
                return

            # 3. Send prompt to LLM
            json_result_str, model_name_used, reasoning_trace = send_verification_prompt_to_llm(
                prompt_text,
                grammar_text=grammar_content,
                server_url_base=globals.LLM_SERVER_URL,
                model_name=model_alias
            )

            if globals.is_shutdown_flag_set():
                return

            # 4. Process LLM response
            if json_result_str:
                # print(f"[DEBUG] Raw LLM output for {paper_id}: {json_result_str}")
                try:
                    llm_verification_result = json.loads(json_result_str)
                    # 5. Update database with verification result

                    success = update_paper_verification(
                        db_path,
                        paper_id,
                        llm_verification_result,
                        verified_by=model_name_used,
                        reasoning_trace=reasoning_trace # Pass the reasoning_trace
                    )
                    if success:
                        print(f"[Thread-{threading.get_ident()}] Verified paper {paper_id} (Model: {model_name_used})")
                    else:
                        print(f"[Thread-{threading.get_ident()}] No verification changes or error for paper {paper_id}")
                except json.JSONDecodeError as e:
                    print(f"[Thread-{threading.get_ident()}] Error parsing LLM verification output for {paper_id}: {e}")
                    print(f"LLM Output: {json_result_str}")
                except Exception as e:
                    print(f"[Thread-{threading.get_ident()}] Error updating DB verification for {paper_id}: {e}")
            else:
                if not globals.is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No LLM verification response for {paper_id}")

        except Exception as e:
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error verifying {paper_id}: {e}")
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Progress] Verified {processed_count[0]}/{total_papers} papers.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verify LLM classifications for papers in the database.')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--grammar_file', '-g', default=globals.GRAMMAR_FILE, # Might use same grammar or a different one
                       help=f'Path to the GBNF grammar file (default: {globals.GRAMMAR_FILE})')
    parser.add_argument('--prompt_template', '-t', default=globals.VERIFIER_TEMPLATE,
                       help=f'Path to the verification prompt template file (default: {globals.VERIFIER_TEMPLATE})')
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL,
                       help=f'Base URL of the LLM server (default: {globals.LLM_SERVER_URL})')
    args = parser.parse_args()

    if not os.path.exists(args.db_file):
        print(f"Error: Database file '{args.db_file}' not found.")
        exit(1)

    try:
        verification_prompt_template_content = globals.load_prompt_template(args.prompt_template)
        print(f"Loaded verification prompt template from '{args.prompt_template}'")
    except Exception as e:
        print(f"Error loading verification prompt template: {e}")
        exit(1)

    # Use the signal handler from globals for graceful shutdown
    signal.signal(signal.SIGINT, globals.signal_handler)

    grammar_content = None
    if args.grammar_file:
        try:
            grammar_content = globals.load_grammar(args.grammar_file)
            print(f"Loaded GBNF grammar from '{args.grammar_file}' for verification")
        except Exception as e:
            print(f"Warning: Error reading grammar file for verification: {e}")
            # Not exiting, verification might work without strict grammar, but likely needs it.
            # Consider making grammar mandatory for verification if the output must be strict JSON.
            # exit(1)

    print("Fetching model alias from LLM server for verification...")
    model_alias = globals.get_model_alias(args.server_url)
    if not model_alias:
        print("Error: Could not determine model alias for verification. Exiting.")
        exit(1)

    print(f"Connecting to database '{args.db_file}' to fetch papers for verification...")
    try:
        conn = sqlite3.connect(args.db_file)
        cursor = conn.cursor()
        # Only fetch papers that have been classified but not yet verified
        cursor.execute("""
            SELECT id 
            FROM papers 
            WHERE (changed_by IS NOT NULL AND changed_by != '') 
            AND (verified_by IS NULL OR verified_by = '')
        """)        
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        total_papers = len(paper_ids)
        print(f"Found {total_papers} classified but unverified papers to verify.")
    except Exception as e:
        print(f"Error fetching paper IDs: {e}")
        exit(1)
        
    if not paper_ids:
        print("No papers found in database for verification. Exiting.")
        exit(0)

    paper_id_queue = queue.Queue()
    for pid in paper_ids:
        paper_id_queue.put(pid)

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers for verification...")
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                executor.submit(
                    process_paper_verification_worker,
                    args.db_file,
                    grammar_content,
                    verification_prompt_template_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias
                )
            print("Verification processing started. Press Ctrl+C to abort.")
            while True:
                time.sleep(0.1)
    except Exception as e:
        print(f"Error in main verification execution: {e}")
        os._exit(1) # Force exit on unexpected errors in main thread
    finally:
        end_time = time.time()
        with progress_lock:
            final_count = processed_count[0]
        print(f"\n--- Verification Summary ---")
        print(f"Papers verified: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Verification Done.")