# deannualize_conferences.py
import sqlite3
import json
import argparse
import time
import os
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import signal
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
import globals  # Use globals from your existing setup

# Create the mapping table if it doesn't exist
def create_mapping_table(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS conference_name_mapping (
        original_name TEXT PRIMARY KEY,
        deannualized_name TEXT NOT NULL
    )
    ''')
    conn.commit()
    conn.close()

# Add new column to papers table if it doesn't exist
def add_deannualized_column(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Check if column exists
    cursor.execute("PRAGMA table_info(papers)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'deannualized_conference' not in columns:
        cursor.execute("ALTER TABLE papers ADD COLUMN deannualized_conference TEXT")
        conn.commit()
    conn.close()

# Get unique conference names that need processing
def get_unique_conference_names(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT journal as conference_name
        FROM papers
        WHERE type = 'inproceedings' AND journal IS NOT NULL AND journal != ''
        AND deannualized_conference IS NULL
    """)
    conference_names = [row[0] for row in cursor.fetchall()]
    conn.close()
    return conference_names

# Get all papers that need deannualizing
def get_papers_for_deannualizing(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, journal
        FROM papers
        WHERE type = 'inproceedings' AND journal IS NOT NULL AND journal != ''
        AND deannualized_conference IS NULL
    """)
    papers = cursor.fetchall()
    conn.close()
    return papers

# Build the deannualizing prompt
def build_deannualize_prompt(conference_name):
    template = """Your task is to remove year-specific information from conference names to get the core conference acronym or name.

Examples:
Input: "2023 IEEE International Conference on Robotics and Automation (ICRA)"
Output: "IEEE International Conference on Robotics and Automation (ICRA)"

Input: "Proc. of the 2021 ACM SIGPLAN International Conference on Object-Oriented Programming, Systems, Languages and Applications (OOPSLA)"
Output: "ACM SIGPLAN International Conference on Object-Oriented Programming, Systems, Languages and Applications (OOPSLA)"

Input: "2020 Conference on Neural Information Processing Systems (NeurIPS)"
Output: "Conference on Neural Information Processing Systems (NeurIPS)"

Input: "Proceedings of the 37th AAAI Conference on Artificial Intelligence, AAAI 2023"
Output: "AAAI Conference on Artificial Intelligence (AAAI)"

Input: "The Thirty-Fifth AAAI Conference on Artificial Intelligence (AAAI-2021)"
Output: "AAAI Conference on Artificial Intelligence (AAAI)"

Always put the available conference acronym in () for consistency, see below, both go to the same conference despite different format:

Input: "2025 26th International Conference on Electronic Packaging Technology (ICEPT)"
Output: "International Conference on Electronic Packaging Technology (ICEPT)"

Input: "2022 23rd International Conference on Electronic Packaging Technology, ICEPT 2022"
Output: "International Conference on Electronic Packaging Technology (ICEPT)"

Remember, your response is not being read by a human, it goes directly to an automated parser. After thinking through the request in <think></think> tags, output only the result in plaintext without any other tags like ```plaintext or similar.	

Input: "{conference_name}"
Output:"""
    return template.format(conference_name=conference_name)

# Update the mapping table with deannualized names
def update_mapping_table(db_path, original_name, deannualized_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO conference_name_mapping (original_name, deannualized_name)
        VALUES (?, ?)
    """, (original_name, deannualized_name))
    conn.commit()
    conn.close()

# Get deannualized name from mapping table
def get_deannualized_name_from_mapping(db_path, original_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT deannualized_name
        FROM conference_name_mapping
        WHERE original_name = ?
    """, (original_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Update papers with deannualized names
def update_papers_with_deannualized_name(db_path, original_name, deannualized_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE papers
        SET deannualized_conference = ?
        WHERE type = 'inproceedings' AND journal = ?
        AND deannualized_conference IS NULL
    """, (deannualized_name, original_name))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected

# Worker function for deannualizing conference names
def process_conference_worker(db_path, conference_name_queue, progress_lock, processed_count, total_conferences, model_alias):
    while True:
        try:
            # Use timeout to periodically check for shutdown
            conference_name = conference_name_queue.get(timeout=1)
        except queue.Empty:
            # Check if we should shutdown periodically
            if globals.is_shutdown_flag_set():
                return
            continue
        # Poison pill - time to die
        if conference_name is None:
            return
        # Check for shutdown before processing
        if globals.is_shutdown_flag_set():
            return
        print(f"[Thread-{threading.get_ident()}] Processing conference: {conference_name}")
        try:
            prompt_text = build_deannualize_prompt(conference_name)
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
                # Clean up the response - extract only the output part
                result = json_result_str.strip()
                # Sometimes the LLM might include the "Output:" part, so we remove it if present
                if "Output:" in result:
                    result = result.split("Output:")[-1].strip()
                # Also remove any <think> tags and content
                import re
                result = re.sub(r'<think>.*?</think>.*', '', result, flags=re.DOTALL).strip()
                
                # Update mapping table
                update_mapping_table(db_path, conference_name, result)
                
                # Update papers with this conference name
                rows_affected = update_papers_with_deannualized_name(db_path, conference_name, result)
                
                print(f"[Thread-{threading.get_ident()}] Updated {rows_affected} papers with deannualized name for '{conference_name}' -> '{result}'")
            else:
                if not globals.is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No LLM response for conference: {conference_name}")
        except Exception as e:
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error processing conference '{conference_name}': {e}")
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Deannualizing Progress] Processed {processed_count[0]}/{total_conferences} unique conferences.")

# Verification function
def verify_deannualized_names(db_path, verification_queue, progress_lock, processed_count, total_verifications, model_alias):
    while True:
        try:
            # Use timeout to periodically check for shutdown
            original_name, deannualized_name = verification_queue.get(timeout=1)
        except queue.Empty:
            # Check if we should shutdown periodically
            if globals.is_shutdown_flag_set():
                return
            continue
        # Poison pill - time to die
        if original_name is None:
            return
        # Check for shutdown before processing
        if globals.is_shutdown_flag_set():
            return
        print(f"[Thread-{threading.get_ident()}] Verifying: {original_name} -> {deannualized_name}")
        try:
            # Build verification prompt with JSON output
            verification_prompt = f"""
Your task is to verify if the de-annualized conference name properly removes year-specific information from the original conference name.

Examples:
Input: "2023 IEEE International Conference on Robotics and Automation (ICRA)", "IEEE International Conference on Robotics and Automation (ICRA)"
Output: {{"status": "VERIFIED"}}

Input: "Proc. of the 2021 ACM SIGPLAN International Conference on Object-Oriented Programming, Systems, Languages and Applications (OOPSLA)", "ACM SIGPLAN International Conference on Object-Oriented Programming, Systems, Languages and Applications (OOPSLA)"
Output: {{"status": "VERIFIED"}}

Input: "2020 Conference on Neural Information Processing Systems (NeurIPS)", "Conference on Neural Information Processing Systems (NeurIPS)"
Output: {{"status": "VERIFIED"}}

Input: "Proceedings of the 37th AAAI Conference on Artificial Intelligence, AAAI 2023", "AAAI Conference on Artificial Intelligence (AAAI)"
Output: {{"status": "VERIFIED"}}

Input: "2023 IEEE International Conference on Robotics and Automation (ICRA)", "IEEE Robotics Conference (ICRA)"
Output: {{"status": "INCORRECT", "corrected": "IEEE International Conference on Robotics and Automation (ICRA)"}}

Please verify if the de-annualized version correctly removes year-specific information (like years, edition numbers) while preserving the core conference identity. If the de-annualized version is correct, respond with {{"status": "VERIFIED"}}. If it is incorrect, respond with {{"status": "INCORRECT", "corrected": "correct_deannualized_name"}}.

Remember, your response is not being read by a human, it goes directly to an automated parser. After thinking through the request in <think> </think> tags, output only the JSON result without any other tags like ```json or similar.

Original: "{original_name}"
De-annualized: "{deannualized_name}"
"""
            if globals.is_shutdown_flag_set():
                return
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                verification_prompt,
                server_url_base=globals.LLM_SERVER_URL,
                model_name=model_alias,
                is_verification=True
            )
            if globals.is_shutdown_flag_set():
                return
            if json_result_str:
                result = json_result_str.strip()
                # Try to parse the JSON result
                try:
                    verification_result = json.loads(result)
                    status = verification_result.get("status")
                    
                    if status == "VERIFIED":
                        # Don't print anything for correct results to not pollute the log
                        pass
                    elif status == "INCORRECT":
                        corrected_name = verification_result.get("corrected")
                        if corrected_name:
                            print(f"[Thread-{threading.get_ident()}] Verification FAILED for: {original_name}, correcting to: {corrected_name}")
                            
                            # Update the mapping table with the corrected name
                            update_mapping_table(db_path, original_name, corrected_name)
                            
                            # Update papers with the corrected name
                            conn = sqlite3.connect(db_path)
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE papers
                                SET deannualized_conference = ?
                                WHERE type = 'inproceedings' AND journal = ?
                            """, (corrected_name, original_name))
                            rows_affected = cursor.rowcount
                            conn.commit()
                            conn.close()
                            print(f"[Thread-{threading.get_ident()}] Corrected {rows_affected} papers for '{original_name}' -> '{corrected_name}'")
                        else:
                            print(f"[Thread-{threading.get_ident()}] Verification FAILED but no corrected name provided for: {original_name}")
                    else:
                        print(f"[Thread-{threading.get_ident()}] Unexpected verification status for: {original_name} -> {status}")
                except json.JSONDecodeError:
                    print(f"[Thread-{threading.get_ident()}] Could not parse verification result JSON for: {original_name}")
                    print(f"Verification result: {result}")
            else:
                if not globals.is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No verification response for: {original_name}")
        except Exception as e:
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error verifying conference '{original_name}': {e}")
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Verification Progress] Verified {processed_count[0]}/{total_verifications} conference mappings.")

def run_deannualizing(db_file=None):
    """
    Main function to run the deannualizing process
    """
    if db_file is None:
        db_file = globals.DATABASE_FILE

    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False

    print("Creating mapping table and adding deannualized column if needed...")
    create_mapping_table(db_file)
    add_deannualized_column(db_file)

    print("Fetching unique conference names...")
    unique_conferences = get_unique_conference_names(db_file)
    total_conferences = len(unique_conferences)
    print(f"Found {total_conferences} unique conference names to process.")

    if not unique_conferences:
        print("No conference names found to de-annualize.")
        return True

    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        return False

    # Create queue for conference names
    conference_queue = queue.Queue()
    for conf in unique_conferences:
        conference_queue.put(conf)
    # Add poison pills
    for _ in range(globals.MAX_CONCURRENT_WORKERS):
        conference_queue.put(None)

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers for deannualizing...")
    start_time = time.time()
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                future = executor.submit(
                    process_conference_worker,
                    db_file,
                    conference_queue,
                    progress_lock,
                    processed_count,
                    total_conferences,
                    model_alias
                )
                futures.append(future)

            print("Deannualizing started. Press Ctrl+C to abort.")
            while not globals.is_shutdown_flag_set():
                if all(f.done() for f in futures):
                    break
                time.sleep(0.1)
            if globals.is_shutdown_flag_set():
                print("\nShutdown signal received. Waiting for threads to finish...")
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught. Setting shutdown flag.")
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
        print(f"\n--- Deannualizing Summary ---")
        print(f"Unique conferences processed: {final_count}/{total_conferences}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")

    # Verification step
    if not globals.is_shutdown_flag_set():
        print("\n--- Starting Verification ---")
        # Get all mappings to verify
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT original_name, deannualized_name FROM conference_name_mapping")
        mappings_to_verify = cursor.fetchall()
        conn.close()
        
        total_verifications = len(mappings_to_verify)
        print(f"Found {total_verifications} mappings to verify.")
        
        if mappings_to_verify:
            verification_queue = queue.Queue()
            for original, deannualized in mappings_to_verify:
                verification_queue.put((original, deannualized))
            # Add poison pills
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                verification_queue.put(None)

            verification_progress_lock = threading.Lock()
            verification_processed_count = [0]

            print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers for verification...")
            verification_start_time = time.time()
            try:
                with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
                    futures = []
                    for _ in range(globals.MAX_CONCURRENT_WORKERS):
                        future = executor.submit(
                            verify_deannualized_names,
                            db_file,
                            verification_queue,
                            verification_progress_lock,
                            verification_processed_count,
                            total_verifications,
                            model_alias
                        )
                        futures.append(future)

                    print("Verification started. Press Ctrl+C to abort.")
                    while not globals.is_shutdown_flag_set():
                        if all(f.done() for f in futures):
                            break
                        time.sleep(0.1)
                    if globals.is_shutdown_flag_set():
                        print("\nShutdown signal received during verification. Waiting for threads to finish...")
            except KeyboardInterrupt:
                print("\nKeyboardInterrupt caught during verification. Setting shutdown flag.")
                globals.set_shutdown_flag()
            except Exception as e:
                print(f"Error in verification execution loop: {e}")
                globals.set_shutdown_flag()
            finally:
                verification_end_time = time.time()
                verification_final_count = 0
                if verification_progress_lock:
                    with verification_progress_lock:
                        verification_final_count = verification_processed_count[0] if verification_processed_count else 0
                print(f"\n--- Verification Summary ---")
                print(f"Mappings verified: {verification_final_count}/{total_verifications}")
                print(f"Time taken: {verification_end_time - verification_start_time:.2f} seconds")

    return not globals.is_shutdown_flag_set()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='De-annualize conference names in the database.')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, globals.signal_handler)

    success = run_deannualizing(db_file=args.db_file)

    if not success and not globals.is_shutdown_flag_set():
        exit(1)
    # If shutdown_flag is set, signal_handler already called os._exit(1)
    # Normal exit code 0 is implicit