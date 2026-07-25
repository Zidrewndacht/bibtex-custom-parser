# web/importer.py
# v1.2
# Importer for the v1.2 PCB inspection papers database.
# Assumes the v1.2 database schema already exists.
import sqlite3
import json
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import homogenize_latex_encoding
import re
import csv
from typing import List
import sys
import os
from shared import config

def parse_authors(authors_str):
    if not authors_str: return ""
    return "; ".join(a.strip() for a in authors_str.split(' and '))

def parse_keywords(keywords_str):
    if not keywords_str: return ""
    return "; ".join(k.strip() for k in keywords_str.split(','))

def clean_latex_braces(text):
    """Remove unescaped curly braces from text, often left in titles by bibtexparser."""
    if not text:
        return text
    # Remove braces that are not part of a LaTeX command (simple heuristic)
    # This removes { and } that are not preceded by a backslash.
    # It might not be perfect for all edge cases but handles common ones.
    cleaned = re.sub(r'(?<!\\)\{', '', text)
    return re.sub(r'(?<!\\)\}', '', cleaned)

def clean_latex_commands(text):
    """Remove common LaTeX commands and formatting from text."""
    if not text: return text

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
    return re.sub(r'\s+', ' ', text).strip()

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

def clean_bibtex_key(text: str) -> str:
    """Clean text to create a valid BibTeX key."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s-]+', '_', text)
    text = text.strip('_')
    if text and not text[0].isalpha():
        text = 'key_' + text
    text = text[:50]
    return text

def clean_authors(authors_str: str) -> str:
    """Convert authors from semicolon-separated format to BibTeX format."""
    if not authors_str:
        return ""
    authors = authors_str.split(';')
    cleaned_authors = []
    for author in authors:
        author = author.strip()
        if ',' in author:
            parts = author.split(',')
            if len(parts) >= 2:
                last_name = parts[0].strip()
                first_name = parts[1].strip()
                cleaned_authors.append(f"{last_name}, {first_name}")
            else:
                cleaned_authors.append(author)
        else:
            name_parts = author.split()
            if len(name_parts) >= 2:
                last_name = name_parts[-1]
                first_name = ' '.join(name_parts[:-1])
                cleaned_authors.append(f"{last_name}, {first_name}")
            else:
                cleaned_authors.append(author)
    return " and ".join(cleaned_authors)

def clean_title(title: str) -> str:
    """Clean title for BibTeX format."""
    if not title:
        return ""
    title = title.replace('{', '\\{').replace('}', '\\}')
    title = title.replace('#', '\\#')
    title = title.replace('$', '\\$')
    title = title.replace('%', '\\%')
    title = title.replace('&', '\\&')
    title = title.replace('_', '\\_')
    title = title.replace('^', '\\^')
    title = title.replace('~', '\\~')
    return title

def escape_bibtex_field(text: str) -> str:
    """Escape special characters in BibTeX fields."""
    if not text:
        return ""
    text = text.replace('{', '\\{').replace('}', '\\}')
    text = text.replace('#', '\\#')
    text = text.replace('$', '\\$')
    text = text.replace('%', '\\%')
    text = text.replace('&', '\\&')
    text = text.replace('_', '\\_')
    text = text.replace('^', '\\^')
    text = text.replace('~', '\\~')
    text = text.replace('\\', '\\textbackslash{}')
    return text

def extract_month_from_date(date_str: str) -> str:
    """Extract month from date string like '30 May 2025'."""
    if not date_str:
        return ""
    try:
        # Split and try to extract month
        parts = date_str.split()
        if len(parts) >= 2:
            month_str = parts[1].lower()
            month_map = {
                'january': 'jan', 'february': 'feb', 'march': 'mar', 'april': 'apr',
                'may': 'may', 'june': 'jun', 'july': 'jul', 'august': 'aug',
                'september': 'sep', 'october': 'oct', 'november': 'nov', 'december': 'dec',
                'jan': 'jan', 'feb': 'feb', 'mar': 'mar', 'apr': 'apr',
                'jun': 'jun', 'jul': 'jul', 'aug': 'aug', 'sep': 'sep',
                'oct': 'oct', 'nov': 'nov', 'dec': 'dec'
            }
            return month_map.get(month_str, "")
    except Exception:
        pass
    return ""

def convert_csv_to_bibtex(csv_file_path: str) -> List[str]:
    """Convert a single CSV file to BibTeX entries."""
    bibtex_entries = []
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row_idx, row in enumerate(reader):
            try:
                # Create a unique key for the entry
                title = row.get("Document Title", "")
                authors = row.get("Authors", "")
                if authors:
                    first_author = authors.split(';')[0].strip() if ';' in authors else authors.strip()
                    first_author_name = first_author.split()[-1] if first_author.split() else "Unknown"
                else:
                    first_author_name = "Unknown"
                year = row.get("Publication Year", "0000")
                title_part = clean_bibtex_key(title[:20]) if title else "title"
                key = f"{first_author_name}{year}{title_part}"
                
                # Ensure key is unique
                original_key = key
                counter = 1
                while any(entry.startswith(f"@article{{{key}") or
                          entry.startswith(f"@inproceedings{{{key}") or
                          entry.startswith(f"@conference{{{key}") or
                          entry.startswith(f"@book{{{key}") for entry in bibtex_entries):
                    key = f"{original_key}{counter}"
                    counter += 1
                
                # Determine entry type using the Document Identifier field
                doc_identifier = row.get("Document Identifier", "").strip().lower()
                if "conference" in doc_identifier:
                    entry_type = "inproceedings"
                elif "journal" in doc_identifier:
                    entry_type = "article"
                else:
                    # Fallback: try to determine from Publication Title if Document Identifier is not available
                    pub_title = row.get("Publication Title", "").lower()
                    if "conference" in pub_title or "inproceeding" in pub_title or "proceeding" in pub_title:
                        entry_type = "inproceedings"
                    elif "journal" in pub_title or "trans" in pub_title:
                        entry_type = "article"
                    else:
                        entry_type = "article"
                
                # Start building the BibTeX entry
                bibtex_entry = f"@{entry_type}{{{key},\n"
                if title:
                    bibtex_entry += f"  title = {{{clean_title(title)}}},\n"
                if authors:
                    bibtex_entry += f"  author = {{{clean_authors(authors)}}},\n"
                    
                pub_title = row.get("Publication Title", "")
                if pub_title:
                    if entry_type == "inproceedings":
                        bibtex_entry += f"  booktitle = {{{escape_bibtex_field(pub_title)}}},\n"
                    else:
                        bibtex_entry += f"  journal = {{{escape_bibtex_field(pub_title)}}},\n"
                        
                if year and year != "0000":
                    bibtex_entry += f"  year = {{{year}}},\n"
                    
                date_added = row.get("Date Added To Xplore", "")
                if date_added:
                    month = extract_month_from_date(date_added)
                    if month:
                        bibtex_entry += f"  month = {{{month}}},\n"
                        
                volume = row.get("Volume", "").strip()
                if volume:
                    bibtex_entry += f"  volume = {{{volume}}},\n"
                    
                issue = row.get("Issue", "").strip()
                if issue:
                    bibtex_entry += f"  number = {{{issue}}},\n"
                    
                start_page = row.get("Start Page", "").strip()
                end_page = row.get("End Page", "").strip()
                if start_page and end_page:
                    bibtex_entry += f"  pages = {{{start_page}--{end_page}}},\n"
                elif start_page:
                    bibtex_entry += f"  pages = {{{start_page}}},\n"
                    
                doi = row.get("DOI", "").strip()
                if doi:
                    bibtex_entry += f"  doi = {{{doi}}},\n"
                    
                issn = row.get("ISSN", "").strip()
                if issn:
                    bibtex_entry += f"  issn = {{{issn}}},\n"
                    
                isbn = row.get("ISBNs", "").strip()
                if isbn:
                    bibtex_entry += f"  isbn = {{{isbn}}},\n"
                    
                publisher = row.get("Publisher", "").strip()
                if publisher:
                    bibtex_entry += f"  publisher = {{{escape_bibtex_field(publisher)}}},\n"
                    
                abstract = row.get("Abstract", "").strip()
                if abstract:
                    bibtex_entry += f"  abstract = {{{escape_bibtex_field(abstract)}}},\n"
                    
                ieee_terms = row.get("IEEE Terms", "").strip()
                if ieee_terms:
                    # Convert semicolon-separated terms to comma-separated keywords
                    keywords = ieee_terms.replace(';', ',').replace('|', ',')
                    bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                    
                author_keywords = row.get("Author Keywords", "").strip()
                if author_keywords:
                    if ieee_terms:  # If we already have keywords, append to them
                        all_keywords = f"{ieee_terms}, {author_keywords}"
                        all_keywords = all_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(all_keywords)}}},\n"
                    else:
                        keywords = author_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                        
                pdf_link = row.get("PDF Link", "").strip()
                if pdf_link:
                    bibtex_entry += f"  url = {{{pdf_link}}},\n"
                    
                citation_count = row.get("Article Citation Count", "").strip()
                if citation_count and citation_count != "0":
                    bibtex_entry += f"  note = {{Citations: {citation_count}}},\n"
                    
                if row.get("Document Identifier"):
                    doc_id = row.get("Document Identifier", "").strip()
                    if doc_id:
                        bibtex_entry += f"  file = {{{doc_id}}},\n"
                        
                ref_count = row.get("Reference Count", "").strip()
                if ref_count:
                    bibtex_entry += f"  references = {{{ref_count}}},\n"
                    
                funding = row.get("Funding Information", "").strip()
                if funding:
                    bibtex_entry += f"  funding = {{{escape_bibtex_field(funding)}}},\n"
                    
                mesh_terms = row.get("Mesh_Terms", "").strip()
                if mesh_terms:
                    bibtex_entry += f"  mesh = {{{escape_bibtex_field(mesh_terms)}}},\n"
                    
                bibtex_entry += "}\n"
                bibtex_entries.append(bibtex_entry)
            except Exception as e:
                print(f"Error processing row {row_idx + 2} in {csv_file_path}: {e}")
                continue
    return bibtex_entries

def normalize_title_for_comparison(title):
    """Normalize title for duplicate detection by removing case, extra whitespace, and common variations."""
    if not title:
        return ""
    
    # Convert to lowercase
    normalized = title.lower()
    
    # Remove extra whitespace and normalize spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common punctuation variations that don't change meaning
    # Replace various dash types with standard space
    normalized = re.sub(r'[-–—]', ' ', normalized)
    
    # Remove extra spaces created by dash replacement
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common leading/trailing punctuation
    normalized = normalized.strip(' .,;:')
    
    return normalized

def import_bibtex(bib_file, db_path):
    """Import BibTeX file into existing v1.2 SQLite database"""
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' does not exist.")
        sys.exit(1)
    parser = BibTexParser(common_strings=True, homogenize_fields=True)
    parser.customization = homogenize_latex_encoding
    parser.ignore_nonstandard_types = False
    with open(bib_file, 'r', encoding='utf-8') as f:
        bib_db = bibtexparser.load(f, parser=parser)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
    if not cursor.fetchone():
        print("Error: The 'papers' table is missing.")
        conn.close()
        sys.exit(1)
        
    schema_cols = [
        "id", "type", "title", "authors", "year", "month", "journal", "volume", "pages", "page_count",
        "doi", "issn", "abstract", "keywords", "deannualized_conference",
        "user_trace", "changed", "changed_by", "verified", "verified_by", "estimated_score",
        "user_override_count", "pdf_filename", "pdf_state", "main_certainty", "classification",
        "set_1_llm", "set_2_llm", "set_3_llm", "set_1_llm_log", "set_2_llm_log", "set_3_llm_log", "llm_log"
    ]
    
    total_entries = len(bib_db.entries)
    processed_count = 0
    duplicate_count = 0
    print(f"Starting import of {total_entries} entries...")
    for entry in bib_db.entries:
        # Initialize all schema columns to None
        data = {col: None for col in schema_cols}
        
        # Set required defaults expected by the application logic
        data['user_override_count'] = 0
        data['pdf_state'] = 'none'
        data['set_1_llm_log'] = '[]'
        data['set_2_llm_log'] = '[]'
        data['set_3_llm_log'] = '[]'
        data['llm_log'] = '[]'
        data['main_certainty'] = '{}'
        data['classification'] = '{}'

        title_raw = entry.get('title', '')
        cleaned_title = clean_latex_commands(title_raw)
        
        raw_pages = entry.get('pages', '')
        normalized_pages, computed_page_count = parse_pages(raw_pages)

        # Try to get page_count from numpages field
        numpages_str = entry.get('numpages', '')
        page_count = None
        if numpages_str and str(numpages_str).isdigit():
            page_count = int(numpages_str)
        else:
            page_count = computed_page_count
            
        year_str = entry.get('year', '')
        year = int(year_str) if str(year_str).isdigit() else None
        
        doi = entry.get('doi', '')
        title = cleaned_title
        
        duplicate_found = False
        if doi:
            cursor.execute("SELECT id FROM papers WHERE doi = ?", (doi,))
            if cursor.fetchone():
                # print(f"Skipping duplicate entry with DOI '{doi}'")
                duplicate_found = True
                
        if not duplicate_found and title:
            normalized_title = normalize_title_for_comparison(title)
            if year:
                cursor.execute("SELECT id FROM papers WHERE LOWER(title) = ? AND year = ?", (normalized_title, year))
                if cursor.fetchone():
                    duplicate_found = True
            if not duplicate_found:
            # Also check for exact title match (case-insensitive) as additional safeguard
                cursor.execute("SELECT id FROM papers WHERE LOWER(title) = LOWER(?)", (title,))
                if cursor.fetchone():
                    duplicate_found = True
                    
        if duplicate_found:
            duplicate_count += 1
            continue  # Skip this entry
        # Generate a unique ID if the original ID already exists

        original_id = entry.get('ID', '')
        final_id = original_id
        counter = 1
        while True:
            cursor.execute("SELECT id FROM papers WHERE id = ?", (final_id,))
            if not cursor.fetchone():
                break
            final_id = f"{original_id}_{counter}"
            counter += 1

        # Normalize entry type: always use 'inproceedings' for conferences
        entry_type = entry.get('ENTRYTYPE', '').lower()
        if entry_type == 'conference':
            entry_type = 'inproceedings'
            
        data['id'] = final_id
        data['type'] = entry_type
        data['title'] = cleaned_title
        data['authors'] = parse_authors(entry.get('author', ''))
        data['year'] = year
        data['month'] = entry.get('month', '')
        data['journal'] = entry.get('journal', '') or entry.get('booktitle', '')
        data['volume'] = entry.get('volume', '')
        data['pages'] = normalized_pages
        data['page_count'] = page_count
        data['doi'] = doi
        data['issn'] = entry.get('issn', '')
        data['abstract'] = entry.get('abstract', '')
        data['keywords'] = parse_keywords(entry.get('keywords', ''))
        
        try:
            columns = ', '.join(data.keys())
            placeholders = ', '.join([f":{k}" for k in data.keys()])
            insert_query = f"INSERT INTO papers ({columns}) VALUES ({placeholders})"
            cursor.execute(insert_query, data)
        except Exception as e:
            print(f"\nError inserting entry '{data['id']}': {e}")
            continue
            
        processed_count += 1
        
        if total_entries > 0:
            if processed_count % 100 == 0 or processed_count == total_entries - duplicate_count:
                progress_percentage = int((processed_count / total_entries) * 100)
                filled_length = int(50 * processed_count // total_entries)
                bar = '█' * filled_length + '.' * (50 - filled_length)
                print(f"\r{'Progress:':<12} [{bar}] {progress_percentage}% ({processed_count}/{total_entries})", end='', flush=True)
                sys.stdout.flush()  # Force immediate output

    # Check if placeholder record with id=1 exists before import
    cursor.execute("SELECT COUNT(*) FROM papers WHERE id = '1'")    #Should actually check if this is the placeholder, surely?
    placeholder_exists = cursor.fetchone()[0] > 0
    # Delete the placeholder record with id=1 if it existed before import
    if placeholder_exists and processed_count > 0:
        cursor.execute("DELETE FROM papers WHERE id = '1'")
        print("\nRemoved placeholder record with id=1")

    conn.commit()
    print(f"\nImport completed: {processed_count} records imported, {duplicate_count} duplicates skipped")
    conn.close()