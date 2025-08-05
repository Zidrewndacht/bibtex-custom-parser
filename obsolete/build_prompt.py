import sqlite3
# import json
import argparse

# Define default JSON structures for features and technique (from import_bibtex.py)
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

# Example YAML template (as a multi-line string)
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

def build_prompt(paper_data):
    """Builds the prompt string for a single paper."""
    
    # Extract basic fields
    title = paper_data.get('title', '')
    abstract = paper_data.get('abstract', '')
    keywords = paper_data.get('keywords', '')
    authors = paper_data.get('authors', '')
    year = paper_data.get('year', '')
    type = paper_data.get('type', '') # Covers journal/conf
    journal = paper_data.get('journal', '') # Covers journal/conf
    
    # Start building the prompt
    prompt_lines = [
        "Read the following paper title, abstract and keywords:",
        "\nTitle:", title,
        "\nAbstract:", abstract,
        "\nKeywords:", keywords,
        "\nAuthors:", authors,
        "\nPublication Year:", str(year), # Ensure year is a string
        "\nPublication Type:", type,
        "\nPublication Name:", journal,
        "\nGiven the contents of the paper, fill in the following YAML structure exactly and convert it to JSON. Do not add, remove or move any fields.",
        "Only write 'true' or 'false' if the contents above make it clear that it is the case. If unsure, fill the field with null:",
        "The example below is not related to the paper above, use it only as a reference for the structure itself.",
        "", # Blank line
        YAML_TEMPLATE.strip(), # Include the template without extra newlines
        "", # Blank line
        "Your response is not being read by a human, it is grammar-locked via GBNF and goes directly to an automated parser. Answer with nothing but the structure itself directly. Output in JSON format"
    ]
    
    return "\n".join(prompt_lines)

def get_paper_by_id(db_path, paper_id):
    """Fetches a single paper's data from the database by its ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    
    if row:
        paper_dict = dict(row)
        # Parse JSON fields if needed (though not strictly necessary for prompt building)
        # The prompt uses the raw text fields from the DB
        conn.close()
        return paper_dict
    else:
        conn.close()
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build a prompt for a paper from the database.')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('paper_id', help='ID of the paper to build the prompt for')
    # Optional: Add argument for output file instead of printing
    parser.add_argument('-o', '--output', help='Write prompt to a file instead of stdout')
    
    args = parser.parse_args()
    
    paper_data = get_paper_by_id(args.db_file, args.paper_id)
    
    if not paper_data:
        print(f"Error: Paper with ID '{args.paper_id}' not found in database '{args.db_file}'.")
        exit(1)
        
    prompt_text = build_prompt(paper_data)
    
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(prompt_text)
            print(f"Prompt written to '{args.output}'")
        except Exception as e:
            print(f"Error writing to file '{args.output}': {e}")
            exit(1)
    else:
        print(prompt_text)
