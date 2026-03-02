# migrate_to_v1.0.0.py
"""
Single-use migration script to update the database schema for ResearchParça v1.0.0.

This script performs the following:
1. Adds new columns: last_llm_*, user_override_count, llm_log.
2. Populates last_llm_* columns with the *current* main field values.
3. Initializes llm_log with synthetic entries based on existing trace and audit data.
4. Initializes user_override_count to 0 (as we're starting fresh from main field state).
"""

import sqlite3
import json
import argparse
from datetime import datetime, timedelta


def migrate_database(db_path):
    """
    Performs the database migration.
    """
    print(f"Starting migration for database: {db_path}")
    conn = sqlite3.connect(db_path)
    # Use row_factory to access columns by name easily
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # --- Step 1: Add new columns ---
        print("Adding new columns...")
        # Core LLM log
        cursor.execute("ALTER TABLE papers ADD COLUMN llm_log TEXT DEFAULT '[]'")

        # Last LLM state cache
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_features TEXT")
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_technique TEXT")
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_is_survey INTEGER") # BOOLEAN
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_is_offtopic INTEGER") # BOOLEAN
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_is_through_hole INTEGER") # BOOLEAN
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_is_smt INTEGER") # BOOLEAN
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_is_x_ray INTEGER") # BOOLEAN
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_relevance REAL")
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_verified REAL")
        cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_estimated_score REAL")

        # User override count
        cursor.execute("ALTER TABLE papers ADD COLUMN user_override_count INTEGER DEFAULT 0")

        # Optional: Add other main fields if you want full separation (e.g., title, authors, type)
        # cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_title TEXT")
        # cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_authors TEXT")
        # cursor.execute("ALTER TABLE papers ADD COLUMN last_llm_type TEXT")
        # ... add others as needed, defaulting to NULL

        print("New columns added successfully.")

        # --- Step 2: Populate last_llm_* columns from main fields ---
        # We fetch the current state of main fields and use them as the initial "last LLM" state.
        # This assumes the current data represents the best known state prior to the new system.
        print("Populating last_llm_* columns with current main field values...")
        cursor.execute("""
            UPDATE papers
            SET
                last_llm_features = features,
                last_llm_technique = technique,
                last_llm_is_survey = is_survey,
                last_llm_is_offtopic = is_offtopic,
                last_llm_is_through_hole = is_through_hole,
                last_llm_is_smt = is_smt,
                last_llm_is_x_ray = is_x_ray,
                last_llm_relevance = relevance,
                last_llm_verified = verified,
                last_llm_estimated_score = estimated_score
            """)
        print(f"Populated last_llm_* columns for {cursor.rowcount} rows.")

        # --- Step 3: Generate and populate llm_log for each paper ---
        print("Generating and populating llm_log for each paper...")
        # Fetch all papers to process their existing trace/audit data
        cursor.execute("SELECT id, reasoning_trace, verifier_trace, changed, changed_by, user_trace, features, technique, is_survey, is_offtopic, is_through_hole, is_smt, is_x_ray, relevance, verified, estimated_score FROM papers")
        rows = cursor.fetchall()

        total_processed = 0
        for row in rows:
            paper_id = row['id']
            # Use the current field values as the base for synthetic LLM outputs
            current_features = row['features']
            current_technique = row['technique']
            current_is_survey = row['is_survey']
            current_is_offtopic = row['is_offtopic']
            current_is_through_hole = row['is_through_hole']
            current_is_smt = row['is_smt']
            current_is_x_ray = row['is_x_ray']
            current_relevance = row['relevance']
            current_verified = row['verified']
            current_estimated_score = row['estimated_score']

            # Get the paper's change timestamp, or use a default if NULL
            paper_timestamp_iso = row['changed']
            if paper_timestamp_iso:
                try:
                    # Remove 'Z' before parsing to keep datetime naive (matching existing code style)
                    paper_timestamp = datetime.fromisoformat(paper_timestamp_iso.replace('Z', ''))
                except ValueError:
                    print(f"Warning: Invalid timestamp format for paper {paper_id}: {paper_timestamp_iso}. Using UTC now.")
                    paper_timestamp = datetime.utcnow()
            else:
                print(f"Warning: No 'changed' timestamp for paper {paper_id}. Using UTC now.")
                paper_timestamp = datetime.utcnow()

            # Determine the model name from the changed_by field
            # Assume if changed_by contains "LLM", it's the model name alias used previously
            # Otherwise, treat as user or unknown, default to a generic placeholder or skip
            # For this migration, let's assume 'LLM' or a specific alias was used consistently for LLM changes
            # If changed_by is 'user', it means the last *explicit* change was by the user, but the underlying data might still be from LLM
            # The safest assumption here might be that the *data* itself represents the last effective state,
            # regardless of who last touched the 'changed'/'changed_by' fields explicitly.
            # However, the traces (reasoning_trace, verifier_trace) are more indicative of LLM involvement.
            # Let's derive the model name from the trace prefixes if available, otherwise use changed_by as fallback.
            # The prompt mentions: "reasoning_trace = f"As classified by {model_name_used}{reasoning_trace}"" etc.
            # So, traces likely start with "As classified by..." or "As verified by..."
            classifier_model_name = "unknown"
            verifier_model_name = "unknown"

            classifier_trace_content = ""
            if row['reasoning_trace']:
                 trace_str = row['reasoning_trace']
                 if trace_str.startswith("As classified by "):
                     end_marker_idx = trace_str.find('\n', len("As classified by ")) # Find end of model name line
                     if end_marker_idx != -1:
                         classifier_model_name = trace_str[len("As classified by "):end_marker_idx].strip()
                         classifier_trace_content = trace_str[end_marker_idx+1:] # Rest of the trace
                     else: # If no newline, assume rest of string is model name (less likely)
                          # This handles the case where the trace is just "As classified by MODEL_NAME"
                          classifier_model_name = trace_str[len("As classified by "):].strip()
                          classifier_trace_content = ""
                 else:
                     # If it doesn't start with the prefix, assume it's just the trace content and model is unknown
                     classifier_trace_content = trace_str

            verifier_trace_content = ""
            if row['verifier_trace']:
                 trace_str = row['verifier_trace']
                 if trace_str.startswith("As verified by "):
                     end_marker_idx = trace_str.find('\n', len("As verified by ")) # Find end of model name line
                     if end_marker_idx != -1:
                         verifier_model_name = trace_str[len("As verified by "):end_marker_idx].strip()
                         verifier_trace_content = trace_str[end_marker_idx+1:] # Rest of the trace
                     else: # If no newline, assume rest of string is model name (less likely)
                          # This handles the case where the trace is just "As verified by MODEL_NAME"
                          verifier_model_name = trace_str[len("As verified by "):].strip()
                          verifier_trace_content = ""
                 else:
                      # If it doesn't start with the prefix, assume it's just the trace content and model is unknown
                      verifier_trace_content = trace_str


            # Build the synthetic log list
            synthetic_log = []

            # Add synthetic Classifier Trace Entry (if trace exists)
            if row['reasoning_trace']: # Check the original trace field
                # Timestamp: 2 minutes before the paper's change timestamp
                # Keep format consistent: naive datetime + 'Z' suffix (matching existing code style)
                classifier_ts = (paper_timestamp - timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                # Synthetic output: reconstruct the JSON-like structure from current fields
                # Note: This is a best-effort reconstruction, assuming the current fields reflect the LLM's output at that time
                synthetic_output = {
                    # Include fields typically set by classifier
                    # You might need to adjust this list based on your exact classifier prompt output schema
                    "features": json.loads(current_features) if current_features else {},
                    "technique": json.loads(current_technique) if current_technique else {},
                    "is_survey": current_is_survey,
                    "is_offtopic": current_is_offtopic,
                    "is_through_hole": current_is_through_hole,
                    "is_smt": current_is_smt,
                    "is_x_ray": current_is_x_ray,
                    "research_area": getattr(row, 'research_area', None), # Include if column exists and was set by classifier
                    "relevance": current_relevance,
                    # Add other fields set by classifier prompt here if applicable
                }
                # Filter out keys with None values if desired for cleaner output
                synthetic_output = {k: v for k, v in synthetic_output.items() if v is not None}

                classifier_entry = {
                    "timestamp": classifier_ts,
                    "type": "classifier", # Or "reclassification" if it was a re-run
                    "model": classifier_model_name,
                    "trace": classifier_trace_content, # Exclude the "As classified by..." prefix
                    "output": json.dumps(synthetic_output), # Store reconstructed output as string
                    "valid": True # Assume it was valid if it was saved previously
                }
                synthetic_log.append(classifier_entry)

            # Add synthetic Verifier Trace Entry (if trace exists)
            if row['verifier_trace']: # Check the original trace field
                # Timestamp: 1 minute before the paper's change timestamp
                # Keep format consistent: naive datetime + 'Z' suffix (matching existing code style)
                verifier_ts = (paper_timestamp - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                # Synthetic output: reconstruct the JSON-like structure from verification fields
                # Note: Verification typically focuses on 'verified', 'estimated_score', maybe reasoning
                synthetic_verification_output = {
                    "verified": current_verified,
                    "estimated_score": current_estimated_score,
                    # Add other fields potentially set by verifier prompt here if applicable
                }
                # Filter out keys with None values if desired for cleaner output
                synthetic_verification_output = {k: v for k, v in synthetic_verification_output.items() if v is not None}

                verifier_entry = {
                    "timestamp": verifier_ts,
                    "type": "verifier", # Or "reclassification" if it was a verification-triggered re-run
                    "model": verifier_model_name,
                    "trace": verifier_trace_content, # Exclude the "As verified by..." prefix
                    "output": json.dumps(synthetic_verification_output), # Store reconstructed output as string
                    "valid": True # Assume it was valid if it was saved previously
                }
                synthetic_log.append(verifier_entry)

            # Add synthetic User Trace Entry (if user_trace exists)
            # This represents the *state* of user_trace at the time of the last recorded change,
            # not necessarily a *new* user change triggering this migration log entry.
            # For migration, we can log the *current* user_trace value if it exists.
            # However, the prompt implies logging *changes*. For the initial state, maybe only log if
            # there's evidence of a *user override* compared to the 'last_llm_*' state (which we just set to main fields).
            # Since we initialized last_llm_* to main fields, any current user_trace would represent an override at that time.
            # But the prompt for migration says to use *current* state.
            # Let's log the user_trace if it exists, representing the state at the time the *last* change happened.
            # The timestamp will be the paper's change timestamp (or the closest proxy).
            if row['user_trace'] is not None and row['user_trace'].strip() != "":
                 # Use the paper's timestamp as the proxy for when the user trace was last set
                 # Keep format consistent: naive datetime + 'Z' suffix (matching existing code style)
                 user_ts = paper_timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                 # For the 'output', log the fields that might have been user-modified.
                 # Since we don't know *which* fields the user actually changed historically,
                 # and we just set last_llm_* to the current main fields, we cannot accurately determine
                 # the *difference* for this historical user action.
                 # The best proxy is to log the *current* main fields again, acknowledging the limitation.
                 # OR, since user_trace itself is a direct field, maybe just log that?
                 # The prompt example for user log: "output": "full set of currently set values"
                 # This is ambiguous for the *migration* case. We know the *final* state of the main fields
                 # matches the last_llm state (due to step 2). So, if user_trace was set, it existed alongside
                 # that state. We can log the main fields as they were at that time (i.e., same as last_llm).
                 # However, the 'output' in the new log should ideally represent the *change*.
                 # Given the ambiguity for migration, let's log the main fields as they stood
                 # (which equals the new last_llm state) and the user_trace comment.
                 # This serves as a record that a user comment existed at that time.
                 # A more accurate log would require knowing historical diffs, which we don't have.
                 # Therefore, we log the *snapshot* of main fields alongside the comment.
                 current_main_fields_snapshot = {
                     "features": json.loads(current_features) if current_features else {},
                     "technique": json.loads(current_technique) if current_technique else {},
                     "is_survey": current_is_survey,
                     "is_offtopic": current_is_offtopic,
                     "is_through_hole": current_is_through_hole,
                     "is_smt": current_is_smt,
                     "is_x_ray": current_is_x_ray,
                     "relevance": current_relevance,
                     "verified": current_verified,
                     "estimated_score": current_estimated_score,
                     # Add other main fields here if they were potentially user-editable and part of the 'output'
                 }
                 current_main_fields_snapshot = {k: v for k, v in current_main_fields_snapshot.items() if v is not None}

                 user_entry = {
                     "timestamp": user_ts,
                     "type": "user",
                     "model": "user",
                     "trace": row['user_trace'], # The user comment
                     "output": json.dumps(current_main_fields_snapshot), # Snapshot of fields at that time
                     "valid": True # User input is considered valid
                 }
                 synthetic_log.append(user_entry)


            # Serialize the synthetic log list to a JSON string
            log_json_str = json.dumps(synthetic_log)

            # Update the paper's llm_log column with the synthetic data
            cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (log_json_str, paper_id))

            total_processed += 1
            if total_processed % 1000 == 0: # Print progress every 1000 papers
                print(f"Processed {total_processed} papers...")

        print(f"Generated and populated llm_log for {total_processed} papers.")

        # Commit all changes
        conn.commit()
        print("Migration completed successfully!")

    except sqlite3.Error as e:
        print(f"An error occurred during migration: {e}")
        conn.rollback() # Rollback changes if an error occurs
        raise # Re-raise the exception after rollback
    except json.JSONDecodeError as e:
        print(f"JSON error during log reconstruction: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Migrate ResearchParça database to v1.0.0 schema.')
    parser.add_argument('db_file', type=str, help='Path to the SQLite database file to migrate.')
    args = parser.parse_args()

    migrate_database(args.db_file)