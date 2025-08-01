# import_bibtex.py
import sqlite3
import json
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import homogenize_latex_encoding
import argparse
import re # Import regex for brace removal

# Define default JSON structures for features and technique
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
        changed_by TEXT                    -- Identifier of the changer (e.g., 'Web app')
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

def import_bibtex(bib_file, db_path):
    """Import BibTeX file into SQLite database"""
    # Configure BibTeX parser
    parser = BibTexParser(common_strings=True)
    parser.customization = homogenize_latex_encoding
    parser.ignore_nonstandard_types = False

    # Parse BibTeX file
    with open(bib_file, 'r', encoding='utf-8') as f:
        bib_db = bibtexparser.load(f, parser=parser)

    # Create database (this will overwrite if db_path exists, as we want a fresh start)
    create_database(db_path) # Ensure table exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for entry in bib_db.entries:
        # Prepare data for insertion
        title_raw = entry.get('title', '')
        cleaned_title = clean_latex_braces(title_raw)

        data = {
            'id': entry.get('ID', ''),
            'type': entry.get('ENTRYTYPE', ''),
            'title': cleaned_title,
            'authors': parse_authors(entry.get('author', '')),
            'year': int(entry.get('year', '0')) if entry.get('year', '').isdigit() else None,
            'month': entry.get('month', ''),
            'journal': entry.get('journal', '') or entry.get('booktitle', ''), # Prioritize journal
            'volume': entry.get('volume', ''),
            'pages': entry.get('pages', ''),
            'doi': entry.get('doi', ''),
            'issn': entry.get('issn', ''),
            'abstract': entry.get('abstract', ''),
            'keywords': parse_keywords(entry.get('keywords', '')),
            # Custom fields (initialized to unknown state)
            'research_area': None,
            'is_survey': None,
            'is_offtopic': None,
            'is_through_hole': None,
            'is_smt': None,
            'is_x_ray': None,
            'features': json.dumps(DEFAULT_FEATURES),
            'technique': json.dumps(DEFAULT_TECHNIQUE),
            # Audit fields (initially NULL)
            'changed': None,
            'changed_by': None
        }
        # Insert into database
        try:
            cursor.execute('''
            INSERT INTO papers (
                id, type, title, authors, year, month, journal, 
                volume, pages, doi, issn, abstract, keywords,
                research_area, is_survey, is_offtopic, is_through_hole, 
                is_smt, is_x_ray, features, technique, changed, changed_by
            ) VALUES (
                :id, :type, :title, :authors, :year, :month, :journal, 
                :volume, :pages, :doi, :issn, :abstract, :keywords,
                :research_area, :is_survey, :is_offtopic, :is_through_hole, 
                :is_smt, :is_x_ray, :features, :technique, :changed, :changed_by
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
