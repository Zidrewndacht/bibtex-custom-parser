# web/routes_files.py
import os
import io
import tempfile
import tarfile
import shutil
import zstandard as zstd
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, send_file, Response, abort
from shared import db
from shared import config
from . import export_logic
import json
import yaml

files_bp = Blueprint('files', __name__)

def _prompt_arcname(prompt_path: str, key: str) -> str:
    """
    Returns a safe tar member name for a user prompt file.

    If the file lives inside BASE_DIR, preserve its relative path.
    Otherwise, store it under prompt_templates/ with a key-prefixed filename.
    """
    try:
        rel = os.path.relpath(prompt_path, config.BASE_DIR).replace(os.sep, "/")
        if rel.startswith(".."):
            raise ValueError("Prompt path is outside BASE_DIR")
        return rel
    except ValueError:
        return f"prompt_templates/{key}_{os.path.basename(prompt_path)}"


def _add_user_prompt_templates_to_tar(tar):
    """
    Adds user-editable prompt fragments to a tar archive.

    Base templates are intentionally NOT included.
    """
    manifest = []

    for key, prompt_path in config.get_user_prompt_template_paths().items():
        if not os.path.isfile(prompt_path):
            print(f"[Backup] Warning: user prompt file missing, skipping: {prompt_path}")
            continue

        arcname = _prompt_arcname(prompt_path, key)
        tar.add(prompt_path, arcname=arcname)
        manifest.append({
            "key": key,
            "arcname": arcname,
        })

    if manifest:
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="prompt_manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))


def _restore_user_prompt_templates(temp_dir: str, extracted_domain_config_path: str):
    """
    Restores user-editable prompt fragments from the extracted backup.

    This must run BEFORE config.reload_domain_config(), so the reloaded
    domain config can assemble prompts from the restored files.
    """
    manifest_path = os.path.join(temp_dir, "prompt_manifest.json")
    manifest = []

    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f) or []
        except Exception:
            manifest = []

    manifest_by_key = {
        entry.get("key"): entry.get("arcname")
        for entry in manifest
        if isinstance(entry, dict) and entry.get("key")
    }

    # Determine prompt target paths from the domain_config being restored,
    # not from the currently running config.
    restored_cfg = {}
    if os.path.exists(extracted_domain_config_path):
        try:
            with open(extracted_domain_config_path, "r", encoding="utf-8") as f:
                restored_cfg = yaml.safe_load(f) or {}
        except Exception:
            restored_cfg = {}

    for key, target_path in config.get_user_prompt_template_paths(restored_cfg).items():
        arcname = manifest_by_key.get(key)

        if arcname:
            source_path = os.path.join(temp_dir, arcname)
        else:
            # Backward-compatible fallback for backups made before the manifest existed.
            try:
                rel_target = os.path.relpath(target_path, config.BASE_DIR).replace(os.sep, "/")
                if rel_target.startswith(".."):
                    raise ValueError("Prompt path is outside BASE_DIR")
                source_path = os.path.join(temp_dir, rel_target)
            except ValueError:
                source_path = os.path.join(
                    temp_dir,
                    "prompt_templates",
                    f"{key}_{os.path.basename(target_path)}",
                )

        if os.path.isfile(source_path):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            if os.path.exists(target_path):
                os.remove(target_path)

            shutil.move(source_path, target_path)
            print(f"[Restore] Restored user prompt file: {target_path}")

@files_bp.route('/backup', methods=['GET'])
def backup_database():
    """Creates a backup of the database and related files."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{timestamp}.parça.zst"
        
        # Create temporary directory for exports
        with tempfile.TemporaryDirectory() as temp_dir:
            # Generate HTML export (full, not lite)
            papers = db.fetch_papers(hide_offtopic=True, year_from=0, year_to=9999, min_page_count=0)
            html_content = export_logic.generate_html_export_content(papers, True, 0, 9999, 0, is_lite_export=False)
            html_path = os.path.join(temp_dir, 'export.html')
            with open(html_path, 'w', encoding='utf-8') as f: f.write(html_content)

            # Generate XLSX export
            xlsx_content = export_logic.generate_xlsx_export_content(papers)
            xlsx_path = os.path.join(temp_dir, 'export.xlsx')
            with open(xlsx_path, 'wb') as f:
                f.write(xlsx_content)

            # Create in-memory buffer for the backup
            buffer = io.BytesIO()
            # Create a Zstandard compressor
            cctx = zstd.ZstdCompressor(level=1, threads=-1)  # Fastest compression level    

            # Compress the tar directly to the buffer
            with tarfile.open(fileobj=buffer, mode='w') as tar:
                tar.add(config.DATABASE_FILE, arcname='data/new.sqlite')

                # Add PDF storage directories
                if os.path.exists(config.PDF_STORAGE_DIR):
                    tar.add(config.PDF_STORAGE_DIR, arcname='data/pdf')
                if os.path.exists(config.ANNOTATED_PDF_STORAGE_DIR):
                    tar.add(config.ANNOTATED_PDF_STORAGE_DIR, arcname='data/pdf_annotated')
                
                # Add export files
                tar.add(html_path, arcname='export.html')
                tar.add(xlsx_path, arcname='export.xlsx') 

                # Add domain config
                tar.add(config.DOMAIN_CONFIG_PATH, arcname='domain_config.yaml')

                # Add user-editable prompt templates, but not base templates
                _add_user_prompt_templates_to_tar(tar)
            
            # Get the uncompressed tar data
            tar_data = buffer.getvalue()
            
            # Now compress the tar data with zstd
            compressed_data = cctx.compress(tar_data)
            
            # Create a new buffer with the compressed data
            compressed_buffer = io.BytesIO(compressed_data)
            compressed_buffer.seek(0)
            
            # Create a response with the in-memory backup
            response = send_file(
                compressed_buffer,
                as_attachment=True,
                download_name=backup_filename,
                mimetype='application/zstd'
            )
            
            # Ensure the filename is set correctly in Content-Disposition
            response.headers['Content-Disposition'] = f'attachment; filename="{backup_filename}"'
            
            return response
    except Exception as e:
        print(f"Backup error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@files_bp.route('/restore', methods=['POST'])
def restore_database():
    """Restores database and related files from a backup."""
    try:
        if 'backup_file' not in request.files: return jsonify({'status': 'error', 'message': 'No backup file provided'}), 400
        file = request.files['backup_file']
        if file.filename == '': return jsonify({'status': 'error', 'message': 'No file selected'}), 400
        if not file.filename.endswith('.parça.zst'): return jsonify({'status': 'error', 'message': 'Invalid backup file format. Expected .parça.zst'}), 400
            

        # Create temporary directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save uploaded file temporarily
            temp_backup_path = os.path.join(temp_dir, 'backup.parça.zst')
            file.save(temp_backup_path)

            # Decompress and extract
            dctx = zstd.ZstdDecompressor()
            with open(temp_backup_path, 'rb') as compressed_file:
                with dctx.stream_reader(compressed_file) as decomp_stream:
                    with tarfile.open(fileobj=decomp_stream, mode='r|') as tar:
                        tar.extractall(path=temp_dir)

            # Paths in the extracted archive
            extracted_db_path = os.path.join(temp_dir, 'data', 'new.sqlite')
            extracted_pdf_dir = os.path.join(temp_dir, 'data', 'pdf')
            extracted_annotated_pdf_dir = os.path.join(temp_dir, 'data', 'pdf_annotated')
            extracted_domain_config_path = os.path.join(temp_dir, 'domain_config.yaml')

            # Verify required files exist
            if not os.path.exists(extracted_db_path):
                return jsonify({'status': 'error', 'message': 'Backup does not contain required database file'}), 500

            # Backup current data before restoring (single file name, overwrites previous)
            backup_current = "backup_before_restore.parça.zst"
            backup_current_path = os.path.join(os.getcwd(), backup_current)
            cctx = zstd.ZstdCompressor(level=1)
            with cctx.stream_writer(open(backup_current_path, 'wb')) as compressor:
                with tarfile.open(fileobj=compressor, mode='w|') as tar:
                    if os.path.exists(config.DATABASE_FILE): tar.add(config.DATABASE_FILE, arcname='data/new.sqlite')
                    if os.path.exists(config.PDF_STORAGE_DIR): tar.add(config.PDF_STORAGE_DIR, arcname='data/pdf')
                    if os.path.exists(config.ANNOTATED_PDF_STORAGE_DIR): tar.add(config.ANNOTATED_PDF_STORAGE_DIR, arcname='data/pdf_annotated')
                    if os.path.exists(config.DOMAIN_CONFIG_PATH): tar.add(config.DOMAIN_CONFIG_PATH, arcname='domain_config.yaml')
                    # Also preserve current user prompt files before overwriting them
                    _add_user_prompt_templates_to_tar(tar)

            # Perform restoration
            # 1. Replace database
            shutil.move(extracted_db_path, config.DATABASE_FILE)
            
            # 2. Replace PDF directories - only if they exist in the backup
            if os.path.exists(extracted_pdf_dir):
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(config.PDF_STORAGE_DIR), exist_ok=True)
                if os.path.exists(config.PDF_STORAGE_DIR): shutil.rmtree(config.PDF_STORAGE_DIR)
                shutil.move(extracted_pdf_dir, config.PDF_STORAGE_DIR)
            else: # Create empty annotated PDF directory if not in backup
                os.makedirs(config.PDF_STORAGE_DIR, exist_ok=True)
                
            if os.path.exists(extracted_annotated_pdf_dir):
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(config.ANNOTATED_PDF_STORAGE_DIR), exist_ok=True)
                # Remove existing directory if it exists
                if os.path.exists(config.ANNOTATED_PDF_STORAGE_DIR): shutil.rmtree(config.ANNOTATED_PDF_STORAGE_DIR)
                # Move the extracted directory
                shutil.move(extracted_annotated_pdf_dir, config.ANNOTATED_PDF_STORAGE_DIR)
            else: # Create empty annotated PDF directory if not in backup
                os.makedirs(config.ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)                

            # 3. Restore user prompt templates before reloading the domain config.
            _restore_user_prompt_templates(temp_dir, extracted_domain_config_path)

            # 4. Restore domain config
            if os.path.exists(extracted_domain_config_path):
                if os.path.exists(config.DOMAIN_CONFIG_PATH):
                    os.remove(config.DOMAIN_CONFIG_PATH)
                shutil.move(extracted_domain_config_path, config.DOMAIN_CONFIG_PATH)

            config.reload_domain_config()  # Hot-reload the web app's memory
            
            # Notify the queue manager process to hot-reload its memory
            try:
                import requests
                requests.post(f"{config.QUEUE_MANAGER_URL}/reload_config", timeout=2)
            except Exception:
                pass # Queue manager might not be running, which is fine
                
            return jsonify({
                'status': 'success', 
                'message': f'Restored successfully from backup. Previous data backed up as {backup_current}. Domain configuration automatically reloaded.'
            })
        
    except Exception as e:
        print(f"Restore error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@files_bp.route('/upload_pdf/<paper_id>', methods=['POST'])
def upload_pdf(paper_id):
    """Handles PDF file upload for a specific paper."""
    print(f"Received upload request for paper ID: {paper_id}") # Debug print

    if 'pdf_file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file part in request'}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file selected'}), 400
        
    if file and file.filename.lower().endswith('.pdf'):
        # original_filename = secure_filename(file.filename)
        unique_filename = f"{paper_id}.pdf"
        filepath = os.path.join(config.PDF_STORAGE_DIR, unique_filename)
        
        try:
            file.save(filepath)
            with db.get_db() as conn: conn.execute("UPDATE papers SET pdf_filename = ?, pdf_state = ? WHERE id = ?", (unique_filename, 'PDF', paper_id))
            updated_paper_data = db.fetch_updated_paper_data(paper_id)
            if updated_paper_data['status'] == 'success':
                updated_paper_data['pdf_filename'] = unique_filename
                updated_paper_data['pdf_state'] = 'PDF'
                return jsonify(updated_paper_data)
            if os.path.exists(filepath): os.remove(filepath)
            return jsonify({'status': 'error', 'message': 'Failed to fetch updated paper data after upload'}), 500
        except Exception as e:
            print(f"Error saving uploaded PDF for paper {paper_id}: {e}")
            if os.path.exists(filepath):
                try: os.remove(filepath)
                except: pass
            return jsonify({'status': 'error', 'message': 'Failed to save file'}), 500
    return jsonify({'status': 'error', 'message': 'File type not allowed, only PDFs are accepted'}), 400

@files_bp.route('/serve_pdf/<paper_id>')
def serve_pdf(paper_id):
    """
    Serves the correct PDF file (annotated or original) for the PDF.js viewer/annotator
    based on the paper_id. Also updates the pdf_state in the database
    based on the actual existence of the annotated files.
    """
    with db.get_db() as conn:
        paper = conn.execute("SELECT pdf_filename, pdf_state FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not paper or not paper['pdf_filename']:
            print(f"No PDF filename found in DB for paper_id: {paper_id}")
            abort(404)
        filename = paper['pdf_filename']
        current_db_state = paper['pdf_state']
        
    annotated_path = os.path.join(config.ANNOTATED_PDF_STORAGE_DIR, filename)
    original_path = os.path.join(config.PDF_STORAGE_DIR, filename)
    new_state = None
    file_to_serve = None
    
    if os.path.exists(annotated_path):
        new_state = 'annotated'
        file_to_serve = annotated_path
    elif os.path.exists(original_path):
        new_state = 'PDF'
        file_to_serve = original_path
    else:
        print(f"No PDF file found for paper_id: {paper_id} (filename: {filename})")
        new_state = 'none'
        with db.get_db() as conn:
            conn.execute("UPDATE papers SET pdf_state = ? WHERE id = ?", (new_state, paper_id))
        abort(404)
        
    if current_db_state != new_state:
        print(f"Updating pdf_state for {paper_id} from '{current_db_state}' to '{new_state}'")
        with db.get_db() as conn:
            conn.execute("UPDATE papers SET pdf_state = ? WHERE id = ?", (new_state, paper_id))
    else:
        print(f"pdf_state for {paper_id} is already correct ('{new_state}')")
        
    return send_from_directory(os.path.dirname(file_to_serve), os.path.basename(file_to_serve), as_attachment=False)

@files_bp.route('/upload_annotated_pdf/<paper_id>', methods=['POST'])
def upload_annotated_pdf(paper_id):
    """
    API call for annotator autosaving feature:
    Receives an annotated PDF file associated with a paper_id,
    saves it to the annotated storage directory, and updates the pdf_state.
    """
    # FIX 1: The frontend sends the file under the key 'pdf_file', not 'annotated_pdf_file'
    if 'pdf_file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file part in request'}), 400

    file = request.files['pdf_file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'status': 'error', 'message': 'Invalid or missing file'}), 400

    # FIX 2: Look up the actual filename from the DB instead of assuming {paper_id}.pdf
    with db.get_db() as conn:
        paper = conn.execute("SELECT pdf_filename FROM papers WHERE id = ?", (paper_id,)).fetchone()

    if not paper or not paper['pdf_filename']:
        return jsonify({'status': 'error', 'message': f'Paper ID {paper_id} not found in DB'}), 404
    
    filename = paper['pdf_filename']
    filepath = os.path.join(config.ANNOTATED_PDF_STORAGE_DIR, filename)

    try:
        file.save(filepath)
        with db.get_db() as conn:
            conn.execute("UPDATE papers SET pdf_state = ? WHERE id = ?", ('annotated', paper_id))
            
        # Fetch refreshed data for the frontend to update the UI instantly
        updated_data = db.fetch_updated_paper_data(paper_id)
        if updated_data['status'] == 'success':
            updated_data['pdf_filename'] = filename
            updated_data['pdf_state'] = 'annotated'
            return jsonify(updated_data)
        else:
            return jsonify({'status': 'error', 'message': 'DB updated but failed to fetch refreshed data'}), 500
            
    except Exception as e:
        print(f"Error saving annotated PDF for paper {paper_id}: {e}")
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except: pass
        return jsonify({'status': 'error', 'message': 'Failed to save file on server.'}), 500
    
@files_bp.route('/static_export', methods=['GET'])
def static_export():
    """Generate and serve a downloadable HTML snapshot based on current filters."""
    # --- Get filter parameters from the request (URL query params) ---
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')
    # hidden params (usable, but not implemented in the Web client GUI):
    lite_param = request.args.get('lite', default='0')
    download_param = request.args.get('download', default='1')

    # --- Determine filter values ---
    hide_offtopic, year_from_value, year_to_value, min_page_count_value= export_logic.get_default_filter_values(
        hide_offtopic_param, year_from_param, year_to_param, min_page_count_param
    )

    # --- Fetch papers based on these filters ---
    papers = db.fetch_papers(
        hide_offtopic=hide_offtopic,
        year_from=year_from_value,
        year_to=year_to_value,
        min_page_count=min_page_count_value,
    )

    is_lite_export = lite_param.lower() in ['1', 'true', 'yes']

    # --- Generate the content using the core function ---
    full_html_content = export_logic.generate_html_export_content(
        papers, hide_offtopic, year_from_value, year_to_value, min_page_count_value, is_lite_export
    )

    # --- Create a filename based on filters ---
    extra_suffix = "lite" if is_lite_export else ""
    filename = export_logic.generate_filename("ResearchParsa", year_from_value, year_to_value, min_page_count_value, hide_offtopic, extra_suffix) + ".html"

    # --- Prepare Response Headers ---
    response_headers = {"Content-Type": "text/html"}
    if download_param == '0':       # If download=0, set Content-Disposition to 'inline' to display in browser
        response_headers["Content-Disposition"] = f"inline; filename={filename}"
        print(f"Serving static export inline: {filename}") # Optional: Log action
    else:                           # Default behavior: prompt for download
        response_headers["Content-Disposition"] = f"attachment; filename={filename}"
        print(f"Sending static export as attachment: {filename}") # Optional: Log action

    return Response(
        full_html_content,
        mimetype="text/html",
        headers=response_headers
    )

@files_bp.route('/xlsx_export', methods=['GET'])
def export_excel():
    """Generate and serve a downloadable Excel (.xlsx) file based on current filters."""
    # --- Get filter parameters from the request (URL query params) ---
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')

    # --- Determine filter values ---
    hide_offtopic, year_from_value, year_to_value, min_page_count_value = export_logic.get_default_filter_values(
        hide_offtopic_param, year_from_param, year_to_param, min_page_count_param
    )

    # --- Fetch papers based on these filters ---
    papers = db.fetch_papers(
        hide_offtopic=hide_offtopic,
        year_from=year_from_value,
        year_to=year_to_value,
        min_page_count=min_page_count_value,
    )

    # --- Generate the content using the core function ---
    excel_bytes = export_logic.generate_xlsx_export_content(papers)

    # --- Create a filename based on filters ---
    filename = export_logic.generate_filename("ResearchParsa", year_from_value, year_to_value, min_page_count_value, hide_offtopic) + ".xlsx"

    # --- Return as a downloadable attachment ---
    return Response(
        excel_bytes, # Get the bytes from the core function
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
