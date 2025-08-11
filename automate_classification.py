#automate_classification
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

import globals  #globals.py for global settings and variables used by multiple files.

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

def send_prompt_to_llm(prompt_text, grammar_text=None, server_url_base=globals.LLM_SERVER_URL, model_name="default"):
    """Sends a prompt to the LLM via the OpenAI-compatible API. Returns (content_str, model_name_used)."""
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
        if is_shutdown_flag_set():
            return None, None
        response = requests.post(chat_url, headers=headers, json=payload, timeout=600)
        if is_shutdown_flag_set():
            return None, None
        response.raise_for_status()
        response_data = response.json()
        model_name_from_response = response_data.get('model', model_name)
        if 'choices' in response_data and response_data['choices']:
            reasoning_content = response_data['choices'][0]['message'].get('reasoning_content', '').strip()
            content = response_data['choices'][0]['message']['content'].strip()
            return content, model_name_from_response, reasoning_content
        else:
            print(f"Warning: Unexpected LLM response structure: {response_data}")
            return None, model_name_from_response
    except requests.exceptions.RequestException as e:
        if is_shutdown_flag_set():
            return None, None
        print(f"Error sending request to LLM server: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response Text: {e.response.text}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        if 'response' in locals():
            print(f"Response Text: {response.text}")
        return None, None
    except KeyError as e:
        print(f"Unexpected response structure, missing key: {e}")
        print(f"Response Data: {response_data}")
        return None, None

def signal_handler(sig, frame):
    print("\nReceived Ctrl+C. Killing all threads...")
    set_shutdown_flag()
    os._exit(1)

def process_paper_worker(db_path, grammar_content, prompt_template_content, paper_id_queue, progress_lock, processed_count, total_papers, model_alias):
    """Worker function executed by each thread."""
    while True:
        if is_shutdown_flag_set():
            return
        try:
            paper_id = paper_id_queue.get_nowait()
        except queue.Empty:
            if is_shutdown_flag_set():
                return
            time.sleep(0.1)
            continue
            
        print(f"[Thread-{threading.get_ident()}] Processing paper ID: {paper_id}")
        try:
            paper_data = globals.get_paper_by_id(db_path, paper_id)
            if not paper_data:
                print(f"[Thread-{threading.get_ident()}] Error: Paper {paper_id} not found in DB.")
                continue
                
            prompt_text = build_prompt(paper_data, prompt_template_content)
            if is_shutdown_flag_set():
                return
                
            json_result_str, model_name_used, reasoning_trace = send_prompt_to_llm(
                prompt_text, 
                grammar_text=grammar_content, 
                server_url_base=globals.LLM_SERVER_URL, 
                model_name=model_alias
            )
            
            if is_shutdown_flag_set():
                return
                
            if json_result_str:
                try:
                    llm_classification = json.loads(json_result_str)
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
                if not is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No LLM response for {paper_id}")
        except Exception as e:
            if not is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error processing {paper_id}: {e}")
        finally:
            if is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Progress] Processed {processed_count[0]}/{total_papers} papers.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Automate LLM classification for papers in the database.')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE, 
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--grammar_file', '-g', default=globals.GRAMMAR_FILE,
                       help=f'Path to the GBNF grammar file (default: {globals.GRAMMAR_FILE})')
    parser.add_argument('--prompt_template', '-t', default=globals.PROMPT_TEMPLATE, 
                       help=f'Path to the prompt template file (default: {globals.PROMPT_TEMPLATE})')
    parser.add_argument('--server_url', default=globals.LLM_SERVER_URL, 
                       help=f'Base URL of the LLM server (default: {globals.LLM_SERVER_URL})')
    args = parser.parse_args()

    if not os.path.exists(args.db_file):
        print(f"Error: Database file '{args.db_file}' not found.")
        exit(1)

    try:
        prompt_template_content = globals.load_prompt_template(args.prompt_template)
        print(f"Loaded prompt template from '{args.prompt_template}'")
    except Exception:
        exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    grammar_content = None
    if args.grammar_file:
        try:
            with open(args.grammar_file, 'r', encoding='utf-8') as f:
                grammar_content = f.read()
            print(f"Loaded GBNF grammar from '{args.grammar_file}'")
        except Exception as e:
            print(f"Error reading grammar file: {e}")
            exit(1)

    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(args.server_url)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        exit(1)

    print(f"Connecting to database '{args.db_file}'...")
    try:
        conn = sqlite3.connect(args.db_file)
        cursor = conn.cursor()
        # Only fetch papers that have not been processed yet (changed_by IS NULL or blank)
        cursor.execute("SELECT id FROM papers WHERE changed_by IS NULL OR changed_by = ''")
        paper_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        total_papers = len(paper_ids)
        print(f"Found {total_papers} unprocessed papers to process.")
    except Exception as e:
        print(f"Error fetching paper IDs: {e}")
        exit(1)
        
    if not paper_ids:
        print("No papers found in database. Exiting.")
        exit(0)

    paper_id_queue = queue.Queue()
    for pid in paper_ids:
        paper_id_queue.put(pid)

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers...")
    start_time = time.time()
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                executor.submit(
                    process_paper_worker,
                    args.db_file,
                    grammar_content,
                    prompt_template_content,
                    paper_id_queue,
                    progress_lock,
                    processed_count,
                    total_papers,
                    model_alias
                )
            print("Processing started. Press Ctrl+C to abort.")
            while True:
                time.sleep(0.1)
    except Exception as e:
        print(f"Error in main execution: {e}")
        os._exit(1)
    finally:
        end_time = time.time()
        with progress_lock:
            final_count = processed_count[0]
        print(f"\n--- Summary ---")
        print(f"Papers processed: {final_count}/{total_papers}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print("Done.")