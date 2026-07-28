# web/routes_ui.py
import json
import sqlite3
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from shared import db
from shared import config
from . import export_logic

ui_bp = Blueprint('ui', __name__)

# Load domain config once at module level
from shared.config import load_domain_config
domain_config = load_domain_config()

# web/routes_ui.py
def render_papers_table(hide_offtopic_param=None, year_from_param=None, year_to_param=None, min_page_count_param=None):
    hide_offtopic = True
    if hide_offtopic_param is not None:
        hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']
        
    year_from_value = int(year_from_param) if year_from_param is not None else config.DEFAULT_YEAR_FROM
    year_to_value = int(year_to_param) if year_to_param is not None else config.DEFAULT_YEAR_TO
    min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else config.DEFAULT_MIN_PAGE_COUNT

    papers = db.fetch_papers(
        hide_offtopic=hide_offtopic,
        year_from=year_from_value,
        year_to=year_to_value,
        min_page_count=min_page_count_value,
    )
    
    rendered_table = render_template(
        'papers_table.html',
        papers=papers,
        domain_config=domain_config,
        type_emojis=config.TYPE_EMOJIS,
        default_type_emoji=config.DEFAULT_TYPE_EMOJI,
        pdf_emojis=config.PDF_EMOJIS,
        hide_offtopic=hide_offtopic,
        year_from_value=str(year_from_value),
        year_to_value=str(year_to_value),
        min_page_count_value=str(min_page_count_value),
        search_query_value = request.args.get('search_query', '')
    )
    return rendered_table

@ui_bp.route('/', methods=['GET'])
def index():
    # Self-heal if the database file exists but the 'papers' table is missing/corrupted
    try:
        with db.get_db() as conn:
            total_paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    except sqlite3.OperationalError as e:
        if "no such table: papers" or "unable to open database file" in str(e):
            print("[Web] 'papers' table missing or corrupted. Rebuilding schema and reloading without filters...")
            # Force rebuild the DB and placeholder row
            db.init_db(config.DATABASE_FILE)
            # Redirect to base '/' without query parameters so active filters don't hide the placeholder!
            return redirect(url_for('ui.index'))
        raise

    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')
        
    papers_table_content = render_papers_table(
        hide_offtopic_param=hide_offtopic_param,
        year_from_param=year_from_param,
        year_to_param=year_to_param,
        min_page_count_param=min_page_count_param,
    )
    
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
        'index.html',
        domain_config=domain_config,
        papers_table_content=papers_table_content,
        hide_offtopic=hide_offtopic_checkbox_checked,
        year_from_value=year_from_input_value,
        year_to_value=year_to_input_value,
        min_page_count_value=min_page_count_input_value,
        total_paper_count=total_paper_count
    )

@ui_bp.route('/load_table', methods=['GET'])
def load_table():
    return render_papers_table(
        hide_offtopic_param=request.args.get('hide_offtopic'),
        year_from_param=request.args.get('year_from'),
        year_to_param=request.args.get('year_to'),
        min_page_count_param=request.args.get('min_page_count'),
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

            paper_dict['llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=None)
            paper_dict['set_1_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=1)
            paper_dict['set_2_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=2)
            paper_dict['set_3_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=3)

            history_html = render_template('history_row.html', paper=paper_dict, domain_config=domain_config)
            return jsonify({'status': 'success', 'html': history_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
    except Exception as e:
        print(f"Error fetching history row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch history row'}), 500