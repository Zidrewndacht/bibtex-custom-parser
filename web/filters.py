# web/filters.py
from markupsafe import Markup
import re

# --- Jinja2-like filters ---
def render_status(value):
    """Render status value as emoji/symbol"""
    if value == 1 or value == "true" or value is True:
        return '✔️' # Checkmark for True
    elif value == 0  or value == "false" or value is False:
        return '❌' # Cross for False
    else: # None or unknown
        return '❔' # Question mark for Unknown/Null

def render_status_filter(value):
    return render_status(value)


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

def render_verified_by_filter(value):
    # Use Markup to tell Jinja2 that the output is safe HTML
    return Markup(render_verified_by(value)) 


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
    
def render_changed_by_filter(value):
    # Use Markup to tell Jinja2 that the output is safe HTML
    return Markup(render_changed_by(value))



# --- BibTeX Generation Function ---
def generate_bibtex_string(paper):
    """
    Generates a raw BibTeX entry string from a paper dictionary.
    Excludes the abstract field.
    Handles different entry types and common fields.
    """
    if not paper or not paper.get('id'):
        return "Error: Paper ID missing."

    entry_type = paper.get('type', 'misc').lower() # Default to 'misc' if type is missing
    bibtex_key = paper['id'] # Use the database ID as the BibTeX key

    # Map common database fields to BibTeX fields
    field_mapping = {
        'title': paper.get('title'),
        'author': paper.get('authors'), # Assuming authors are stored as a semicolon-separated string, might need reformatting for BibTeX
        'year': paper.get('year'),
        'journal': paper.get('journal'),
        'booktitle': paper.get('journal'), # For inproceedings, conference papers - using journal field which contains conference name
        'volume': paper.get('volume'),
        'number': paper.get('number'), # Add number if it exists in DB (mapped from issue)
        'pages': paper.get('pages'), # Already normalized, might need further cleaning for BibTeX range format
        'doi': paper.get('doi'),
        'issn': paper.get('issn'),
        'month': paper.get('month'),
        'keywords': paper.get('keywords'),
        'abstract': paper.get('abstract'),  # Note: this will be excluded later
        # Add other fields as needed
        'publisher': paper.get('publisher'),  # Might be needed for books
        'institution': paper.get('institution'),  # For tech reports
        'school': paper.get('school'),  # For theses
        'chapter': paper.get('chapter'),  # For inbook entries
        'note': paper.get('note'),  # General notes
        'howpublished': paper.get('howpublished'),  # For misc entries
    }

    # Handle author formatting (semicolon-separated to ' and ' separated, potentially)
    # This is a simple conversion, might need refinement based on your exact storage format
    if field_mapping['author']:
        # Split by semicolon and join with ' and '
        authors_list = [author.strip() for author in field_mapping['author'].split(';')]
        field_mapping['author'] = ' and '.join(authors_list)

    # Handle keywords formatting (semicolon-separated to comma-separated)
    if field_mapping['keywords']:
        # Split by semicolon and join with comma for BibTeX keywords
        keywords_list = [keyword.strip() for keyword in field_mapping['keywords'].split(';')]
        field_mapping['keywords'] = ', '.join(keywords_list)

    # Handle pages formatting for BibTeX range (e.g., "123 - 125" -> "123--125")
    if field_mapping['pages']:
        # Simple replacement, might need more robust parsing if formats vary significantly
        # Remove spaces around hyphens/dashes and replace with double dash
        import re
        pages_str = field_mapping['pages']
        # Replace spaces around various dash-like characters with double hyphen
        field_mapping['pages'] = re.sub(r'\s*[-–—]\s*', '--', pages_str)

    # Determine fields relevant to the entry type and build the entry
    # This is a basic example, you might want to expand this mapping
    type_required_fields = {
        'article': ['title', 'author', 'journal', 'year'],
        'inproceedings': ['title', 'author', 'booktitle', 'year'], # Note: booktitle, not journal
        'book': ['title', 'author', 'publisher', 'year'],
        'inbook': ['title', 'author', 'chapter', 'publisher', 'year'],
        'incollection': ['title', 'author', 'booktitle', 'publisher', 'year'],
        'techreport': ['title', 'author', 'institution', 'year'],
        'phdthesis': ['title', 'author', 'school', 'year'],
        'mastersthesis': ['title', 'author', 'school', 'year'],
        'manual': ['title'],
        'misc': ['title','author', 'year'], # Default, might add author, howpublished, note
        'conference': ['title', 'author', 'booktitle', 'year'], # Treat like inproceedings
    }

    # Update the field_mapping to use the actual conference name for booktitle when type is inproceedings or conference
    if entry_type in ['inproceedings', 'conference'] and paper.get('journal'):
        field_mapping['booktitle'] = paper.get('journal')

    relevant_fields = type_required_fields.get(entry_type, ['title', 'author', 'year']) # Default fields

    # Start building the BibTeX string
    lines = [f"@{entry_type}{{{bibtex_key},"]
    for field in relevant_fields:
        value = field_mapping.get(field)
        if value is not None and str(value).strip() != "": # Only add non-empty fields
            # Basic escaping for common BibTeX characters if needed (e.g., #, {, }, $)
            # bibtex_value = str(value).replace('{', '\\{').replace('}', '\\}') # Example
            bibtex_value = str(value)
            # Ensure proper quoting, using double quotes as standard
            lines.append(f"  {field} = {{{bibtex_value}}},") # Use braces for safety

    # Add other potentially relevant fields that aren't strictly "required"
    # Include all available fields from the database schema
    other_fields = [
        'volume', 'number', 'pages', 'doi', 'issn', 'month', 'keywords',
        'publisher', 'institution', 'school', 'chapter', 'note', 'howpublished'
    ]
    for field in other_fields:
        value = field_mapping.get(field)
        if value is not None and str(value).strip() != "" and field not in relevant_fields:
             bibtex_value = str(value)
             lines.append(f"  {field} = {{{bibtex_value}}},") # Use braces

    # Remove trailing comma from the last field
    if lines and lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]

    lines.append("}") # Close the entry
    return "\n".join(lines)


def bibtex_filter(paper):
    """Jinja2 filter to generate a BibTeX string for a paper dictionary."""
    return generate_bibtex_string(paper)

def get_json_path_filter(d, path):
    """Traverses a nested dictionary using a dot-notation path string."""
    if not d or not path: return None
    keys = path.split('.')
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d