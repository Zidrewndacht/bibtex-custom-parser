# web/routes_data.py
import os
import tempfile
import requests
from flask import Blueprint, request, jsonify
from shared import db
from shared import config
from . import importer

data_bp = Blueprint('data', __name__)

@data_bp.route('/update_paper', methods=['POST'])
def update_paper():
    """Endpoint to handle AJAX updates (partial or full)."""
    data = request.get_json()
    paper_id = data.get('id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        # Use 'user' as the identifier for changes made via this interface
        result = db.update_paper_custom_fields(paper_id, data, changed_by="user")
        # The result dict already contains status and other data
        return jsonify(result)
    except Exception as e:
        print(f"Error updating paper {paper_id}: {e}") # Log error
        return jsonify({'status': 'error', 'message': 'Failed to update database'}), 500

@data_bp.route('/classify', methods=['POST'])
def classify_paper():
    """Endpoint to handle classification requests."""
    data = request.get_json()
    mode = data.get('mode', 'id')
    paper_id = data.get('paper_id')
    
    # Determine which queue_manager endpoint to use
    if mode == 'consensus':
        endpoint = '/consensus'
    else:
        endpoint = '/classify'
    
    # Try to call queue manager
    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}{endpoint}",
            json={'mode': mode, 'paper_id': paper_id},
            timeout=None  # No timeout for single-paper requests
        )
        if response.status_code == 200:
            result = response.json()
            if mode == 'id':
                # Single paper - fetch updated data and return
                updated_data = db.fetch_updated_paper_data(paper_id)
                return jsonify(updated_data)
            else:
                # Batch - return immediately
                return jsonify({'status': 'started', 'message': f'Batch classification ({mode}) initiated.'})
        else:
            return jsonify({'status': 'error', 'message': 'Queue manager returned error'}), 500
    except requests.exceptions.RequestException as e:
        # Queue manager unavailable
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503
    
@data_bp.route('/verify', methods=['POST'])
def verify_paper():
    """Endpoint to handle verification requests."""
    data = request.get_json()
    mode = data.get('mode', 'id')
    paper_id = data.get('paper_id')
    
    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}/verify",
            json={'mode': mode, 'paper_id': paper_id},
            timeout=None
        )
        
        if response.status_code == 200:
            result = response.json()
            if mode == 'id':
                updated_data = db.fetch_updated_paper_data(paper_id)
                return jsonify(updated_data)
            else:
                return jsonify({'status': 'started', 'message': f'Batch verification ({mode}) initiated.'})
        else:
            return jsonify({'status': 'error', 'message': 'Queue manager returned error'}), 500
    
    except requests.exceptions.RequestException as e:
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503
    
@data_bp.route('/upload_bibtex', methods=['POST'])
def upload_bibtex():
    if 'file' not in request.files: return jsonify({'status': 'error', 'message': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'status': 'error', 'message': 'No selected file'}), 400
    filename = file.filename.lower()
    
    tmp_file_path = None
    tmp_bib_path = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            tmp_file_path = tmp_file.name
            
        if filename.endswith('.bib'):
            importer.import_bibtex(tmp_file_path, config.DATABASE_FILE)
        elif filename.endswith('.csv'):
            bibtex_entries = importer.convert_csv_to_bibtex(tmp_file_path)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.bib') as tmp_bib_file:
                for entry in bibtex_entries:
                    tmp_bib_file.write(entry.encode('utf-8'))
                tmp_bib_path = tmp_bib_file.name
            importer.import_bibtex(tmp_bib_path, config.DATABASE_FILE)
        else:
            return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload a .bib or .csv file.'}), 400
            
        return jsonify({'status': 'success', 'message': f'{"BibTeX" if filename.endswith(".bib") else "CSV"} file imported successfully.'})
    except Exception as e:
        print(f"Error importing file: {e}")
        return jsonify({'status': 'error', 'message': f'Import failed: {str(e)}'}), 500
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            try: os.unlink(tmp_file_path)
            except: pass
        if tmp_bib_path and os.path.exists(tmp_bib_path):
            try: os.unlink(tmp_bib_path)
            except: pass