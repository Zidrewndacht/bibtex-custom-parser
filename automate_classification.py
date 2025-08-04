# automate_classification.py
import sqlite3
import json
import argparse
import requests
import time
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import threading
import signal

# --- Configuration ---
# These match the structures from your other scripts
DEFAULT_FEATURES = {
    "solder": None,
    "polarity": None,
    "wrong_component": None,
    "missing_component": None,
    "tracks": None,
    "holes": None,
    "other": None
}
DEFAULT_TECHNIQUE = {
    "classic_computer_graphics_based": None,
    "machine_learning_based": None,
    "hybrid": None,
    "model": None,
    "available_dataset": None
}

YAML_TEMPLATE = """research_area: null #broad area: electrical engineering, computer sciences, medical, finances, etc, can be inferred by journal or conference name as well as contents.
is_survey: false #true for survey/review/etc., false for implementations, new research, etc.
is_offtopic: false #true if paper seems entirely unrelated to the field (e.g. an exobiology paper that got through by mistake).  If offtopic, answer null for all fields following this one.
is_through_hole: true #true for papers that specify PTH, THT, etc., through-hole component mounting
is_smt: true #true for papers that specify surface-mount compoent mounting (SMD, SMT)
is_x_ray: null  #true for X-ray inspection, false for standard optical (visible light) inspection
features:  # true, false, null for unknown
    solder: null
    polarity: null
    wrong_component: null
    missing_component: null
    tracks: null	#any track error detection: split, short, etc.
    holes: null
    other: null 	#"string with other types of error detection"
technique:
    classic_computer_graphics_based: null
    machine_learning_based: null
    hybrid: null
    model: "name"	#comma-separated list if multiple models are used (YOLO, ResNet, DETR, etc.), null if not ML, "in-house" if unnamed ML model is developed in the paper itself.
available_dataset: null #true if authors provide the datasets for the public, false if there are no datasets or if they're not provided
"""

LLM_SERVER_URL = "http://localhost:8080/v1/chat/completions" # Default endpoint
MAX_CONCURRENT_WORKERS = 18 # Match your server slots

# --- Global Flag for Shutdown ---
shutdown_event = threading.Event()

# --- Functions from build_prompt.py (adapted for direct use) ---
def build_prompt(paper_data):
    """Builds the prompt string for a single paper."""
    title = paper_data.get('title', '')
    abstract = paper_data.get('abstract', '')
    keywords = paper_data.get('keywords', '')
    authors = paper_data.get('authors', '')
    year = paper_data.get('year', '')
    type = paper_data.get('type', '')
    journal = paper_data.get('journal', '')

    prompt_lines = [
        "Read the following paper title, abstract and keywords:",
        f"Title: {title}",
        f"Abstract: {abstract}",
        f"Keywords: {keywords}",
        f"Authors: {authors}",
        f"Publication Year: {str(year)}",
        f"Publication Type: {type}",
        f"Publication Name: {journal}",
        "Given the contents of the paper, fill in the following YAML structure exactly and convert it to JSON. Do not add, remove or move any fields.",
        "Only write 'true' or 'false' if the contents above make it clear that it is the case. If unsure, fill the field with null:",
        "The example below is not related to the paper above, use it only as a reference for the structure itself.",
        "",
        YAML_TEMPLATE.strip(),
        "",
        "Your response is not being read by a human, it is grammar-locked via GBNF and goes directly to an automated parser. Answer with nothing but the structure itself directly. Output in JSON format"
    ]
    return "\n".join(prompt_lines)

def get_paper_by_id(db_path, paper_id):
    """Fetches a single paper's data from the database by its ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# --- Database Update Function (adapted from browse_db.py) ---
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
    update_values.append(changed_by)

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

# --- LLM Interaction Function ---
def send_prompt_to_llm(prompt_text, grammar_text=None, server_url=LLM_SERVER_URL, model_name="default"):
    """Sends a prompt to the LLM via the OpenAI-compatible API."""
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.0, # Lower temp for more deterministic output
        "max_tokens": 1000,
        "stream": False # Ensure we get the full response at once
    }
    if grammar_text:
        payload["grammar"] = grammar_text

    try:
        # Check for shutdown before sending request
        if shutdown_event.is_set():
            return None
        response = requests.post(server_url, headers=headers, json=payload, timeout=300) # Add timeout
        # Check for shutdown after receiving response
        if shutdown_event.is_set():
            return None
        response.raise_for_status()
        response_data = response.json()
        if 'choices' in response_data and len(response_data['choices']) > 0:
            return response_data['choices'][0]['message']['content'].strip()
        else:
            print(f"Warning: Unexpected LLM response structure: {response_data}")
            return None
    except requests.exceptions.RequestException as e:
        if shutdown_event.is_set():
             # Likely due to shutdown, suppress error
             return None
        print(f"Error sending request to LLM server: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response Text: {e.response.text}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from LLM server: {e}")
        print(f"Response Text: {response.text}")
        return None
    except KeyError as e:
        print(f"Unexpected response structure from LLM server, missing key: {e}")
        print(f"Response Data: {response_data}")
        return None

# --- Signal Handler for Graceful Shutdown ---
def signal_handler(sig, frame):
    print("\nReceived interrupt signal (Ctrl+C). Requesting shutdown...")
    shutdown_event.set() # Signal all threads to stop

# --- Worker Function for ThreadPoolExecutor ---
def process_paper_worker(db_path, grammar_content, paper_id_queue, progress_lock, processed_count, total_papers):
    """Worker function executed by each thread."""
    while not shutdown_event.is_set():
        try:
            # Non-blocking get with timeout to allow checking shutdown_event
            paper_id = paper_id_queue.get(timeout=1)
        except queue.Empty:
            # If queue is empty for timeout duration, check if we should exit
            continue # Go back to the loop condition check

        if shutdown_event.is_set():
            paper_id_queue.task_done() # Ensure task is marked done even if skipped
            break

        print(f"[Thread-{threading.get_ident()}] Processing paper ID: {paper_id}")
        try:
            paper_data = get_paper_by_id(db_path, paper_id)
            if not paper_data:
                print(f"[Thread-{threading.get_ident()}] Error: Paper {paper_id} not found in DB.")
                paper_id_queue.task_done()
                continue

            prompt_text = build_prompt(paper_data)
            
            # Check for shutdown before sending
            if shutdown_event.is_set():
                paper_id_queue.task_done()
                break

            json_result_str = send_prompt_to_llm(prompt_text, grammar_text=grammar_content, server_url=LLM_SERVER_URL, model_name="default")

            # Check for shutdown after sending
            if shutdown_event.is_set():
                paper_id_queue.task_done()
                break

            if json_result_str:
                try:
                    # Attempt to parse the LLM's output as JSON
                    llm_classification = json.loads(json_result_str)
                    # Update the database with the parsed data
                    success = update_paper_from_llm(db_path, paper_id, llm_classification, changed_by="LLM")
                    if success:
                        print(f"[Thread-{threading.get_ident()}] Successfully updated database for paper ID: {paper_id}")
                    else:
                        print(f"[Thread-{threading.get_ident()}] Database update reported no changes for paper ID: {paper_id}")
                except json.JSONDecodeError as e:
                    print(f"[Thread-{threading.get_ident()}] Error parsing LLM JSON output for paper {paper_id}: {e}")
                    print(f"[Thread-{threading.get_ident()}] LLM Output was: {json_result_str}")
                except Exception as e: # Catch potential DB errors
                     print(f"[Thread-{threading.get_ident()}] Unexpected error updating DB for paper {paper_id}: {e}")
            else:
                if not shutdown_event.is_set(): # Only report failure if not shutting down
                    print(f"[Thread-{threading.get_ident()}] Failed to get valid response from LLM for paper ID: {paper_id}")

        except Exception as e:
            if not shutdown_event.is_set(): # Only report unexpected errors if not shutting down
                print(f"[Thread-{threading.get_ident()}] Unexpected error processing paper {paper_id}: {e}")

        finally:
            # Mark the task as done in the queue
            paper_id_queue.task_done()
            # Safely increment and report progress
            with progress_lock:
                processed_count[0] += 1 # Increment the shared counter
                print(f"[Progress] Processed {processed_count[0]}/{total_papers} papers.")

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification for all papers in the database.')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('--grammar_file', '-g', help='Path to the GBNF grammar file to constrain the output format')
    parser.add_argument('--server_url', default=LLM_SERVER_URL, help='URL of the LLM server endpoint (default: http://localhost:8080/v1/chat/completions)')
    args = parser.parse_args()

    if not os.path.exists(args.db_file):
        print(f"Error: Database file '{args.db_file}' not found.")
        exit(1)

    # --- Register signal handler for Ctrl+C ---
    signal.signal(signal.SIGINT, signal_handler)
    print("Press Ctrl+C to stop processing gracefully.")

    # --- Read GBNF Grammar if file is provided ---
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
    # --- End GBNF Reading ---

    # --- Fetch all paper IDs ---
    print(f"Connecting to database '{args.db_file}'...")
    try:
        conn = sqlite3.connect(args.db_file)
        cursor = conn.cursor()
        # Select only papers that haven't been changed by LLM yet, or select all if you want to re-process
        # cursor.execute("SELECT id FROM papers WHERE changed_by != 'LLM' OR changed_by IS NULL")
        cursor.execute("SELECT id FROM papers") # Process all
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
    processed_count = [0] # Use a list to make it mutable across threads

    # --- Start ThreadPoolExecutor ---
    print(f"Starting ThreadPoolExecutor with max {MAX_CONCURRENT_WORKERS} workers...")
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
            # Submit worker tasks
            futures = []
            for i in range(MAX_CONCURRENT_WORKERS):
                # Pass necessary arguments to the worker function
                 future = executor.submit(process_paper_worker, args.db_file, grammar_content, paper_id_queue, progress_lock, processed_count, total_papers)
                 futures.append(future)

            # Wait for all tasks in the queue to be completed OR for shutdown signal
            while not paper_id_queue.empty() and not shutdown_event.is_set():
                time.sleep(0.1) # Small sleep to avoid busy waiting

            # Once queue is empty or shutdown is requested, wait for threads to finish current tasks
            paper_id_queue.join()

            # Wait for all threads to finish (they should finish once the queue is empty or shutdown)
            # Use a timeout to ensure we don't wait forever if a thread hangs
            for future in as_completed(futures, timeout=60): 
                try:
                    future.result() # This will raise exceptions if the worker did
                except Exception as e:
                    print(f"Worker thread raised an exception: {e}")

    except Exception as e:
        print(f"An error occurred in the main execution block: {e}")
    finally:
        # --- Final Status ---
        end_time = time.time()
        with progress_lock:
            final_count = processed_count[0]
        print(f"\n--- Automation Summary ---")
        print(f"Papers processed: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds.")
        if shutdown_event.is_set():
            print("Processing was stopped by user (Ctrl+C).")
        else:
            print("Automation complete.")
        print("--------------------------")
