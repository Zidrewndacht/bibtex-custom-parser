# web/routes_ui.py
import json
from flask import Blueprint, render_template, request, jsonify
from shared import db
from shared import config
from . import export_logic

ui_bp = Blueprint('ui', __name__)

domain_config = config.load_domain_config()

def render_papers_table(hide_offtopic_param=None, year_from_param=None, year_to_param=None, min_page_count_param=None):
    """Fetches papers based on filters and renders the papers_table.html template. 
       Used for initial render from / and XHR updates."""
    # Determine hide_offtopic state
    hide_offtopic = True # Default
    if hide_offtopic_param is not None:
        hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

    # Determine filter values, using defaults if not provided or invalid
    year_from_value = int(year_from_param) if year_from_param is not None else config.DEFAULT_YEAR_FROM
    year_to_value = int(year_to_param) if year_to_param is not None else config.DEFAULT_YEAR_TO
    min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else config.DEFAULT_MIN_PAGE_COUNT

    # Fetch papers with ALL the filters applied
    papers = db.fetch_papers(
        domain_config=domain_config, # <-- ADD THIS
        hide_offtopic=hide_offtopic,
        year_from=year_from_value,
        year_to=year_to_value,
        min_page_count=min_page_count_value,
    )

    # Render the table template fragment, passing the search query value for the input field
    rendered_table = render_template(
        'papers_table.html',
        papers=papers,
        type_emojis=config.TYPE_EMOJIS,
        default_type_emoji=config.DEFAULT_TYPE_EMOJI,
        pdf_emojis=config.PDF_EMOJIS, # Pass the PDF emojis dictionary
        hide_offtopic=hide_offtopic,
        # Pass the *string representations* of the values to the template for input fields
        year_from_value=str(year_from_value),
        year_to_value=str(year_to_value),
        min_page_count_value=str(min_page_count_value)
    )
    return rendered_table

@ui_bp.route('/', methods=['GET'])
def index():
    """Main page to display the table."""
    # Get initial filter parameters from the request (or they will default inside render_papers_table)
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')
        
    # Get the total number of papers in the database.
    with db.get_db() as conn:
        total_paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        
    papers_table_content = render_papers_table(
        hide_offtopic_param=hide_offtopic_param,
        year_from_param=year_from_param,
        year_to_param=year_to_param,
        min_page_count_param=min_page_count_param,
    )
    # Pass the rendered table content and filter values to the main index template
    # Determine values to display in the input fields (use defaults if URL params were missing/invalid)
    try:
        year_from_input_value = str(int(year_from_param)) if year_from_param is not None else str(config.DEFAULT_YEAR_FROM)
    except ValueError:
        year_from_input_value = str(config.DEFAULT_YEAR_FROM)
    try:
        year_to_input_value = str(int(year_to_param)) if year_to_param is not None else str(config.DEFAULT_YEAR_TO)
    except ValueError:
        year_to_input_value = str(config.DEFAULT_YEAR_TO)
    try:
        min_page_count_input_value = str(int(min_page_count_param)) if min_page_count_param is not None else str(config.DEFAULT_MIN_PAGE_COUNT)
    except ValueError:
        min_page_count_input_value = str(config.DEFAULT_MIN_PAGE_COUNT)
    hide_offtopic_checkbox_checked = hide_offtopic_param is None or hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

    return render_template(
        'index.html', domain_config=domain_config,
        papers_table_content=papers_table_content,
        hide_offtopic=hide_offtopic_checkbox_checked,
        year_from_value=year_from_input_value,
        year_to_value=year_to_input_value,
        min_page_count_value=min_page_count_input_value,
        total_paper_count=total_paper_count
    )

@ui_bp.route('/load_table', methods=['GET'])
def load_table():
    """Endpoint to fetch and render the table content based on current filters."""
    return render_papers_table(
        hide_offtopic_param=request.args.get('hide_offtopic'), year_from_param=request.args.get('year_from'),
        year_to_param=request.args.get('year_to'), min_page_count_param=request.args.get('min_page_count'),
    )

@ui_bp.route('/get_detail_row', methods=['GET'])
def get_detail_row():
    paper_id = request.args.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400
    try:
        paper_dict = db.get_paper_by_id(paper_id)
        if paper_dict:
            try: paper_dict['classification'] = json.loads(paper_dict['classification']) if paper_dict['classification'] else {}
            except: paper_dict['classification'] = {}
            detail_html = render_template('detail_row.html', paper=paper_dict, domain_config=domain_config)
            return jsonify({'status': 'success', 'html': detail_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
    except Exception as e:
        print(f"Error fetching detail row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch detail row'}), 500

@ui_bp.route('/get_history_row', methods=['GET'])
def get_history_row():
    """Endpoint to fetch and render the history row content for a specific paper."""
    paper_id = request.args.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400
        
    try:
        paper = db.get_paper_by_id(paper_id)
            
        if paper:
            paper_dict = dict(paper)
            try: paper_dict['classification'] = json.loads(paper_dict['classification']) if paper_dict['classification'] else {}
            except: paper_dict['classification'] = {}
            try: paper_dict['main_certainty'] = json.loads(paper_dict['main_certainty']) if paper_dict['main_certainty'] else {}
            except: paper_dict['main_certainty'] = {}
                    
            # Prepare ALL 4 logs using the SAME function
            paper_dict['llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=None)
            paper_dict['set_1_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=1)
            paper_dict['set_2_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=2)
            paper_dict['set_3_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=3)
            
            # Render the history row template
            history_html = render_template('history_row.html', paper=paper_dict, domain_config=domain_config)
            return jsonify({'status': 'success', 'html': history_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
            
    except Exception as e:
        print(f"Error fetching history row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch history row'}), 500
    