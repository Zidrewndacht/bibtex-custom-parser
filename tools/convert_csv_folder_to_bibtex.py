# convert_csv_to_bibtex.py
# Tool to convert a folder full of IEEE Xplore CSV files onto a single BibTeX, compatible with the importer accessible from the Web GUI

import csv
import os
import re
from typing import List

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
    except:
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
                
                # Add title
                if title:
                    bibtex_entry += f"  title = {{{clean_title(title)}}},\n"
                
                # Add authors
                if authors:
                    bibtex_entry += f"  author = {{{clean_authors(authors)}}},\n"
                
                # Add journal/booktitle
                pub_title = row.get("Publication Title", "")
                if pub_title:
                    if entry_type == "inproceedings":
                        bibtex_entry += f"  booktitle = {{{escape_bibtex_field(pub_title)}}},\n"
                    else:
                        bibtex_entry += f"  journal = {{{escape_bibtex_field(pub_title)}}},\n"
                
                # Add year
                if year and year != "0000":
                    bibtex_entry += f"  year = {{{year}}},\n"
                
                # Add month
                date_added = row.get("Date Added To Xplore", "")
                if date_added:
                    month = extract_month_from_date(date_added)
                    if month:
                        bibtex_entry += f"  month = {{{month}}},\n"
                
                # Add volume if available
                volume = row.get("Volume", "").strip()
                if volume:
                    bibtex_entry += f"  volume = {{{volume}}},\n"
                
                # Add issue as number if available
                issue = row.get("Issue", "").strip()
                if issue:
                    bibtex_entry += f"  number = {{{issue}}},\n"
                
                # Add pages if available
                start_page = row.get("Start Page", "").strip()
                end_page = row.get("End Page", "").strip()
                if start_page and end_page:
                    bibtex_entry += f"  pages = {{{start_page}--{end_page}}},\n"
                elif start_page:
                    bibtex_entry += f"  pages = {{{start_page}}},\n"
                
                # Add DOI if available
                doi = row.get("DOI", "").strip()
                if doi:
                    bibtex_entry += f"  doi = {{{doi}}},\n"
                
                # Add ISSN if available
                issn = row.get("ISSN", "").strip()
                if issn:
                    bibtex_entry += f"  issn = {{{issn}}},\n"
                
                # Add ISBN if available
                isbn = row.get("ISBNs", "").strip()
                if isbn:
                    bibtex_entry += f"  isbn = {{{isbn}}},\n"
                
                # Add publisher if available
                publisher = row.get("Publisher", "").strip()
                if publisher:
                    bibtex_entry += f"  publisher = {{{escape_bibtex_field(publisher)}}},\n"
                
                # Add abstract (the fully-featured part you wanted!)
                abstract = row.get("Abstract", "").strip()
                if abstract:
                    bibtex_entry += f"  abstract = {{{escape_bibtex_field(abstract)}}},\n"
                
                # Add keywords from IEEE Terms (as keyword field)
                ieee_terms = row.get("IEEE Terms", "").strip()
                if ieee_terms:
                    # Convert semicolon-separated terms to comma-separated keywords
                    keywords = ieee_terms.replace(';', ',').replace('|', ',')
                    bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                
                # Add author keywords if available
                author_keywords = row.get("Author Keywords", "").strip()
                if author_keywords:
                    if ieee_terms:  # If we already have keywords, append to them
                        all_keywords = f"{ieee_terms}, {author_keywords}"
                        all_keywords = all_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(all_keywords)}}},\n"
                    else:
                        keywords = author_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                
                # Add PDF link if available
                pdf_link = row.get("PDF Link", "").strip()
                if pdf_link:
                    bibtex_entry += f"  url = {{{pdf_link}}},\n"
                
                # Add note about citation counts
                citation_count = row.get("Article Citation Count", "").strip()
                if citation_count and citation_count != "0":
                    bibtex_entry += f"  note = {{Citations: {citation_count}}},\n"
                
                if row.get("Document Identifier"):
                    doc_id = row.get("Document Identifier", "").strip()
                    if doc_id:
                        bibtex_entry += f"  file = {{{doc_id}}},\n"
                
                # Add reference count as a custom field
                ref_count = row.get("Reference Count", "").strip()
                if ref_count:
                    bibtex_entry += f"  references = {{{ref_count}}},\n"
                
                # Add funding information as a custom field
                funding = row.get("Funding Information", "").strip()
                if funding:
                    bibtex_entry += f"  funding = {{{escape_bibtex_field(funding)}}},\n"
                
                # Add Mesh terms as a custom field
                mesh_terms = row.get("Mesh_Terms", "").strip()
                if mesh_terms:
                    bibtex_entry += f"  mesh = {{{escape_bibtex_field(mesh_terms)}}},\n"
                
                bibtex_entry += "}\n\n"
                bibtex_entries.append(bibtex_entry)
                
            except Exception as e:
                print(f"Error processing row {row_idx + 2} in {csv_file_path}: {e}")
                continue
    
    return bibtex_entries

def main():
    """Main function to process all CSV files in a folder."""
    # Get folder path from user or use current directory
    folder_path = input("Enter the folder path containing CSV files (or press Enter for current directory): ").strip()
    if not folder_path:
        folder_path = "."
    
    output_file = input("Enter the output BibTeX file name (or press Enter for 'output.bib'): ").strip()
    if not output_file:
        output_file = "output.bib"
    
    # Find all CSV files in the folder
    csv_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.csv')]
    
    if not csv_files:
        print(f"No CSV files found in {folder_path}")
        return
    
    print(f"Found {len(csv_files)} CSV files: {csv_files}")
    
    all_entries = []
    for csv_file in csv_files:
        csv_path = os.path.join(folder_path, csv_file)
        print(f"Processing {csv_file}...")
        entries = convert_csv_to_bibtex(csv_path)
        all_entries.extend(entries)
        print(f"  Added {len(entries)} entries")
    
    # Write all entries to the output file
    with open(output_file, 'w', encoding='utf-8') as bibfile:
        bibfile.write("% Generated BibTeX file from CSV data\n")
        bibfile.write("% Contains entries from multiple CSV files\n")
        bibfile.write("% Fully-featured with abstracts, keywords, and custom fields\n\n")
        for entry in all_entries:
            bibfile.write(entry)
    
    print(f"\nSuccessfully created {output_file} with {len(all_entries)} entries")
    print("Fields included: title, author, journal/booktitle, year, month, volume, number, pages, doi, issn, isbn, publisher, abstract, keywords, url, and custom fields")

if __name__ == "__main__":
    main()