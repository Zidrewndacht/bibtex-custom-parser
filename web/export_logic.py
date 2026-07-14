# web/export_logic.py
import os
import base64
import gzip
import json
import rjsmin
from flask import render_template
from markupsafe import Markup
from shared import config

def get_default_filter_values(hide_offtopic_param, year_from_param, year_to_param, min_page_count_param):
    """Extracts and validates filter parameters, returning default values if invalid/missing."""
    hide_offtopic = True
    if hide_offtopic_param is not None:
        hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']
    try: year_from_value = int(year_from_param) if year_from_param is not None else config.DEFAULT_YEAR_FROM
    except ValueError: year_from_value = config.DEFAULT_YEAR_FROM
    try: year_to_value = int(year_to_param) if year_to_param is not None else config.DEFAULT_YEAR_TO
    except ValueError: year_to_value = config.DEFAULT_YEAR_TO
    try: min_page_count_value = int(min_page_count_param) if min_page_count_param is not None else config.DEFAULT_MIN_PAGE_COUNT
    except ValueError: min_page_count_value = config.DEFAULT_MIN_PAGE_COUNT
    return hide_offtopic, year_from_value, year_to_value, min_page_count_value


def font_to_data_uri(font_path):
    """Converts a font file to a Base64 data URI string."""
    with open(font_path, 'rb') as font_file:
        font_data = font_file.read()
        base64_data = base64.b64encode(font_data).decode('ascii')
        
    # Determine format from file extension
    if font_path.lower().endswith('.woff2'):
        mime_type = 'font/woff2'
        format_str = 'woff2'
    elif font_path.lower().endswith('.woff'):
        mime_type = 'font/woff'
        format_str = 'woff'
    elif font_path.lower().endswith('.ttf'):
        mime_type = 'font/ttf'
        format_str = 'truetype'
    else:
        mime_type = 'application/octet-stream'
        format_str = 'truetype'  # fallback
        
    return f"data:{mime_type};base64,{base64_data}", format_str

def embed_fonts_in_css(static_dir):
    """Convert font files to Base64 data URIs and return CSS with embedded fonts."""
    fonts_dir = os.path.join(static_dir, 'fonts')
    
    # Define font files to embed
    font_files = [
        ('Twemoji.mozilla.ttf', 'Twemoji Mozilla', 400, 'normal'),
        ('inter-tight-v7-latin_latin-ext-300.woff2', 'Inter Tight', 300, 'normal'),
        ('inter-tight-v7-latin_latin-ext-regular.woff2', 'Inter Tight', 400, 'normal'),
        ('inter-tight-v7-latin_latin-ext-600.woff2', 'Inter Tight', 600, 'normal'),
    ]
    
    css_content = "/* Embedded Fonts */\n"
    
    # Group fonts by family to create proper @font-face rules
    font_faces = {}
    
    for filename, font_family, font_weight, font_style in font_files:
        font_path = os.path.join(fonts_dir, filename)
        try:
            data_uri, format_str = font_to_data_uri(font_path)
            
            key = (font_family, font_weight, font_style)
            if key not in font_faces:
                font_faces[key] = []
            
            font_faces[key].append((data_uri, format_str))
        except FileNotFoundError:
            print(f"Warning: Font file not found: {font_path}")
            continue
    
    # Generate @font-face CSS rules
    for (font_family, font_weight, font_style), sources in font_faces.items():
        css_content += f"""
/* {font_family} - {font_weight} */
@font-face {{
    font-display: swap;
    font-family: '{font_family}';
    font-style: {font_style};
    font-weight: {font_weight};
    src: """
        
        # Add all sources for this font face
        src_parts = []
        for data_uri, format_str in sources:
            src_parts.append(f"url('{data_uri}') format('{format_str}')")
        
        css_content += ",\n        ".join(src_parts) + ";\n}\n"
    
    return css_content

def prepare_history_log_data(paper_dict, set_num=None):
    """
    Prepares llm_log data for history row rendering.
    Marks malformed entries as invalid instead of scrapping them.
    """
    # Determine which log column to use
    if set_num and set_num in [1, 2, 3]:
        raw_log = paper_dict.get(f'set_{set_num}_llm_log', '[]')
        # has_certainty = False
    else:
        raw_log = paper_dict.get('llm_log', '[]')
        # has_certainty = True
    
    try:
        log_entries = json.loads(raw_log) if raw_log else []
    except (json.JSONDecodeError, TypeError):
        log_entries = []
    
    # Required fields for classification entries
    REQUIRED_CLASSIFICATION_FIELDS = [
        'is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
        'relevance', 'features', 'technique'
    ]
    
    # parse output JSON and validate
    for entry in log_entries:
        try:
            output_raw = entry.get('output', '{}')
            if isinstance(output_raw, str) and output_raw:
                entry['output'] = json.loads(output_raw)
            elif isinstance(output_raw, dict):
                entry['output'] = output_raw
            else:
                entry['output'] = {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            entry['output'] = {}
        
        # Mark entry as valid by default, then check for malformed data
        entry['valid'] = bool(entry.get('valid', False))
        
        # Only validate classification-type entries (not verifier entries)
        if entry.get('type') in ['classifier', 'consensus', 'averaged_llm', 'user']:
            output = entry.get('output', {})
            if not isinstance(output, dict):
                entry['valid'] = False
                entry['invalid_reason'] = 'Output is not a dictionary'
            else:
                # Check for required classification fields
                missing_fields = [f for f in REQUIRED_CLASSIFICATION_FIELDS if f not in output]
                if missing_fields:
                    entry['valid'] = False
                    entry['invalid_reason'] = f'Missing required fields: {", ".join(missing_fields)}'
                else:
                    entry['valid'] = True  # Entry has all required fields
    
    # PASS 1: Ascending order - Mark changed cells (valid entries only)
    table_entries = [e for e in log_entries
                    if e.get('type') in ['classifier', 'consensus', 'averaged_llm', 'user']
                    and e.get('valid', False)]  # ← Only use valid entries for change tracking
    
    for i in range(len(table_entries)):
        current = table_entries[i]
        older = table_entries[i - 1] if i > 0 else None
        current['changed_fields'] = set()
        if older:
            older_output = older.get('output', {}) or {}
            current_output = current.get('output', {}) or {}
            if not isinstance(older_output, dict):
                older_output = {}
            if not isinstance(current_output, dict):
                current_output = {}
            for field in ['is_offtopic', 'relevance', 'is_survey',
                         'is_through_hole', 'is_smt', 'is_x_ray']:
                if current_output.get(field) != older_output.get(field):
                    current['changed_fields'].add(field)
            current_features = current_output.get('features') or {}
            older_features = older_output.get('features') or {}
            if isinstance(current_features, dict) and isinstance(older_features, dict):
                all_keys = set(current_features.keys()) | set(older_features.keys())
                for key in all_keys:
                    if current_features.get(key) != older_features.get(key):
                        current['changed_fields'].add(f'features_{key}')
            current_technique = current_output.get('technique') or {}
            older_technique = older_output.get('technique') or {}
            if isinstance(current_technique, dict) and isinstance(older_technique, dict):
                all_keys = set(current_technique.keys()) | set(older_technique.keys())
                for key in all_keys:
                    if current_technique.get(key) != older_technique.get(key):
                        current['changed_fields'].add(f'technique_{key}')
    
    changed_fields_map = {
        entry['timestamp']: entry.get('changed_fields', set())
        for entry in table_entries
    }
    
    # PASS 2: Reverse for UI, attach verifiers
    log_entries.reverse()
    processed_entries = []
    cached_verifier = None
    for entry in log_entries:
        entry_type = entry.get('type', '')
        entry['changed_fields'] = changed_fields_map.get(entry['timestamp'], set())
        if entry_type == 'verifier':
            verifier_output = entry.get('output', {}) or {}
            if not isinstance(verifier_output, dict):
                verifier_output = {}
            cached_verifier = {
                'verified': verifier_output.get('verified'),
                'estimated_score': verifier_output.get('estimated_score'),
                'verifier_trace': entry.get('trace', ''),
                'verifier_model': entry.get('model', ''),
                'verifier_timestamp': entry['timestamp']
            }
            entry['verification_data'] = None
        elif entry_type in ['classifier', 'consensus']:
            entry['verification_data'] = cached_verifier
            cached_verifier = None
        else:
            entry['verification_data'] = None
        processed_entries.append(entry)
    
    return processed_entries

# Core Export Generation Functions
def generate_html_export_content(papers, hide_offtopic, year_from_value, year_to_value, min_page_count_value, is_lite_export=False):
    """Generates the full HTML content string for the static export."""
     
    # Prepare history log data for the FILTERED papers only (already passed in)
    for paper in papers:
        paper['llm_log_entries'] = prepare_history_log_data(paper, set_num=None)
        paper['set_1_llm_log_entries'] = prepare_history_log_data(paper, set_num=1)
        paper['set_2_llm_log_entries'] = prepare_history_log_data(paper, set_num=2)
        paper['set_3_llm_log_entries'] = prepare_history_log_data(paper, set_num=3)

    
    style_css_content = ""
    chart_js_content = ""
    chart_js_datalabels_content = ""
    d3_js_content = ""
    d3_cloud_js_content = ""
    ghpages_js_content = ""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(script_dir, 'static')
    
    # Load and embed fonts as Base64 data URIs
    fonts_css_content = embed_fonts_in_css(static_dir)
    
    with open(os.path.join(static_dir, 'libs/chart.min.js'), 'r', encoding='utf-8') as f:
        chart_js_content = f.read()
    with open(os.path.join(static_dir, 'libs/chartjs-plugin-datalabels.min.js'), 'r', encoding='utf-8') as f:
        chart_js_datalabels_content = f.read()
    with open(os.path.join(static_dir, 'libs/d3.min.js'), 'r', encoding='utf-8') as f:
        d3_js_content = f.read()
    with open(os.path.join(static_dir, 'libs/d3-cloud.min.js'), 'r', encoding='utf-8') as f:
        d3_cloud_js_content = f.read()

    with open(os.path.join(static_dir, 'style.css'), 'r', encoding='utf-8') as f:
        style_css_content = f.read()
    with open(os.path.join(static_dir, 'ghpages.js'), 'r', encoding='utf-8') as f:
        ghpages_js_content = f.read()
    with open(os.path.join(static_dir, 'stats.js'), 'r', encoding='utf-8') as f:
        stats_js_content = f.read()
    with open(os.path.join(static_dir, 'filtering.js'), 'r', encoding='utf-8') as f:
        filtering_js_content = f.read()

    # Combine fonts CSS with main CSS
    style_css_content = fonts_css_content + "\n" + style_css_content
    
    # style_css_content = rcssmin.cssmin(style_css_content)
    
    chart_js_content = rjsmin.jsmin(chart_js_content)
    chart_js_datalabels_content = rjsmin.jsmin(chart_js_datalabels_content)
    d3_js_content = rjsmin.jsmin(d3_js_content)
    d3_cloud_js_content = rjsmin.jsmin(d3_cloud_js_content)

    stats_js_content = rjsmin.jsmin(stats_js_content)
    filtering_js_content = rjsmin.jsmin(filtering_js_content)
    ghpages_js_content = rjsmin.jsmin(ghpages_js_content)

    # --- Render the static export template ---
    papers_table_static_export = render_template(
        'papers_table_static_export.html',
        papers=papers,
        type_emojis=config.TYPE_EMOJIS,
        pdf_emojis=config.PDF_EMOJIS,
        default_type_emoji=config.DEFAULT_TYPE_EMOJI,
        hide_offtopic=hide_offtopic,
        year_from_value=str(year_from_value),
        year_to_value=str(year_to_value),
        min_page_count_value=str(min_page_count_value),
        is_lite_export=is_lite_export,
    )
    full_html_content = render_template(
        'index_static_export.html',
        papers_table_static_export=papers_table_static_export,
        hide_offtopic=hide_offtopic,
        year_from_value=year_from_value,
        year_to_value=year_to_value,
        min_page_count_value=min_page_count_value,

        style_css_content=Markup(style_css_content),
        
        chart_js_content=Markup(chart_js_content),
        chart_js_datalabels_content=Markup(chart_js_datalabels_content),
        d3_js_content=Markup(d3_js_content),
        d3_cloud_js_content=Markup(d3_cloud_js_content),

        filtering_js_content=Markup(filtering_js_content),
        stats_js_content=Markup(stats_js_content),
        ghpages_js_content=Markup(ghpages_js_content)
    )

    # --- Compress the full HTML content ---
    html_bytes = full_html_content.encode('utf-8')  # 1. Encode the HTML string to bytes (UTF-8)
    compressed_bytes = gzip.compress(html_bytes)    # 2. Compress the bytes
    compressed_base64 = base64.b64encode(compressed_bytes).decode('ascii')  # 3. Encode the compressed bytes to Base64 for embedding in JS

    pako_js_content = ""
    with open(os.path.join(static_dir, 'libs/pako.min.js'), 'r', encoding='utf-8') as f:
        pako_js_content = f.read()

    # --- Render the LOADER template, passing the compressed data ---
    loader_html_content = render_template(
        'loader.html',
        compressed_html_data=compressed_base64,
        pako_js_content=Markup(pako_js_content)
    )
    return loader_html_content

def generate_xlsx_export_content(papers): #outdated, must be updated to be useful for v1.2:
    # """Generates the Excel file content as bytes."""
    # from openpyxl import Workbook
    # from openpyxl.styles import Font, PatternFill 
    # from openpyxl.worksheet.table import Table, TableStyleInfo
    # output = io.BytesIO()
    # wb = Workbook()
    # ws = wb.active
    # ws.title = "PCB Inspection Papers"

    # # --- Define Headers (Updated Order - Corrected Boolean Features) ---
    # headers = [
    #     "Type", "Title", "Year", "Journal/Conf name", "Pages count",
    #     # Classification Summary
    #     "Off-topic", "Relevance", "Survey", "THT", "SMT", "X-Ray",
    #     # Features Summary (Updated Order - Corrected Boolean Features)
    #     "Tracks", "Holes / Vias", "Bare PCB Other", # Boolean (e.g., bare_pcb_other)
    #     "Solder Insufficient", "Solder Excess", "Solder Void", "Solder Crack", "Solder Other", # Boolean (e.g., solder_other)
    #     "Missing Comp", "Wrong Comp", "Orientation", "Comp Other", # Boolean (e.g., component_other)
    #     "Cosmetic", "Other State", # Boolean for state (based on 'other' text content)
    #     "Other Defects Text", # Text for content (the 'other' field)
    #     # Techniques Summary (Updated Order)
    #     "Classic CV", "ML", "CNN Classifier", "CNN Detector",
    #     "R-CNN Detector", "Transformers", "Other DL", "Hybrid", "Datasets", "Model name",
    #     # Metadata
    #     "Last Changed", "Changed By", "Verified", "Accr. Score", "Verified By",
    #     "User Comment State", "User Comments" # Boolean for state, Text for content
    # ]

    # # --- Write Headers ---
    # for col_num, header in enumerate(headers, 1):
    #     cell = ws.cell(row=1, column=col_num, value=header)
    #     cell.font = Font(bold=True)

    # # --- Write Data Rows ---
    # for row_num, paper in enumerate(papers, 2): # Start from row 2
    #     # --- Helper function for consistent Excel value conversion ---
    #     def format_excel_value(val):
    #         """
    #         Converts Python/DB values to Excel-friendly values:
    #         - True/1   -> TRUE (Excel boolean)
    #         - False/0  -> FALSE (Excel boolean)
    #         - None/''/etc. -> "" (Empty string for blank Excel cell)
    #         - Other    -> str(val) (Text)
    #         """
    #         if val is True or (isinstance(val, (int, float)) and val == 1):
    #             return True # Excel TRUE
    #         elif val is False or (isinstance(val, (int, float)) and val == 0):
    #             return False # Excel FALSE
    #         elif val is None or val == "":
    #              return "" # Explicitly empty cell for NULL/empty
    #         else:
    #             # Handle potential string representations of booleans from inconsistent DB
    #             if isinstance(val, str):
    #                 lower_val = val.lower()
    #                 if lower_val in ('true', '1'):
    #                     return True
    #                 elif lower_val in ('false', '0'):
    #                     return False
    #             # Default: Convert to string for text fields
    #             return str(val)

    #     # Extract and format data
    #     features = paper.get('features', {})
    #     technique = paper.get('technique', {})

    #     # --- Format the 'Last Changed' date ---
    #     changed_timestamp_str = paper.get('changed', '')
    #     formatted_changed_date = ""
    #     if changed_timestamp_str:
    #         try:
    #             # Parse the ISO format timestamp
    #             dt = datetime.fromisoformat(changed_timestamp_str.replace('Z', '+00:00'))
    #             # Format as 'YYYY-MM-DD HH:MM:SS' for Excel compatibility
    #             formatted_changed_date = dt.strftime("%Y-%m-%d %H:%M:%S")
    #         except ValueError:
    #             # If parsing fails, keep the original string or leave blank
    #             formatted_changed_date = changed_timestamp_str # Or ""

    #     row_data = [
    #         paper.get('type', ''),                    # Type (text)
    #         paper.get('title', ''),                   # Title (text)
    #         paper.get('year'),                        # Year (integer)
    #         paper.get('journal', ''),                 # Journal/Conf name (text)
    #         paper.get('page_count'),                  # Pages count (integer)
    #         # --- Classification Summary ---
    #         format_excel_value(paper.get('is_offtopic')), # Off-topic (boolean/null)
    #         paper.get('relevance'),                   # Relevance (integer)
    #         format_excel_value(paper.get('is_survey')), # Survey (boolean/null)
    #         format_excel_value(paper.get('is_through_hole')), # THT (boolean/null)
    #         format_excel_value(paper.get('is_smt')),    # SMT (boolean/null)
    #         format_excel_value(paper.get('is_x_ray')),  # X-Ray (boolean/null)
    #         # --- Features Summary (Updated Order - Corrected Boolean Features) ---
    #         format_excel_value(features.get('tracks')), # Tracks (boolean/null)
    #         format_excel_value(features.get('holes')),  # Holes / Vias (boolean/null)
    #         format_excel_value(features.get('bare_pcb_other')), # Bare PCB Other (boolean/null) - ADDED
    #         format_excel_value(features.get('solder_insufficient')), # Solder Insufficient (boolean/null)
    #         format_excel_value(features.get('solder_excess')), # Solder Excess (boolean/null)
    #         format_excel_value(features.get('solder_void')), # Solder Void (boolean/null)
    #         format_excel_value(features.get('solder_crack')), # Solder Crack (boolean/null)
    #         format_excel_value(features.get('solder_other')), # Solder Other (boolean/null) - ADDED
    #         format_excel_value(features.get('missing_component')), # Missing Comp (boolean/null)
    #         format_excel_value(features.get('wrong_component')), # Wrong Comp (boolean/null)
    #         format_excel_value(features.get('orientation')), # Orientation (boolean/null)
    #         format_excel_value(features.get('component_other')), # Comp Other (boolean/null) - ADDED
    #         format_excel_value(features.get('cosmetic')), # Cosmetic (boolean/null)
    #         # Other State (boolean based on 'other' text content) - CORRECTED COMMENT
    #         format_excel_value(features.get('other') is not None and str(features.get('other', '')).strip() != ""),
    #         features.get('other', ''),               # Other Defects Text (text) - This one shows the text
    #         # --- Techniques Summary (Updated Order) ---
    #         format_excel_value(technique.get('classic_cv_based')), # Classic CV (boolean/null)
    #         format_excel_value(technique.get('ml_traditional')), # ML (boolean/null)
    #         format_excel_value(technique.get('dl_cnn_classifier')), # CNN Classifier (boolean/null)
    #         format_excel_value(technique.get('dl_cnn_detector')), # CNN Detector (boolean/null)
    #         format_excel_value(technique.get('dl_rcnn_detector')), # R-CNN Detector (boolean/null)
    #         format_excel_value(technique.get('dl_transformer')), # Transformers (boolean/null)
    #         format_excel_value(technique.get('dl_other')), # Other DL (boolean/null)
    #         format_excel_value(technique.get('hybrid')), # Hybrid (boolean/null)
    #         format_excel_value(technique.get('available_dataset')), # Datasets (boolean/null)
    #         technique.get('model', ''),              # Model name (text)
    #         # --- Metadata ---
    #         formatted_changed_date,                 # Last Changed (formatted date string)
    #         paper.get('changed_by', ''),            # Changed By (text)
    #         format_excel_value(paper.get('verified')), # Verified (boolean/null)
    #         paper.get('estimated_score'),           # Accr. Score (integer)
    #         paper.get('verified_by', ''),           # Verified By (text)
    #         # User comments state (boolean based on 'user_trace' text content) - CORRECTED COMMENT
    #         format_excel_value(paper.get('user_trace') is not None and str(paper.get('user_trace', '')).strip() != ""),
    #         paper.get('user_trace', '')             # User comments contents (text) - This one shows the text
    #     ]

    #     # Write the row data to Excel
    #     for col_num, cell_value in enumerate(row_data, 1):
    #         ws.cell(row=row_num, column=col_num, value=cell_value)

    # # Optional: Auto-adjust column widths (basic attempt)
    # for column in ws.columns:
    #     max_length = 0
    #     column_letter = column[0].column_letter # Get the column name
    #     for cell in column:
    #         try:
    #             if len(str(cell.value)) > max_length:
    #                 max_length = len(str(cell.value))
    #         except:
    #             pass
    #     adjusted_width = (max_length + 2)
    #     # Cap the width to prevent extremely wide columns
    #     ws.column_dimensions[column_letter].width = min(adjusted_width, 50)

    # # Optional: Format the data as a table (requires openpyxl >= 2.5)
    # if len(papers) > 0:
    #     # Adjust the column reference to 'AQ' (assuming 37 columns now: A through AQ)
    #     # Headers are row 1, data starts row 2, so last row is len(papers) + 1
    #     tab = Table(displayName="PCBPapersTable", ref=f"A1:AQ{len(papers) + 1}")
    #     style = TableStyleInfo(name="TableStyleMedium2", showFirstColumn=False,
    #                             showLastColumn=False, showRowStripes=True, showColumnStripes=False)
    #     tab.tableStyleInfo = style
    #     ws.add_table(tab)

    # # --- NEW: Apply Conditional Formatting for Boolean Cells ---
    # # Define fills for TRUE and FALSE
    # true_fill = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid") # Light Green
    # false_fill = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid") # Light Red
    # # Updated boolean column indices based on corrected new order (1-based indexing)
    # boolean_columns = [
    #     # Classification Summary
    #     6, 8, 9, 10, 11,
    #     # Features Summary (Boolean Features)
    #     12, 13, 14, # Tracks, Holes, Bare PCB Other
    #     15, 16, 17, 18, 19, # Solder Insufficient, Excess, Void, Crack, Solder Other
    #     20, 21, 22, 23, # Missing Comp, Wrong Comp, Orientation, Comp Other
    #     24, 25, 27, # Cosmetic, Other State, User Comment State
    #     # Techniques Summary
    #     28, 29, 30, 31, 32, 33, 34, 35, 36,
    #     # Metadata
    #     39 # Verified (column 39)
    # ]

    # # Iterate through rows and specified boolean columns to apply formatting
    # for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
    #     for col_idx in boolean_columns:
    #         # Adjust for 0-based indexing in the row list
    #         cell = row[col_idx - 1] # col_idx is 1-based, list index is 0-based
    #         if cell.value is True:
    #             cell.fill = true_fill
    #         elif cell.value is False:
    #             cell.fill = false_fill
    #         # If cell.value is None or "", it remains unformatted (blank cell)

    # # --- Save Workbook to BytesIO object ---
    # wb.save(output)
    # output.seek(0)
    # return output.getvalue()
    return

def generate_filename(base_name, year_from, year_to, min_page_count, hide_offtopic, extra_suffix=""):
    """Generates a filename based on filters."""
    filename_parts = [base_name]
    if year_from == year_to:
        filename_parts.append(str(year_from))
    else:
        filename_parts.append(f"{year_from}-{year_to}")
    if min_page_count > 0:
        filename_parts.append(f"min{min_page_count}pg")
    if hide_offtopic:
        filename_parts.append("noOfftopic")
    if extra_suffix:
        filename_parts.append(extra_suffix)
    return "_".join(filename_parts)
