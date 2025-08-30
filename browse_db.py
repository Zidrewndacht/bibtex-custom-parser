# browse_db.py
import sqlite3
import json
import argparse
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from markupsafe import Markup 
import argparse
import tempfile
import os
import sys
import threading
import webbrowser
from collections import Counter

# Import globals, the classification and verification modules
import globals
import automate_classification
import verify_classification

# Define default year range
DEFAULT_YEAR_FROM = 2020
DEFAULT_YEAR_TO = 2025
DEFAULT_MIN_PAGE_COUNT = 4

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

def fetch_papers(hide_offtopic=True, year_from=None, year_to=None, min_page_count=None, search_query=None):
    """Fetch papers from the database, applying various optional filters."""
    conn = get_db_connection()
    query = "SELECT * FROM papers"
    conditions = []
    params = []

    # --- Existing Filters ---
    if hide_offtopic:
        conditions.append("(is_offtopic = 0 OR is_offtopic IS NULL)")

    if year_from is not None:
        try:
            year_from = int(year_from)
            conditions.append("year >= ?")
            params.append(year_from)
        except (ValueError, TypeError):
            pass

    if year_to is not None:
        try:
            year_to = int(year_to)
            conditions.append("year <= ?")
            params.append(year_to)
        except (ValueError, TypeError):
            pass

    if min_page_count is not None:
        try:
            min_page_count = int(min_page_count)
            conditions.append("(page_count IS NULL OR page_count = '' OR page_count > ?)")
            params.append(min_page_count)
        except (ValueError, TypeError):
            pass

    # --- NEW: Search Filter ---
    if search_query:
        # Define the columns to search (exclude reasoning_trace, verifier_trace, features, technique as they need special handling or are JSON)
        searchable_columns = [
            'id', 'type', 'title', 'authors', 'month', 'journal',
            'volume', 'pages', 'doi', 'issn', 'abstract', 'keywords',
            'research_area', 'user_trace' # Include user_trace in search
        ]
        # Create a list of LIKE conditions for each searchable column
        search_conditions = []
        # Add wildcard to the search term for partial matching
        search_term_like = f"%{search_query}%"
        for col in searchable_columns:
            search_conditions.append(f"LOWER({col}) LIKE LOWER(?)")
            params.append(search_term_like)

        # Handle JSON columns (features, technique) - search within the JSON text representation
        # Note: This is a basic text search within the JSON string. For complex JSON queries, consider using SQLite's JSON1 extension.
        json_search_term = search_term_like # Use the same search term
        json_conditions = []
        for json_col in ['features', 'technique']:
             # Search within the JSON string representation
             json_conditions.append(f"LOWER({json_col}) LIKE LOWER(?)")
             params.append(json_search_term)

        # Combine column and JSON search conditions
        all_search_conditions = search_conditions + json_conditions
        if all_search_conditions:
            # Group search conditions together with OR
            combined_search_condition = " OR ".join(all_search_conditions)
            # Wrap the search conditions in parentheses to ensure correct precedence with other filters
            conditions.append(f"({combined_search_condition})")


    # --- Build Final Query ---
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Debug: Print the final query and params (optional)
    # print(f"DEBUG SQL Query: {query}")
    # print(f"DEBUG SQL Params: {params}")

    papers = conn.execute(query, params).fetchall()
    conn.close()

    # --- Process Results (Same as before) ---
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
        paper_dict['changed_formatted'] = format_changed_timestamp(paper_dict.get('changed'))
        paper_dict['authors_truncated'] = truncate_authors(paper_dict.get('authors', ''))
        paper_list.append(paper_dict)
    return paper_list

# Editing functions: update_paper_custom_fields, fetch_updated_paper_data
def update_paper_custom_fields(paper_id, data, changed_by="user"):
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


    page_count_value_for_pages_update = None # Variable to hold the value for potential 'pages' update
    if 'page_count' in data:
        page_count_value = data['page_count']
        if page_count_value is not None:
            try:
                page_count_value = int(page_count_value)
                # Store the integer value for potential 'pages' update
                page_count_value_for_pages_update = page_count_value 
            except (ValueError, TypeError):
                page_count_value = None
                page_count_value_for_pages_update = None # Reset if invalid
        else:
            page_count_value_for_pages_update = None # Reset if None
        
        update_fields.append("page_count = ?")
        update_values.append(page_count_value)

        cursor.execute("SELECT pages FROM papers WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        if row:
            current_pages_value = row['pages']
            # Check if 'pages' is effectively empty/blank/null
            # This checks for None, empty string, or string with only whitespace
            if current_pages_value is None or (isinstance(current_pages_value, str) and current_pages_value.strip() == ""):
                # If 'pages' is blank and we have a valid page_count to set
                if page_count_value_for_pages_update is not None:
                    # Add the update for the 'pages' column
                    update_fields.append("pages = ?")
                    # Convert the integer page count back to string for the 'pages' TEXT column
                    update_values.append(str(page_count_value_for_pages_update)) 
        # --- END NEW LOGIC ---

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
            else: # classic_computer_vision_based, machine_learning_based, hybrid
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

    # Any remaining keys in 'data' are assumed to be direct column names
    for key, value in data.items(): # Iterate over the potentially modified data dict
        # Skip keys already handled or special keys
        if key in ['id', 'changed', 'changed_by', 'verified_by'] or key in main_bool_fields or key.startswith(('features_', 'technique_')):
            continue
        # Treat remaining keys as direct column updates
        update_fields.append(f"{key} = ?")
        update_values.append(value)

    if update_fields:
        update_query = f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?"
        update_values.append(paper_id)
        # --- Debug prints ---
        # print(f"DEBUG: Updating paper {paper_id}")
        # print(f"DEBUG: SQL Query: {update_query}")
        # print(f"DEBUG: Values: {update_values}")
        # --- End Debug prints ---
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
                'relevance': updated_dict.get('relevance'),
                'features': updated_dict['features'], # Parsed dict
                'technique': updated_dict['technique'], # Parsed dict
                'user_trace': updated_dict.get('user_trace')
            }
            return return_data
        else:
            return {'status': 'error', 'message': 'Paper not found after update.'}
    else:
        return {'status': 'error', 'message': 'No rows updated. Paper ID might not exist or no changes were made.'}

def fetch_updated_paper_data(paper_id):
    """Fetches the full paper data after classification/verification for client-side update."""
    conn = get_db_connection()
    try:
        updated_paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
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
            
            # Prepare data for frontend refresh (matching update_paper_custom_fields structure)
            return_data = {
                'status': 'success',
                'changed': updated_dict.get('changed'),
                'changed_formatted': updated_dict['changed_formatted'],
                'changed_by': updated_dict.get('changed_by'),
                'verified_by': updated_dict.get('verified_by'),
                # Include updated fields for frontend refresh
                'research_area': updated_dict.get('research_area'),
                'page_count': updated_dict.get('page_count'),
                'is_survey': updated_dict.get('is_survey'),
                'is_offtopic': updated_dict.get('is_offtopic'),
                'is_through_hole': updated_dict.get('is_through_hole'),
                'is_smt': updated_dict.get('is_smt'),
                'is_x_ray': updated_dict.get('is_x_ray'),
                'relevance': updated_dict.get('relevance'),
                'verified': updated_dict.get('verified'),
                'estimated_score': updated_dict.get('estimated_score'),
                'features': updated_dict['features'], # Parsed dict
                'technique': updated_dict['technique'], # Parsed dict
                'reasoning_trace': updated_dict.get('reasoning_trace'), # Include traces
                'verifier_trace': updated_dict.get('verifier_trace'),
                'user_trace': updated_dict.get('user_trace')
            }
            return return_data
        else:
            return {'status': 'error', 'message': 'Paper not found after update.'}
    finally:
        conn.close()

# render_papers_table Used for initial render from / and XHR updates     
def render_papers_table(hide_offtopic_param=None, year_from_param=None, year_to_param=None, min_page_count_param=None, search_query_param=None):
    """Fetches papers based on filters and renders the papers_table.html template."""
    try:
        # Determine hide_offtopic state
        hide_offtopic = True # Default
        if hide_offtopic_param is not None:
            hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

        # Determine filter values, using defaults if not provided or invalid
        year_from_value = int(year_from_param) if year_from_param is not None else DEFAULT_YEAR_FROM
        year_to_value = int(year_to_param) if year_to_param is not None else DEFAULT_YEAR_TO
        min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else DEFAULT_MIN_PAGE_COUNT
        # --- NEW: Determine search query value ---
        search_query_value = search_query_param if search_query_param is not None else ""

        # Fetch papers with ALL the filters applied, including the new search query
        papers = fetch_papers(
            hide_offtopic=hide_offtopic,
            year_from=year_from_value,
            year_to=year_to_value,
            min_page_count=min_page_count_value,
            search_query=search_query_value # Pass the search query
        )

        # Render the table template fragment, passing the search query value for the input field
        rendered_table = render_template(
            'papers_table.html',
            papers=papers,
            type_emojis=globals.TYPE_EMOJIS,
            default_type_emoji=globals.DEFAULT_TYPE_EMOJI,
            hide_offtopic=hide_offtopic,
            # Pass the *string representations* of the values to the template for input fields
            year_from_value=str(year_from_value),
            year_to_value=str(year_to_value),
            min_page_count_value=str(min_page_count_value),
            # --- NEW: Pass search query value ---
            search_query_value=search_query_value
        )
        return rendered_table
    except Exception as e:
        # Log the error or handle it appropriately
        print(f"Error rendering papers table: {e}")
        # Return an error fragment or re-raise if preferred for the main route
        return "<p>Error loading table.</p>" # Basic error display


#Routes: 
@app.route('/', methods=['GET'])
def index():
    """Main page to display the table."""
    # Get initial filter parameters from the request (or they will default inside render_papers_table)
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')

    search_query_param = request.args.get('search_query')
    
    papers_table_content = render_papers_table(
        hide_offtopic_param=hide_offtopic_param,
        year_from_param=year_from_param,
        year_to_param=year_to_param,
        min_page_count_param=min_page_count_param,
        search_query_param=search_query_param  # Add this line
    )

    # Pass the rendered table content and filter values to the main index template
    # Determine values to display in the input fields (use defaults if URL params were missing/invalid)
    try:
        year_from_input_value = str(int(year_from_param)) if year_from_param is not None else str(DEFAULT_YEAR_FROM)
    except ValueError:
        year_from_input_value = str(DEFAULT_YEAR_FROM)

    try:
        year_to_input_value = str(int(year_to_param)) if year_to_param is not None else str(DEFAULT_YEAR_TO)
    except ValueError:
        year_to_input_value = str(DEFAULT_YEAR_TO)

    try:
        min_page_count_input_value = str(int(min_page_count_param)) if min_page_count_param is not None else str(DEFAULT_MIN_PAGE_COUNT)
    except ValueError:
        min_page_count_input_value = str(DEFAULT_MIN_PAGE_COUNT)

    hide_offtopic_checkbox_checked = hide_offtopic_param is None or hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']
    search_input_value = search_query_param if search_query_param is not None else ""
    
    return render_template(
        'index.html',
        papers_table_content=papers_table_content,
        hide_offtopic=hide_offtopic_checkbox_checked,
        year_from_value=year_from_input_value,
        year_to_value=year_to_input_value,
        min_page_count_value=min_page_count_input_value,
        search_query_value=search_input_value  # Add this line
    )

@app.route('/static_export', methods=['GET'])
def static_export():
    """Generate and serve a downloadable HTML snapshot based on current filters."""
    try:
        # --- Get filter parameters from the request (URL query params) ---
        hide_offtopic_param = request.args.get('hide_offtopic')
        year_from_param = request.args.get('year_from')
        year_to_param = request.args.get('year_to')
        min_page_count_param = request.args.get('min_page_count')
        search_query_param = request.args.get('search_query') # Include search

        # --- Determine filter values, using defaults if not provided or invalid ---
        hide_offtopic = True # Default
        if hide_offtopic_param is not None:
            hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

        year_from_value = int(year_from_param) if year_from_param is not None else DEFAULT_YEAR_FROM
        year_to_value = int(year_to_param) if year_to_param is not None else DEFAULT_YEAR_TO
        min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else DEFAULT_MIN_PAGE_COUNT
        search_query_value = search_query_param if search_query_param is not None else ""

        # --- Fetch papers based on these filters ---
        papers = fetch_papers(
            hide_offtopic=hide_offtopic,
            year_from=year_from_value,
            year_to=year_to_value,
            min_page_count=min_page_count_value,
            search_query=search_query_value # Pass the search query
        )

        # --- Read static file contents ---
        fonts_css_content = ""
        style_css_content = ""
        chart_js_content = ""
        ghpages_js_content = ""
        # Assuming static files are in a 'static' directory relative to the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        static_dir = os.path.join(script_dir, 'static')
        with open(os.path.join(static_dir, 'fonts.css'), 'r') as f:
            fonts_css_content = f.read()
        with open(os.path.join(static_dir, 'style.css'), 'r') as f:
            style_css_content = f.read()
        with open(os.path.join(static_dir, 'chart.js'), 'r') as f:
            chart_js_content = f.read()
        with open(os.path.join(static_dir, 'ghpages.js'), 'r', encoding='utf-8') as f:
            ghpages_js_content = f.read()

        # --- Render the static export template ---
        papers_table_static_export = render_template(
            'papers_table_static_export.html',
            papers=papers,
            type_emojis=globals.TYPE_EMOJIS,
            default_type_emoji=globals.DEFAULT_TYPE_EMOJI,
            hide_offtopic=hide_offtopic,
            year_from_value=str(year_from_value),
            year_to_value=str(year_to_value),
            min_page_count_value=str(min_page_count_value),
            search_query_value=search_query_value
        )

        # --- Render the main static export index template ---
        full_html_content = render_template(
            'index_static_export.html',
            papers_table_static_export=papers_table_static_export,
            hide_offtopic=hide_offtopic,
            year_from_value=year_from_value, # Pass raw values if needed by template logic
            year_to_value=year_to_value,
            min_page_count_value=min_page_count_value,
            search_query=search_query_value,
            # --- Pass static content ---
            fonts_css_content=Markup(fonts_css_content),
            style_css_content=Markup(style_css_content),
            chart_js_content=Markup(chart_js_content),
            ghpages_js_content=Markup(ghpages_js_content)
        )

        # --- Create a filename based on filters ---
        filename_parts = ["PCBPapers"]
        if year_from_value == year_to_value:
             filename_parts.append(str(year_from_value))
        else:
             filename_parts.append(f"{year_from_value}-{year_to_value}")
        if min_page_count_value > 0:
             filename_parts.append(f"min{min_page_count_value}pg")
        if hide_offtopic:
             filename_parts.append("noOfftopic")
        if search_query_value:
             # Sanitize search query for filename (basic)
             safe_search = "".join(c for c in search_query_value if c.isalnum() or c in (' ', '-', '_')).rstrip()
             if safe_search:
                 filename_parts.append(f"search_{safe_search[:20]}") # Limit length
        filename = "_".join(filename_parts) + ".html"

        # --- Return as a downloadable attachment ---
        from flask import Response
        return Response(
            full_html_content,
            mimetype="text/html",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        print(f"Error generating static export: {e}")
        # Return an error message or handle gracefully
        return "Error generating export file.", 500


@app.route('/get_detail_row', methods=['GET'])
def get_detail_row():
    """Endpoint to fetch and render the detail row content for a specific paper."""
    paper_id = request.args.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        conn = get_db_connection()
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        conn.close()

        if paper:
            # Process the paper data like in fetch_papers for consistency
            paper_dict = dict(paper)
            try:
                paper_dict['features'] = json.loads(paper_dict['features'])
            except (json.JSONDecodeError, TypeError):
                paper_dict['features'] = {}
            try:
                paper_dict['technique'] = json.loads(paper_dict['technique'])
            except (json.JSONDecodeError, TypeError):
                paper_dict['technique'] = {}
            
            # Render the detail row template fragment for this specific paper
            detail_html = render_template('detail_row.html', paper=paper_dict)
            return jsonify({'status': 'success', 'html': detail_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
    except Exception as e:
        print(f"Error fetching detail row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch detail row'}), 500

# Endpoint to load the table content via AJAX 
@app.route('/load_table', methods=['GET'])
def load_table():
    """Endpoint to fetch and render the table content based on current filters."""
    # Get filter parameters from the request
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')
    search_query_param = request.args.get('search_query')

    # Use the updated helper function to render the table, passing the search query
    table_html = render_papers_table(
        hide_offtopic_param=hide_offtopic_param,
        year_from_param=year_from_param,
        year_to_param=year_to_param,
        min_page_count_param=min_page_count_param,
        search_query_param=search_query_param # Pass the search query
    )
    return table_html

@app.route('/get_stats', methods=['GET'])
def get_stats():
    """Endpoint to fetch statistics (repeating journals, keywords, authors, research areas) based on current filters."""
    
    # --- Get filter parameters from the request (same as /load_table) ---
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')
    search_query_param = request.args.get('search_query')

    try:
        # --- Determine filter values, using defaults if not provided or invalid ---
        # Replicating logic from render_papers_table for consistency
        hide_offtopic = True # Default
        if hide_offtopic_param is not None:
            hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

        year_from_value = int(year_from_param) if year_from_param is not None else DEFAULT_YEAR_FROM
        year_to_value = int(year_to_param) if year_to_param is not None else DEFAULT_YEAR_TO
        min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else DEFAULT_MIN_PAGE_COUNT
        search_query_value = search_query_param if search_query_param is not None else ""

        # --- Fetch papers based on these filters ---
        papers = fetch_papers(
            hide_offtopic=hide_offtopic,
            year_from=year_from_value,
            year_to=year_to_value,
            min_page_count=min_page_count_value,
            search_query=search_query_value
        )

        # --- Calculate Stats from Fetched Papers ---
        journal_counter = Counter()
        keyword_counter = Counter()
        author_counter = Counter()
        research_area_counter = Counter()

        for paper in papers:
            # --- Journal/Conf ---
            journal = paper.get('journal')
            if journal:
                journal_counter[journal] += 1

            # --- Keywords ---
            # Keywords are stored as a single string, split by ';'
            keywords_str = paper.get('keywords', '')
            if keywords_str:
                 # Split robustly, handling potential extra spaces
                 keywords_list = [kw.strip() for kw in keywords_str.split(';') if kw.strip()]
                 keyword_counter.update(keywords_list)

            # --- Authors ---
            # Authors are stored as a single string, split by ';'
            authors_str = paper.get('authors', '')
            if authors_str:
                # Split robustly, handling potential extra spaces
                authors_list = [author.strip() for author in authors_str.split(';') if author.strip()]
                author_counter.update(authors_list)

            # --- Research Area ---
            research_area = paper.get('research_area')
            if research_area:
                research_area_counter[research_area] += 1

        # --- Filter counts > 1 and sort (matching client-side logic) ---
        def filter_and_sort(counter):
            # Filter items with count > 1
            filtered_items = {item: count for item, count in counter.items() if count > 1}
            # Sort by count descending, then by name ascending
            sorted_items = sorted(filtered_items.items(), key=lambda x: (-x[1], x[0]))
            # Convert back to a list of dictionaries for JSON serialization
            return [{'name': name, 'count': count} for name, count in sorted_items]

        stats_data = {
            'journals': filter_and_sort(journal_counter),
            'keywords': filter_and_sort(keyword_counter),
            'authors': filter_and_sort(author_counter),
            'research_areas': filter_and_sort(research_area_counter)
        }

        return jsonify({'status': 'success', 'data': stats_data})

    except Exception as e:
        print(f"Error calculating stats: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to calculate statistics'}), 500

@app.route('/update_paper', methods=['POST'])
def update_paper():
    """Endpoint to handle AJAX updates (partial or full)."""
    data = request.get_json()
    paper_id = data.get('id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        # Use 'user' as the identifier for changes made via this interface
        result = update_paper_custom_fields(paper_id, data, changed_by="user")
        # The result dict already contains status and other data
        return jsonify(result)
    except Exception as e:
        print(f"Error updating paper {paper_id}: {e}") # Log error
        return jsonify({'status': 'error', 'message': 'Failed to update database'}), 500

# --- New Routes for Classification and Verification ---
@app.route('/classify', methods=['POST'])
def classify_paper():
    """Endpoint to handle classification requests (single or batch)."""
    data = request.get_json()
    mode = data.get('mode', 'id') # Default to 'id' for single paper
    paper_id = data.get('paper_id')
    
    # Determine DB file (use command-line arg or global default)
    db_file = DATABASE 

    def run_classification_task():
        """Background task to run classification."""
        try:
            print(f"Starting classification task: mode={mode}, paper_id={paper_id}")
            # Call the appropriate function from automate_classification
            # Pass db_file explicitly or rely on its internal defaults/globals
            automate_classification.run_classification(
                mode=mode,
                paper_id=paper_id,
                db_file=db_file
                # grammar_file=..., prompt_template=..., server_url=... # Use defaults or override if needed
            )
            print(f"Classification task completed: mode={mode}, paper_id={paper_id}")
        except Exception as e:
            print(f"Error during background classification (mode={mode}, paper_id={paper_id}): {e}")
            # Consider logging this error more formally

    if mode in ['all', 'remaining']:
        # Run batch classification in a background thread to avoid blocking
        thread = threading.Thread(target=run_classification_task)
        thread.daemon = True # Dies with main process
        thread.start()
        # Return immediately
        return jsonify({'status': 'started', 'message': f'Batch classification ({mode}) initiated.'})
    elif mode == 'id' and paper_id:
        try:
            # Run single paper classification synchronously
            # The function updates the DB directly
            automate_classification.run_classification(
                mode=mode,
                paper_id=paper_id,
                db_file=db_file
            )
            # Fetch the updated data from the database
            updated_data = fetch_updated_paper_data(paper_id)
            if updated_data['status'] == 'success':
                return jsonify(updated_data)
            else:
                return jsonify(updated_data), 404 # Or 500 if it's a server error fetching data
        except Exception as e:
            print(f"Error classifying paper {paper_id}: {e}")
            return jsonify({'status': 'error', 'message': f'Classification failed: {str(e)}'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid mode or missing paper_id for single classification.'}), 400

@app.route('/verify', methods=['POST'])
def verify_paper():
    """Endpoint to handle verification requests (single or batch)."""
    data = request.get_json()
    mode = data.get('mode', 'id') # Default to 'id' for single paper
    paper_id = data.get('paper_id')
    
    # Determine DB file (use command-line arg or global default)
    db_file = DATABASE

    def run_verification_task():
        """Background task to run verification."""
        try:
            print(f"Starting verification task: mode={mode}, paper_id={paper_id}")
            # Call the appropriate function from verify_classification
            verify_classification.run_verification(
                mode=mode,
                paper_id=paper_id,
                db_file=db_file
            )
            print(f"Verification task completed: mode={mode}, paper_id={paper_id}")
        except Exception as e:
            print(f"Error during background verification (mode={mode}, paper_id={paper_id}): {e}")
            # Consider logging this error more formally

    if mode in ['all', 'remaining']:
        # Run batch verification in a background thread to avoid blocking
        thread = threading.Thread(target=run_verification_task)
        thread.daemon = True
        thread.start()
        # Return immediately
        return jsonify({'status': 'started', 'message': f'Batch verification ({mode}) initiated.'})
    elif mode == 'id' and paper_id:
        try:
            # Run single paper verification synchronously
            verify_classification.run_verification(
                mode=mode,
                paper_id=paper_id,
                db_file=db_file
            )
            # Fetch the updated data from the database
            updated_data = fetch_updated_paper_data(paper_id)
            if updated_data['status'] == 'success':
                return jsonify(updated_data)
            else:
                return jsonify(updated_data), 404 # Or 500
        except Exception as e:
            print(f"Error verifying paper {paper_id}: {e}")
            return jsonify({'status': 'error', 'message': f'Verification failed: {str(e)}'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid mode or missing paper_id for single verification.'}), 400


@app.route('/upload_bibtex', methods=['POST'])
def upload_bibtex():
    """Endpoint to handle BibTeX file upload and import."""
    global DATABASE # Assuming DATABASE is defined globally as before

    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file part'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No selected file'}), 400

    if file and file.filename.lower().endswith('.bib'):
        try:
            # Save the uploaded file to a temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.bib') as tmp_bib_file:
                file.save(tmp_bib_file.name)
                tmp_bib_path = tmp_bib_file.name

            # Use the existing import_bibtex logic
            # Import here to avoid potential circular imports if placed at the top
            import import_bibtex 

            # Call the import function with the temporary file and the global DB path
            import_bibtex.import_bibtex(tmp_bib_path, DATABASE)

            # Clean up the temporary file
            os.unlink(tmp_bib_path)

            return jsonify({'status': 'success', 'message': 'BibTeX file imported successfully.'})

        except Exception as e:
            # Ensure cleanup even if import fails
            if 'tmp_bib_path' in locals():
                try:
                    os.unlink(tmp_bib_path)
                except OSError:
                    pass # Ignore errors during cleanup
            print(f"Error importing BibTeX: {e}")
            return jsonify({'status': 'error', 'message': f'Import failed: {str(e)}'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload a .bib file.'}), 400



# --- Jinja2-like filters ---
def render_status(value):
    """Render status value as emoji/symbol"""
    if value == 1 or value is True:
        return '✔️' # Checkmark for True
    elif value == 0 or value is False:
        return '❌' # Cross for False
    else: # None or unknown
        return '❔' # Question mark for Unknown/Null

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

def render_changed_by(value):
    """
    Render changed_by value as emoji.
    Accepts the raw database value.
    Returns HTML string with emoji and tooltip if needed.
    """
    if value == 'user':
        return f'<span title="User">👤</span>' # Human emoji
    elif value is None or value == '':
        return f'<span title="Unknown">❔</span>' # Question mark for null/empty
    else:
        # For any other string, value is a model name, show computer emoji with tooltip
        escaped_model_name = str(value).replace('"', '&quot;').replace("'", "&#39;")
        return f'<span title="{escaped_model_name}">🖥️</span>'

@app.template_filter('render_changed_by')
def render_changed_by_filter(value):
    # Use Markup to tell Jinja2 that the output is safe HTML
    return Markup(render_changed_by(value))

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

    # Function to open the browser after a delay
    def open_browser():
        import time
        time.sleep(2)  # Wait for the server to start
        webbrowser.open("http://127.0.0.1:5000")

    # Start the browser opener in a separate thread
    threading.Thread(target=open_browser).start()

    print(" * Visit http://127.0.0.1:5000 to view the table.")
    
    # Ensure the templates and static folders exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static'):
        os.makedirs('static')
    app.run(host='0.0.0.0', port=5000, debug=True)