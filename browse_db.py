# browse_db.py
import sqlite3
import json
import argparse
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import argparse
import os
import sys

import globals

app = Flask(__name__)
DATABASE = None # Will be set from command line argument

# --- Helper Functions ---

def get_db_connection():
    """Create a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
    return conn

def format_changed_timestamp(changed_str):
    """Format the ISO timestamp string to dd/mm/yy hh:mm:ss"""
    if not changed_str:
        return ""
    try:
        dt = datetime.fromisoformat(changed_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%y %H:%M:%S")
    except ValueError:
        # If parsing fails, return the original string or a placeholder
        return changed_str

def truncate_authors(authors_str, max_authors=2):
    """Truncate the authors list for the main table view."""
    if not authors_str:
        return ""
    authors_list = [a.strip() for a in authors_str.split(';')]
    if len(authors_list) > max_authors:
        return "; ".join(authors_list[:max_authors]) + " et al."
    else:
        return authors_str

def fetch_papers():
    """Fetch all papers from the database, optionally sorted."""
    conn = get_db_connection()
    query = "SELECT * FROM papers"
    params = []
    papers = conn.execute(query, params).fetchall()
    conn.close()
    
    # Convert rows to list of dicts, parse JSON, format timestamp, truncate authors
    paper_list = []
    for paper in papers:
        paper_dict = dict(paper)
        try:
            paper_dict['features'] = json.loads(paper_dict['features'])
        except (json.JSONDecodeError, TypeError):
            paper_dict['features'] = {}
        try:
            paper_dict['technique'] = json.loads(paper_dict['technique'])
        except (json.JSONDecodeError, TypeError):
            paper_dict['technique'] = {}
        
        # Format the changed timestamp for display
        paper_dict['changed_formatted'] = format_changed_timestamp(paper_dict.get('changed'))
        
        # Truncate authors for main table view
        paper_dict['authors_truncated'] = truncate_authors(paper_dict.get('authors', ''))
        
        paper_list.append(paper_dict)
    return paper_list


def update_paper_custom_fields(paper_id, data, changed_by="Web app"):
    """Update the custom classification fields for a paper and audit fields.
       Handles partial updates based on keys present in `data`."""

    conn = get_db_connection()
    cursor = conn.cursor()
    
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'

    update_fields = []
    update_values = []

    # Handle Main Boolean Fields (Partial Update)
    main_bool_fields = ['is_survey', 'is_offtopic', 'is_through_hole', 'is_smt', 'is_x_ray']
    for field in main_bool_fields:
        if field in data:
            value = data[field]
            if isinstance(value, str):
                if value.lower() in ('true', '1', 'on'):
                    update_fields.append(f"{field} = ?")
                    update_values.append(1)
                elif value.lower() in ('false', '0'):
                    update_fields.append(f"{field} = ?")
                    update_values.append(0)
                else: # 'unknown', '', None, etc.
                    update_fields.append(f"{field} = ?")
                    update_values.append(None)
            elif value is True:
                update_fields.append(f"{field} = ?")
                update_values.append(1)
            elif value is False:
                update_fields.append(f"{field} = ?")
                update_values.append(0)
            else: # value is None or numeric
                update_fields.append(f"{field} = ?")
                update_values.append(int(bool(value)) if value is not None else None)

    # Handle Research Area (Partial Update)
    if 'research_area' in data:
        update_fields.append("research_area = ?")
        update_values.append(data['research_area'])

    # Handle Page Count (Partial Update)
    if 'page_count' in data:
        page_count_value = data['page_count']
        if page_count_value is not None:
            try:
                page_count_value = int(page_count_value)
            except (ValueError, TypeError):
                page_count_value = None

        update_fields.append("page_count = ?")
        update_values.append(page_count_value)
    
    # Handle Verified By (Partial Update)
    if 'verified_by' in data:
        verified_by_value = data['verified_by']
        # Ensure value is either 'user' or None. Others (like model names) are treated as None.
        # This enforces that the UI can only set 'user' or clear it.
        if verified_by_value != 'user':
            verified_by_value = None
        update_fields.append("verified_by = ?")
        update_values.append(verified_by_value)
        
    # Handle Features (Partial Update)
    # Fetch current features JSON from DB to merge changes
    cursor.execute("SELECT features FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    if row:
        try:
            current_features = json.loads(row['features']) if row['features'] else {}
        except (json.JSONDecodeError, TypeError):
            current_features = {}
    else:
        current_features = {}

    # Check for feature fields in the incoming data
    feature_updates = {}
    for key in list(data.keys()): # Iterate over a copy to safely modify data
        if key.startswith('features_'):
            feature_key = key.split('features_')[1]
            value = data.pop(key) # Remove from main data dict
            if feature_key == 'other':
                feature_updates[feature_key] = value # Text field
            else:
                # Handle radio button group for 3-state (true/false/unknown)
                if isinstance(value, str):
                    if value == 'true':
                        feature_updates[feature_key] = True
                    elif value == 'false':
                        feature_updates[feature_key] = False
                    else: # 'unknown' or anything else
                        feature_updates[feature_key] = None
                elif isinstance(value, bool):
                    feature_updates[feature_key] = value
                else: # None or numeric
                    feature_updates[feature_key] = bool(value) if value is not None else None

    if feature_updates:
        current_features.update(feature_updates)
        update_fields.append("features = ?")
        update_values.append(json.dumps(current_features))

    # Handle Techniques (Partial Update)
    # Fetch current technique JSON from DB to merge changes
    cursor.execute("SELECT technique FROM papers WHERE id = ?", (paper_id,))
    row = cursor.fetchone()
    if row:
        try:
            current_technique = json.loads(row['technique']) if row['technique'] else {}
        except (json.JSONDecodeError, TypeError):
            current_technique = {}
    else:
        current_technique = {}

    # Check for technique fields in the (potentially modified) data
    technique_updates = {}
    for key in list(data.keys()):
        if key.startswith('technique_'):
            technique_key = key.split('technique_')[1]
            value = data.pop(key) # Remove from main data dict
            if technique_key == 'model':
                technique_updates[technique_key] = value # Text field
            elif technique_key == 'available_dataset':
                 # Handle radio button group for 3-state (true/false/unknown)
                if isinstance(value, str):
                    if value == 'true':
                        technique_updates[technique_key] = True
                    elif value == 'false':
                        technique_updates[technique_key] = False
                    else: # 'unknown' or anything else
                        technique_updates[technique_key] = None
                elif isinstance(value, bool):
                    technique_updates[technique_key] = value
                else: # None or numeric
                    technique_updates[technique_key] = bool(value) if value is not None else None
            else: # classic_computer_graphics_based, machine_learning_based, hybrid
                 # Handle radio button group for 3-state (true/false/unknown)
                if isinstance(value, str):
                    if value == 'true':
                        technique_updates[technique_key] = True
                    elif value == 'false':
                        technique_updates[technique_key] = False
                    else: # 'unknown' or anything else
                        technique_updates[technique_key] = None
                elif isinstance(value, bool):
                    technique_updates[technique_key] = value
                else: # None or numeric
                    technique_updates[technique_key] = bool(value) if value is not None else None

    # Merge updates into current technique
    if technique_updates:
        current_technique.update(technique_updates)
        update_fields.append("technique = ?")
        update_values.append(json.dumps(current_technique))

    # Always update audit fields for any change
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
        rows_affected = 0 # No fields to update
    conn.close()

    if rows_affected > 0:
        conn = get_db_connection()
        updated_paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        conn.close()
        
        if updated_paper:
            updated_dict = dict(updated_paper)
            try:
                updated_dict['features'] = json.loads(updated_dict['features'])
            except (json.JSONDecodeError, TypeError):
                updated_dict['features'] = {}
            try:
                updated_dict['technique'] = json.loads(updated_dict['technique'])
            except (json.JSONDecodeError, TypeError):
                updated_dict['technique'] = {}
            
            updated_dict['changed_formatted'] = format_changed_timestamp(updated_dict.get('changed'))
            
            return_data = {
                'status': 'success',
                'changed': updated_dict.get('changed'),
                'changed_formatted': updated_dict['changed_formatted'],
                'changed_by': updated_dict.get('changed_by'),
                # Include updated fields for frontend refresh
                'research_area': updated_dict.get('research_area'),
                'page_count': updated_dict.get('page_count'),
                'is_survey': updated_dict.get('is_survey'),
                'is_offtopic': updated_dict.get('is_offtopic'),
                'is_through_hole': updated_dict.get('is_through_hole'),
                'is_smt': updated_dict.get('is_smt'),
                'is_x_ray': updated_dict.get('is_x_ray'),
                'features': updated_dict['features'], # Parsed dict
                'technique': updated_dict['technique'] # Parsed dict
            }
            return return_data
        else:
            return {'status': 'error', 'message': 'Paper not found after update.'}
    else:
        return {'status': 'error', 'message': 'No rows updated. Paper ID might not exist or no changes were made.'}


# --- Routes ---
@app.route('/', methods=['GET'])
def index():
    """Main page to display the table."""
    sort_by = request.args.get('sort_by')
    sort_order = request.args.get('sort_order', 'ASC')
    papers = fetch_papers()
    # Pass the render_status function and globals.TYPE_EMOJIS to the template
    return render_template(
        'index.html', 
        papers=papers, 
        sort_by=sort_by, 
        sort_order=sort_order,
        type_emojis=globals.TYPE_EMOJIS,
        default_type_emoji=globals.DEFAULT_TYPE_EMOJI
    )

@app.route('/update_paper', methods=['POST'])
def update_paper():
    """Endpoint to handle AJAX updates (partial or full)."""
    data = request.get_json()
    paper_id = data.get('id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        # Use 'Web app' as the identifier for changes made via this interface
        result = update_paper_custom_fields(paper_id, data, changed_by="Web app")
        # The result dict already contains status and other data
        return jsonify(result)
    except Exception as e:
        print(f"Error updating paper {paper_id}: {e}") # Log error
        return jsonify({'status': 'error', 'message': 'Failed to update database'}), 500


# --- Jinja2-like filter for status rendering ---
def render_status(value):
    """Render status value as emoji/symbol"""
    if value == 1 or value is True:
        return '✔️' # Checkmark for True
    elif value == 0 or value is False:
        return '❌' # Cross for False
    else: # None or unknown
        return '❔' # Question mark for Unknown/Null

# --- Jinja2-like filter for verified_by rendering (MODIFIED) ---
def render_verified_by(value):
    """
    Render verified_by value as emoji.
    Accepts the raw database value.
    Returns HTML string with emoji and tooltip if needed.
    """
    if value == 'user':
        return f'<span title="User">👤</span>' # Human emoji
    elif value is None or value == '':
        return f'<span title="Unverified">❔</span>'
    else:
        # For any other string, value is a model name, show computer emoji with tooltip
        # Escape the model name for HTML attribute safety
        escaped_model_name = str(value).replace('"', '&quot;').replace("'", "&#39;")
        return f'<span title="{escaped_model_name}">🖥️</span>'
    
from markupsafe import Markup # Import Markup for safe HTML rendering
@app.template_filter('render_status')
def render_status_filter(value):
    return render_status(value)

@app.template_filter('render_verified_by')
def render_verified_by_filter(value):
    # Use Markup to tell Jinja2 that the output is safe HTML
    return Markup(render_verified_by(value)) 


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Browse and edit PCB inspection papers database.')
    parser.add_argument('db_file', nargs='?', help='SQLite database file path (optional)')
    args = parser.parse_args()
    
    # Determine which database file to use
    if args.db_file:
        DATABASE = args.db_file
    elif hasattr(globals, 'DATABASE_FILE'):
        DATABASE = globals.DATABASE_FILE
    else:
        print("Error: No database file specified and no default in globals.DATABASE_FILE")
        sys.exit(1)

    # Check if database exists before starting server
    if not os.path.exists(DATABASE):
        print(f"Error: Database file not found: {DATABASE}")
        print("Please provide a valid database file.")
        sys.exit(1)

    # Verify the database has the required tables
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
        if not cursor.fetchone():
            print(f"Error: Database '{DATABASE}' does not contain required 'papers' table")
            sys.exit(1)
        conn.close()
    except sqlite3.Error as e:
        print(f"Error verifying database: {e}")
        sys.exit(1)

    print(f"Starting server, database: {DATABASE}")
    print(" * Visit http://127.0.0.1:5000 to view the table.")
    
    # Ensure the templates and static folders exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static'):
        os.makedirs('static')
    app.run(debug=True) # Set debug=False for production