import sqlite3
import json
import argparse
import requests
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import threading
import signal
import globals

# --- Global Flag for Instant Shutdown (using Lock for atomicity) ---
# Using a simple boolean guarded by a lock for absolute immediacy
shutdown_lock = threading.Lock()
shutdown_flag = False

def set_shutdown_flag():
    """Sets the global shutdown flag to True in a thread-safe manner."""
    global shutdown_flag
    with shutdown_lock:
        shutdown_flag = True

def is_shutdown_flag_set():
    """Checks the global shutdown flag in a thread-safe manner."""
    global shutdown_flag
    with shutdown_lock:
        return shutdown_flag

def get_model_alias(server_url_base):
    """Fetches the model alias from the LLM server's /v1/models endpoint."""
    models_url = f"{server_url_base.rstrip('/')}/v1/models" # Ensure correct URL construction
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.get(models_url, headers=headers, timeout=30)
        response.raise_for_status()
        models_data = response.json()

        # Assuming the server returns a list under 'data' and there's only one model
        if 'data' in models_data and isinstance(models_data['data'], list) and len(models_data['data']) > 0:
            model_alias = models_data['data'][0].get('id')
            if model_alias:
                print(f"Detected model alias from server: '{model_alias}'")
                return model_alias
            else:
                print(f"Warning: Model entry found but 'id' field is missing or empty: {models_data['data'][0]}")
        else:
             print(f"Warning: Unexpected response structure from /v1/models endpoint: {models_data}")

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to LLM server models endpoint ({models_url}): {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response Text: {e.response.text}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from LLM server models endpoint: {e}")
        print(f"Response Text: {response.text}")
    except KeyError as e:
        print(f"Unexpected response structure from LLM server models endpoint, missing key: {e}")
        print(f"Response Data: {models_data}")

    fallback_alias = "Unknown_LLM"
    print(f"Could not determine model alias. Using fallback: '{fallback_alias}'")
    return fallback_alias


def load_prompt_template(template_path):
    """Loads the prompt template from a file."""
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Prompt template file '{template_path}' not found.")
        raise
    except Exception as e:
        print(f"Error reading prompt template file '{template_path}': {e}")
        raise

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
        # Add other fields if needed in the template
    }
    try:
        return template_content.format(**format_data)
    except KeyError as e:
        print(f"Error formatting prompt: Missing key {e} in paper data or template expects it.")
        raise

def get_paper_by_id(db_path, paper_id):
    """Fetches a single paper's data from the database by its ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_paper_from_llm(db_path, paper_id, llm_data, changed_by="LLM"):
    """Updates paper classification fields in the database based on LLM output."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    # --- Prepare fields for update ---
    update_fields = []
    update_values = []
    # --- Handle Main Boolean Fields ---
    main_bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in main_bool_fields:
        if field in llm_data:
            value = llm_data[field]
            # Convert LLM output (True/False/None) to DB format (1/0/None)
            if value is True:
                update_fields.append(f"{field} = ?")
                update_values.append(1)
            elif value is False:
                update_fields.append(f"{field} = ?")
                update_values.append(0)
            else: # None or unexpected
                update_fields.append(f"{field} = ?")
                update_values.append(None)
    # --- Handle Research Area ---
    if 'research_area' in llm_data:
        update_fields.append("research_area = ?")
        update_values.append(llm_data['research_area'])
    # --- Handle Features ---
    # Fetch current features to merge
    cursor.execute("SELECT features FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    try:
        current_features = json.loads(row[0]) if row and row[0] else {}
    except (json.JSONDecodeError, TypeError):
        current_features = {}
    # Update features from LLM data
    if 'features' in llm_data and isinstance(llm_data['features'], dict):
        current_features.update(llm_data['features'])
        update_fields.append("features = ?")
        update_values.append(json.dumps(current_features))
    # --- Handle Techniques ---
    # Fetch current technique to merge
    cursor.execute("SELECT technique FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    try:
        current_technique = json.loads(row[0]) if row and row[0] else {}
    except (json.JSONDecodeError, TypeError):
        current_technique = {}
    # Update technique from LLM data
    if 'technique' in llm_data and isinstance(llm_data['technique'], dict):
        current_technique.update(llm_data['technique'])
        update_fields.append("technique = ?")
        update_values.append(json.dumps(current_technique))
    # --- Always update audit fields for any change made by LLM ---
    update_fields.append("changed = ?")
    update_values.append(changed_timestamp)
    update_fields.append("changed_by = ?")
    update_values.append(changed_by) # This will now be the actual model alias
    # --- Perform Update ---
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

def send_prompt_to_llm(prompt_text, grammar_text=None, server_url=globals.LLM_SERVER_URL, model_name="default"):
    """Sends a prompt to the LLM via the OpenAI-compatible API. Returns (content_str, model_name_used)."""
    # Note: model_name is now passed correctly from the main script
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model_name, # Use the actual model name/alias
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.0,
        "max_tokens": 1000,
        "stream": False
    }
    if grammar_text:
        payload["grammar"] = grammar_text
    try:
        # Check for instant shutdown before sending request
        if is_shutdown_flag_set():
            return None, None
        response = requests.post(server_url, headers=headers, json=payload, timeout=60)
        if is_shutdown_flag_set():
            return None, None
        response.raise_for_status()
        response_data = response.json()
        # We still get the model name from the response, but now we also know it should match model_name
        model_name_from_response = response_data.get('model', model_name) # Fallback to passed name if not in response
        if 'choices' in response_data and len(response_data['choices']) > 0:
            content = response_data['choices'][0]['message']['content'].strip()
            return content, model_name_from_response
        else:
            print(f"Warning: Unexpected LLM response structure: {response_data}")
            return None, model_name_from_response
    except requests.exceptions.RequestException as e:
        if is_shutdown_flag_set():
             return None, None
        print(f"Error sending request to LLM server: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response Text: {e.response.text}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from LLM server: {e}")
        print(f"Response Text: {response.text}")
        return None, None
    except KeyError as e:
        print(f"Unexpected response structure from LLM server, missing key: {e}")
        print(f"Response Data: {response_data}")
        return None, None

def signal_handler(sig, frame):
    print("\nReceived Ctrl+C. Killing all threads...")
    # Set the flag first so any threads that check it mid-execution know to stop
    set_shutdown_flag()
    os._exit(1)

def process_paper_worker(db_path, grammar_content, prompt_template_content, paper_id_queue, progress_lock, processed_count, total_papers, model_alias):
    """Worker function executed by each thread. Takes model_alias as an argument."""
    while True:
        if is_shutdown_flag_set():
            return # Just return, the process will die anyway
        try:
            # Non-blocking get, but check the flag instantly if empty
            paper_id = paper_id_queue.get_nowait() # Use nowait to fail fast
        except queue.Empty:
             if is_shutdown_flag_set():
                 return
             else:
                 time.sleep(0.1)
                 continue # Go back to the beginning of the loop to check flag again
        if is_shutdown_flag_set(): return
        print(f"[Thread-{threading.get_ident()}] Processing paper ID: {paper_id}")
        try:
            paper_data = get_paper_by_id(db_path, paper_id)
            if not paper_data:
                print(f"[Thread-{threading.get_ident()}] Error: Paper {paper_id} not found in DB.")
                if is_shutdown_flag_set(): return
                continue # Go back to the top of the while loop
            prompt_text = build_prompt(paper_data, prompt_template_content)
            if is_shutdown_flag_set(): return
            json_result_str, model_name_used = send_prompt_to_llm(prompt_text, grammar_text=grammar_content, server_url=globals.LLM_SERVER_URL, model_name=model_alias)
            if is_shutdown_flag_set(): return # Check again after potentially long LLM call
            if json_result_str:
                try:
                    llm_classification = json.loads(json_result_str)
                    # Pass the model_name_used (which should be the alias) as changed_by
                    success = update_paper_from_llm(db_path, paper_id, llm_classification, changed_by=model_name_used)
                    if success:
                        print(f"[Thread-{threading.get_ident()}] Successfully updated database for paper ID: {paper_id} (Model: {model_name_used})")
                    else:
                        print(f"[Thread-{threading.get_ident()}] Database update reported no changes for paper ID: {paper_id} (Model: {model_name_used})")
                except json.JSONDecodeError as e:
                    print(f"[Thread-{threading.get_ident()}] Error parsing LLM JSON output for paper {paper_id}: {e}")
                    print(f"[Thread-{threading.get_ident()}] LLM Output was: {json_result_str}")
                except Exception as e:
                     print(f"[Thread-{threading.get_ident()}] Unexpected error updating DB for paper {paper_id}: {e}")
            else:
                if not is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] Failed to get valid response from LLM for paper ID: {paper_id}")
        except Exception as e:
            if not is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Unexpected error processing paper {paper_id}: {e}")
        finally:
            if is_shutdown_flag_set(): return
            with progress_lock:
                if is_shutdown_flag_set(): return # Flag checked again
                processed_count[0] += 1
                print(f"[Progress] Processed {processed_count[0]}/{total_papers} papers.")
            # DO NOT call paper_id_queue.task_done() anymore, we ignore the queue's internal count now

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification for all papers in the database.')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('--grammar_file', '-g', help='Path to the GBNF grammar file to constrain the output format')
    parser.add_argument('--prompt_template', '-t', default='prompt_template.txt', help='Path to the prompt template file (default: prompt_template.txt)')
    # Note: server_url is used for chat completions, but base URL is needed for /models
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL, help='URL of the LLM server endpoint (default: http://localhost:8080/v1/chat/completions)')
    args = parser.parse_args()

    if not os.path.exists(args.db_file):
        print(f"Error: Database file '{args.db_file}' not found.")
        exit(1)

    try:
        prompt_template_content = load_prompt_template(args.prompt_template)
        print(f"Loaded prompt template from '{args.prompt_template}'")
    except Exception:
        exit(1)

    # --- Register the BRUTAL signal handler for Ctrl+C ---
    signal.signal(signal.SIGINT, signal_handler)

    grammar_content = None
    if args.grammar_file:
        try:
            with open(args.grammar_file, 'r', encoding='utf-8') as f:
                grammar_content = f.read()
            print(f"Loaded GBNF grammar from '{args.grammar_file}'")
        except FileNotFoundError:
            print(f"Error: Grammar file '{args.grammar_file}' not found.")
            exit(1)
        except Exception as e:
            print(f"Error reading grammar file '{args.grammar_file}': {e}")
            exit(1)

    # --- Get Model Alias BEFORE processing ---
    print("Fetching model alias from LLM server...")
    # Derive base URL for /models endpoint from the chat completions URL
    # This handles cases like http://localhost:8080/v1/chat/completions -> http://localhost:8080
    base_server_url = args.server_url.split('/v1/chat/completions')[0] if '/v1/chat/completions' in args.server_url else args.server_url
    model_alias = get_model_alias(base_server_url)
    if not model_alias:
         print("Critical Error: Could not determine model alias. Exiting.")
         exit(1)


    print(f"Connecting to database '{args.db_file}'...")
    try:
        conn = sqlite3.connect(args.db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM papers")
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        total_papers = len(paper_ids)
        print(f"Found {total_papers} papers to process.")
    except Exception as e:
        print(f"Error fetching paper IDs from database: {e}")
        exit(1)

    if total_papers == 0:
        print("No papers found in the database matching criteria. Exiting.")
        exit(0)

    # --- Create Queue and Populate ---
    paper_id_queue = queue.Queue()
    for pid in paper_ids:
        paper_id_queue.put(pid)

    # --- Shared variables for progress tracking ---
    progress_lock = threading.Lock()
    processed_count = [0]

    # --- Start ThreadPoolExecutor (NO WAITING LOGIC) ---
    print(f"Starting ThreadPoolExecutor with max {globals.MAX_CONCURRENT_WORKERS} workers...")
    start_time = time.time()
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            # Submit worker tasks, passing the model_alias
            for i in range(globals.MAX_CONCURRENT_WORKERS):
                 executor.submit(
                     process_paper_worker,
                     args.db_file,
                     grammar_content,
                     prompt_template_content,
                     paper_id_queue,
                     progress_lock,
                     processed_count,
                     total_papers,
                     model_alias # Pass the model alias to workers
                 )
            print("Processing started. Press Ctrl+C to kill all threads.")
            while True:
                time.sleep(0.1) # Sleep to prevent busy-waiting in the main thread
    except Exception as e:
        print(f"An error occurred in the main execution block: {e}")
        os._exit(1)
    finally:
        end_time = time.time()
        with progress_lock:
            final_count = processed_count[0]
        print(f"\n--- Automation Summary ---")
        print(f"Papers processed: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds.")
        print("Automation complete (if you see this, it exited normally).")
        print("--------------------------")
