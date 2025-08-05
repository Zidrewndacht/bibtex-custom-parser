# send_prompt_to_llm.py (Updated for GBNF)

import requests
import argparse
import json
import time
import sys
import os

# --- Import functions from build_prompt.py ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from build_prompt import build_prompt, get_paper_by_id
except ImportError as e:
    print(f"Error importing functions from build_prompt.py: {e}")
    print("Make sure 'build_prompt.py' is in the same directory or correctly importable.")
    exit(1)
# --- End Import ---

# --- Configuration ---
LLM_SERVER_URL = "http://localhost:8080/v1/chat/completions" # Default endpoint

# --- Function to send prompt to LLM ---
def send_prompt_to_llm(prompt_text, grammar_text=None, server_url=LLM_SERVER_URL, model_name="gpt-3.5-turbo"):
    """
    Sends a prompt (and optionally a grammar) to the LLM via the OpenAI-compatible API.
    """
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.7,
        "max_tokens": 1000,
    }
    if grammar_text:
        payload["grammar"] = grammar_text

    try:
        print(f"Sending request to LLM server at {server_url}...")
        if grammar_text:
            print("  - Grammar constraint applied.")
        start_time = time.time()
        response = requests.post(server_url, headers=headers, data=json.dumps(payload))
        end_time = time.time()
        print(f"Received response in {end_time - start_time:.2f} seconds.")

        response.raise_for_status()
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0:
            json_output = response_data['choices'][0]['message']['content']
            return json_output
        else:
            print(f"Full response data: {response_data}")
            return None

    except requests.exceptions.RequestException as e:
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

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send a paper prompt to a local llama.cpp server.')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('paper_id', help='ID of the paper to process')
    parser.add_argument('--server_url', default=LLM_SERVER_URL, help='URL of the LLM server endpoint (default: http://localhost:8080/v1/chat/completions)')
    parser.add_argument('--model', default="default", help='Model name to pass in the request (often ignored by llama.cpp)')
    parser.add_argument('--output_file', '-o', help='Write the LLM output to a file (default: print to stdout)')
    parser.add_argument('--grammar_file', '-g', help='Path to the GBNF grammar file to constrain the output format')

    args = parser.parse_args()

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

    print(f"Fetching paper data for ID '{args.paper_id}' from database '{args.db_file}'...")
    paper_data = get_paper_by_id(args.db_file, args.paper_id)

    if not paper_data:
        print(f"Error: Paper with ID '{args.paper_id}' not found in database '{args.db_file}'.")
        exit(1)
    print("Paper data fetched successfully.")

    print("Building prompt...")
    prompt_text = build_prompt(paper_data)
    print("Prompt built.")

    print("Sending prompt to LLM...")
    # Pass the loaded grammar_content to the function
    json_result = send_prompt_to_llm(prompt_text, grammar_text=grammar_content, server_url=args.server_url, model_name=args.model)

    if json_result:
        print("\n------ LLM Output ------")
        if args.output_file:
            try:
                with open(args.output_file, 'w', encoding='utf-8') as f:
                    f.write(json_result)
                print(f"LLM output successfully written to '{args.output_file}'")
            except Exception as e:
                print(f"Error writing output to file '{args.output_file}': {e}")
                print("--- LLM Output (printed to stdout) ---")
                print(json_result)
        else:
            print(json_result)
        print("-----------------------")
    else:
        print("\nFailed to get a valid JSON response from the LLM.")
