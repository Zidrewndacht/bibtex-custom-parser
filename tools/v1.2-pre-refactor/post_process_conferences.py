# post_process_conferences.py
import sqlite3
import json
import re
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import os
import time
from difflib import SequenceMatcher
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
import globals

def normalize_conference_name(name):
    """Normalize conference names to help with matching"""
    normalized = name.lower()
    # Remove common prefixes/suffixes and normalize
    normalized = re.sub(r'\bproceedings\b', '', normalized)
    normalized = re.sub(r'\bproc\.\b', '', normalized)
    normalized = re.sub(r'\bconf\b', 'conference', normalized)
    normalized = re.sub(r'\bintl\b', 'international', normalized)
    normalized = re.sub(r'\bint\b', 'international', normalized)
    normalized = re.sub(r'\bann\w*\s+conf\b', 'annual conference', normalized)
    # Remove years and edition numbers
    normalized = re.sub(r'\b\d{4}\b', '', normalized)
    normalized = re.sub(r'\b\d+st\b', '', normalized)
    normalized = re.sub(r'\b\d+nd\b', '', normalized)
    normalized = re.sub(r'\b\d+rd\b', '', normalized)
    normalized = re.sub(r'\b\d+th\b', '', normalized)
    # Remove extra spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized

def get_conference_groups(db_path, threshold=0.85):
    """Efficiently group similar conferences using a more efficient approach"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT original_name, deannualized_name FROM conference_name_mapping")
    all_mappings = cursor.fetchall()
    conn.close()
    
    # Create a dictionary mapping normalized names to their original forms
    normalized_to_originals = {}
    for orig, deannual in all_mappings:
        normalized = normalize_conference_name(deannual)
        if normalized not in normalized_to_originals:
            normalized_to_originals[normalized] = []
        normalized_to_originals[normalized].append((orig, deannual))
    
    # Group by normalized names first (these are already very similar)
    groups = []
    for normalized, originals in normalized_to_originals.items():
        if len(originals) > 1:
            groups.append(originals)
    
    # For remaining items, do fuzzy matching only within similar-length buckets
    # to reduce comparisons
    remaining_items = []
    for orig, deannual in all_mappings:
        normalized = normalize_conference_name(deannual)
        # Skip if already grouped
        already_grouped = False
        for group in groups:
            if any(orig == item[0] for item in group):
                already_grouped = True
                break
        if not already_grouped:
            remaining_items.append((orig, deannual, normalized))
    
    # Group remaining items by first few words to reduce comparisons
    bucketed_items = {}
    for orig, deannual, normalized in remaining_items:
        # Use first 3-4 significant words as bucket key
        words = normalized.split()
        bucket_key = ' '.join(words[:min(4, len(words))])
        if bucket_key not in bucketed_items:
            bucketed_items[bucket_key] = []
        bucketed_items[bucket_key].append((orig, deannual, normalized))
    
    # Do fuzzy matching within each bucket
    for bucket_key, bucket_items in bucketed_items.items():
        if len(bucket_items) <= 1:
            continue
            
        # Compare each item in bucket with others in the same bucket
        processed_in_bucket = set()
        for i, (orig1, deannual1, norm1) in enumerate(bucket_items):
            if orig1 in processed_in_bucket:
                continue
                
            current_group = [(orig1, deannual1)]
            processed_in_bucket.add(orig1)
            
            for j, (orig2, deannual2, norm2) in enumerate(bucket_items[i+1:], i+1):
                if orig2 in processed_in_bucket:
                    continue
                    
                similarity = SequenceMatcher(None, norm1, norm2).ratio()
                if similarity >= threshold:
                    current_group.append((orig2, deannual2))
                    processed_in_bucket.add(orig2)
            
            if len(current_group) > 1:
                groups.append(current_group)
    
    return groups

def build_consistency_prompt(conference_variations):
    """Build prompt to ask LLM to choose canonical forms"""
    variations_list = "\n".join([f"- {deannualized}" for orig, deannualized in conference_variations])

    prompt = f"""
You are tasked with standardizing conference names. You will be given multiple variations of what should be the same conference name, and you need to determine which form should be the canonical (standard) form.

Rules for canonical form:
1. Include the conference acronym in parentheses if available
2. Prefer the most complete and descriptive name
3. Maintain consistency with common conference naming conventions
4. If multiple variations are equally valid, choose the most common or descriptive one


Remember, your response is not being read by a human, it goes directly to an automated parser. After thinking through the request in <think> </think> tags, output only the JSON result without any other tags like ```json or similar.

Output only a JSON object with the canonical form:
{{"canonical": "canonical_conference_name"}}

Here are the variations for the same conference. Analyze the variations to identify which form should be the canonical one based on the rules above.
{variations_list}
"""
    return prompt

def process_conference_group(db_path, group_queue, progress_lock, processed_count, total_groups, model_alias):
    """Process one group of similar conferences"""
    while True:
        try:
            # Use timeout to periodically check for shutdown
            variations = group_queue.get(timeout=1)
        except queue.Empty:
            # Check if we should shutdown periodically
            if globals.is_shutdown_flag_set():
                return
            continue
        # Poison pill - time to die
        if variations is None:
            return
        # Check for shutdown before processing
        if globals.is_shutdown_flag_set():
            return
        
        print(f"[Thread-{threading.get_ident()}] Processing conference group with {len(variations)} variations:")
        for orig, deannualized in variations:
            print(f"  '{orig}' -> '{deannualized}'")
        
        try:
            prompt_text = build_consistency_prompt(variations)
            if globals.is_shutdown_flag_set():
                return
            json_result_str, model_name_used, reasoning_trace = globals.send_prompt_to_llm(
                prompt_text,
                server_url_base=globals.LLM_SERVER_URL,
                model_name=model_alias,
                is_verification=True
            )
            if globals.is_shutdown_flag_set():
                return
            
            if json_result_str:
                try:
                    result = json.loads(json_result_str)
                    canonical_form = result.get("canonical")
                    if canonical_form:
                        print(f"[Thread-{threading.get_ident()}] Canonical form selected: {canonical_form}")
                        
                        # Update the mapping table and papers
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        
                        for orig, deannualized in variations:
                            if deannualized != canonical_form:
                                print(f"[Thread-{threading.get_ident()}] Updating {orig} from '{deannualized}' to '{canonical_form}'")
                                
                                # Update mapping table
                                cursor.execute("""
                                    UPDATE conference_name_mapping
                                    SET deannualized_name = ?
                                    WHERE original_name = ?
                                """, (canonical_form, orig))
                                
                                # Update papers
                                cursor.execute("""
                                    UPDATE papers
                                    SET deannualized_conference = ?
                                    WHERE journal = ? AND type = 'inproceedings'
                                """, (canonical_form, orig))
                        
                        conn.commit()
                        conn.close()
                    else:
                        print(f"[Thread-{threading.get_ident()}] No canonical form found in result: {json_result_str}")
                except json.JSONDecodeError as e:
                    print(f"[Thread-{threading.get_ident()}] Error parsing consistency result: {e}")
                    print(f"Result: {json_result_str}")
            else:
                if not globals.is_shutdown_flag_set():
                    print(f"[Thread-{threading.get_ident()}] No LLM response for group with {len(variations)} variations")
        except Exception as e:
            if not globals.is_shutdown_flag_set():
                print(f"[Thread-{threading.get_ident()}] Error processing group: {e}")
                # Print the variations that caused the error for debugging
                for orig, deannualized in variations:
                    print(f"  Error group item: '{orig}' -> '{deannualized}'")
        finally:
            if globals.is_shutdown_flag_set():
                return
            with progress_lock:
                processed_count[0] += 1
                print(f"[Consistency Progress] Processed {processed_count[0]}/{total_groups} conference groups.")

def run_conference_consistency(db_file=None, similarity_threshold=0.85):
    """Run the post-processing to make conference names consistent"""
    if db_file is None:
        db_file = globals.DATABASE_FILE

    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        return False

    print("Finding similar conference names using efficient grouping...")
    similar_groups = get_conference_groups(db_file, threshold=similarity_threshold)
    total_groups = len(similar_groups)
    print(f"Found {total_groups} groups of similar conferences to process.")

    if not similar_groups:
        print("No similar conference groups found. All names appear consistent.")
        return True

    print("Fetching model alias from LLM server...")
    model_alias = globals.get_model_alias(globals.LLM_SERVER_URL)
    if not model_alias:
        print("Error: Could not determine model alias. Exiting.")
        return False

    # Create queue for conference groups
    group_queue = queue.Queue()
    for variations in similar_groups:
        group_queue.put(variations)
    # Add poison pills
    for _ in range(globals.MAX_CONCURRENT_WORKERS):
        group_queue.put(None)

    progress_lock = threading.Lock()
    processed_count = [0]

    print(f"Starting ThreadPoolExecutor with {globals.MAX_CONCURRENT_WORKERS} workers for consistency...")
    try:
        with ThreadPoolExecutor(max_workers=globals.MAX_CONCURRENT_WORKERS) as executor:
            futures = []
            for _ in range(globals.MAX_CONCURRENT_WORKERS):
                future = executor.submit(
                    process_conference_group,
                    db_file,
                    group_queue,
                    progress_lock,
                    processed_count,
                    total_groups,
                    model_alias
                )
                futures.append(future)

            print("Consistency processing started. Press Ctrl+C to abort.")
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
        print(f"Error in consistency execution loop: {e}")
        globals.set_shutdown_flag()
    finally:
        final_count = 0
        if progress_lock:
            with progress_lock:
                final_count = processed_count[0] if processed_count else 0
        print(f"\n--- Consistency Summary ---")
        print(f"Groups processed: {final_count}/{total_groups}")
        print("Consistency processing completed.")

    return not globals.is_shutdown_flag_set()

if __name__ == "__main__":
    import signal
    import argparse
    
    parser = argparse.ArgumentParser(description='Post-process conference names for consistency.')
    parser.add_argument('--db_file', default=globals.DATABASE_FILE,
                       help=f'SQLite database file path (default: {globals.DATABASE_FILE})')
    parser.add_argument('--threshold', type=float, default=0.85,
                       help='Similarity threshold for fuzzy matching (default: 0.85)')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, globals.signal_handler)

    success = run_conference_consistency(db_file=args.db_file, similarity_threshold=args.threshold)

    if not success and not globals.is_shutdown_flag_set():
        exit(1)
    # If shutdown_flag is set, signal_handler already called os._exit(1)
    # Normal exit code 0 is implicit