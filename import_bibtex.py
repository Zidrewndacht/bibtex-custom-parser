# import_bibtex.py
import sqlite3
import json
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import homogenize_latex_encoding
import argparse
import re # Import regex for brace removal

import globals


def create_database(db_path):
    """Create SQLite database with the specified schema including new columns"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY,               -- BibTeX key
        type TEXT,                         -- Publication type (article, inproceedings, etc.)
        title TEXT,
        authors TEXT,                      -- Semicolon-separated list
        year INTEGER,
        month TEXT,
        journal TEXT,                      -- Journal or conference name
        volume TEXT,
        pages TEXT,
        page_count INTEGER,                
        doi TEXT,
        issn TEXT,
        abstract TEXT,
        keywords TEXT,                     -- Semicolon-separated list
        -- Custom classification fields
        research_area TEXT,                -- NULL = unknown
        is_survey INTEGER,                 -- 1=true, 0=false, NULL=unknown
        is_offtopic INTEGER,               -- 1=true, 0=false, NULL=unknown
        is_through_hole INTEGER,           -- 1=true, 0=false, NULL=unknown
        is_smt INTEGER,                    -- 1=true, 0=false, NULL=unknown
        is_x_ray INTEGER,                  -- 1=true, 0=false, NULL=unknown
        -- Features and techniques (stored as JSON)
        features TEXT,
        technique TEXT,
        -- Audit fields
        changed TEXT,                      -- ISO 8601 timestamp, NULL if never changed
        changed_by TEXT,                   -- Identifier of the changer (e.g., 'Web app')
        verified INTEGER,                  -- 1=true, 0=false, NULL=unknown
        estimated_score INTEGER,
        verified_by TEXT,                  -- Identifier of the verifier (e.g., 'user')
        reasoning_trace TEXT,              -- New column to store evaluator reasoning traces
        verifier_trace TEXT,                -- New column to store verifier reasoning traces
        user_trace TEXT                     -- User comments.
    )
    ''')
    # Enable WAL mode for better concurrency (optional)
    cursor.execute('PRAGMA journal_mode = WAL')
    conn.commit()
    conn.close() # Close connection after creation

def parse_authors(authors_str):
    """Parse authors string into semicolon-separated list"""
    if not authors_str:
        return ""
    # Handle potential LaTeX encoding issues if not fully homogenized
    return "; ".join(a.strip() for a in authors_str.split(' and '))

def parse_keywords(keywords_str):
    """Parse keywords into semicolon-separated list"""
    if not keywords_str:
        return ""
    return "; ".join(k.strip() for k in keywords_str.split(','))

def clean_latex_braces(text):
    """Remove unescaped curly braces from text, often left in titles by bibtexparser."""
    if not text:
        return text
    # Remove braces that are not part of a LaTeX command (simple heuristic)
    # This removes { and } that are not preceded by a backslash.
    # It might not be perfect for all edge cases but handles common ones.
    cleaned = re.sub(r'(?<!\\)\{', '', text)
    cleaned = re.sub(r'(?<!\\)\}', '', cleaned)
    return cleaned

def clean_latex_commands(text):
    """Remove common LaTeX commands and formatting from text."""
    if not text:
        return text
    
    # Remove unescaped braces
    text = re.sub(r'(?<!\\)\{', '', text)
    text = re.sub(r'(?<!\\)\}', '', text)
    
    # Replace LaTeX dash commands with regular dash
    text = re.sub(r'\\textendash', '-', text)
    text = re.sub(r'\\textemdash', '-', text)
    text = re.sub(r'\\endash', '-', text)
    text = re.sub(r'\\emdash', '-', text)
    
    # Remove other common LaTeX commands
    text = re.sub(r'\\textellipsis', '...', text)
    text = re.sub(r'\\ldots', '...', text)
    text = re.sub(r'\\dots', '...', text)
    
    # Remove any remaining LaTeX commands (pattern: backslash followed by letters)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def parse_pages(pages_str):
    """
    Normalize pages string to "start - end" format and return start, end, and count.
    Handles formats like '276--279', '276-279', '276', '276+', etc.
    Returns:
        tuple: (normalized_pages_str, page_count) or (None, None)
    """
    if not pages_str:
        return None, None

    # Clean LaTeX commands first
    pages_str = clean_latex_commands(pages_str).strip()

    # Match common formats including double hyphens
    # Covers: "123--456", "123-456", "123–456", "123—456"
    match = re.match(r'^(\d+)\s*[-–—]*\s*(\d+)?$', pages_str.replace('--', '-'))
    if match:
        start_page = int(match.group(1))
        end_page = int(match.group(2)) if match.group(2) else start_page
        normalized = f"{start_page} - {end_page}"
        count = end_page - start_page + 1
        return normalized, count
    else:
        # Handle "123+" format
        if re.match(r'^\d+\+$', pages_str):
            page = int(pages_str[:-1])
            return f"{page} - {page}", 1
        elif pages_str.isdigit():
            # Single page
            page = int(pages_str)
            return f"{page} - {page}", 1
        else:
            # Fallback: return as-is if parsing fails
            return pages_str, None
        
def import_bibtex(bib_file, db_path):
    """Import BibTeX file into SQLite database"""
    # Configure BibTeX parser
    parser = BibTexParser(common_strings=True)
    parser.customization = homogenize_latex_encoding
    parser.ignore_nonstandard_types = False

    # Parse BibTeX file
    with open(bib_file, 'r', encoding='utf-8') as f:
        bib_db = bibtexparser.load(f, parser=parser)

    # Create database
    create_database(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for entry in bib_db.entries:
        # Prepare data for insertion
        title_raw = entry.get('title', '')
        cleaned_title = clean_latex_commands(title_raw)  # Use improved cleaning

        # Handle pages and page_count
        raw_pages = entry.get('pages', '')
        normalized_pages, computed_page_count = parse_pages(raw_pages)

        # Try to get page_count from numpages field
        numpages_str = entry.get('numpages', '')
        page_count = None
        if numpages_str.isdigit():
            page_count = int(numpages_str)
        else:
            page_count = computed_page_count  # fallback to computed value

        data = {
            'id': entry.get('ID', ''),
            'type': entry.get('ENTRYTYPE', ''),
            'title': cleaned_title,
            'authors': parse_authors(entry.get('author', '')),
            'year': int(entry.get('year', '0')) if entry.get('year', '').isdigit() else None,
            'month': entry.get('month', ''),
            'journal': entry.get('journal', '') or entry.get('booktitle', ''),
            'volume': entry.get('volume', ''),
            'pages': normalized_pages,
            'page_count': page_count,
            'doi': entry.get('doi', ''),
            'issn': entry.get('issn', ''),
            'abstract': entry.get('abstract', ''),
            'keywords': parse_keywords(entry.get('keywords', '')),
            'research_area': None,
            'is_survey': None,
            'is_offtopic': None,
            'is_through_hole': None,
            'is_smt': None,
            'is_x_ray': None,
            'features': json.dumps(globals.DEFAULT_FEATURES),
            'technique': json.dumps(globals.DEFAULT_TECHNIQUE),
            'changed': None,
            'changed_by': None,
            'verified': None,
            'estimated_score': None,
            'verified_by': None,
            'reasoning_trace': None,  
            'verifier_trace': None,  
            'user_trace': None, 
        }
        # Check for duplicates: prioritize DOI, fallback to title + year
        doi = data['doi']
        title = data['title']
        year = data['year']

        duplicate_found = False
        
        if doi:
            cursor.execute("SELECT id FROM papers WHERE doi = ?", (doi,))
            if cursor.fetchone():
                print(f"Skipping duplicate entry with DOI '{doi}'")
                duplicate_found = True
        else:
            # Fallback: check for same title and year
            if title and year:
                cursor.execute("SELECT id FROM papers WHERE title = ? AND year = ?", (title, year))
                if cursor.fetchone():
                    print(f"Skipping duplicate entry with title '{title}' and year '{year}'")
                    duplicate_found = True

        if duplicate_found:
            continue  # Skip this entry

        # Insert into database
        try:
            cursor.execute('''
            INSERT INTO papers (
                id, type, title, authors, year, month, journal, 
                volume, pages, page_count, doi, issn, abstract, keywords,
                research_area, is_survey, is_offtopic, is_through_hole, 
                is_smt, is_x_ray, features, technique, changed, changed_by, verified, estimated_score, verified_by, reasoning_trace, verifier_trace, user_trace
            ) VALUES (
                :id, :type, :title, :authors, :year, :month, :journal, 
                :volume, :pages, :page_count, :doi, :issn, :abstract, :keywords,
                :research_area, :is_survey, :is_offtopic, :is_through_hole, 
                :is_smt, :is_x_ray, :features, :technique, :changed, :changed_by, :verified, :estimated_score, :verified_by, :reasoning_trace, :verifier_trace, :user_trace
            )
            ''', data)
        except sqlite3.IntegrityError as e:
            print(f"Warning: Skipping duplicate ID '{data['id']}' - {e}")
        except Exception as e:
            print(f"Error inserting entry '{data['id']}': {e}")

    conn.commit()
    print(f"Imported {len(bib_db.entries)} records into database '{db_path}'")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Convert BibTeX to SQLite database for PCB inspection papers')
    parser.add_argument('bib_file', help='Input BibTeX file path')
    parser.add_argument('db_file', help='Output SQLite database file path')
    args = parser.parse_args()
    import_bibtex(args.bib_file, args.db_file)
