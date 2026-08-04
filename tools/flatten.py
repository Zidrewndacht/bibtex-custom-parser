"""
Flatten a source code folder into a single markdown/txt file with syntax highlighting.
Useful for NotebookLM import
"""

import os
import sys
from pathlib import Path

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Maximum file size in bytes (1MB = 1024 * 1024 bytes)
MAX_FILE_SIZE = 1024 * 1024 

def get_language_extension(file_path):
    """
    Determine the appropriate markdown language identifier for syntax highlighting.
    """
    # Common file extensions and their corresponding markdown language identifiers
    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'jsx',
        '.tsx': 'tsx',
        '.html': 'html',
        '.htm': 'html',
        '.css': 'css',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        '.sql': 'sql',
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.rb': 'ruby',
        '.php': 'php',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.kts': 'kotlin',
        '.scala': 'scala',
        '.sc': 'scala',
        '.pl': 'perl',
        '.pm': 'perl',
        '.r': 'r',
        '.jl': 'julia',
        '.lua': 'lua',
        '.dart': 'dart',
        '.ex': 'elixir',
        '.exs': 'elixir',
        '.erl': 'erlang',
        '.hrl': 'erlang',
        '.clj': 'clojure',
        '.cljs': 'clojurescript',
        '.coffee': 'coffeescript',
        '.ls': 'livescript',
        '.md': 'markdown',
        '.txt': 'text',
        '.log': 'text',
        '.ini': 'ini',
        '.toml': 'toml',
        '.dockerfile': 'dockerfile',
        '.gitignore': 'gitignore',
        '.env': 'env',
    }
    
    ext = Path(file_path).suffix.lower()
    return language_map.get(ext, 'text')  # Default to 'text' if unknown

def is_binary_file(file_path):
    """
    Check if a file is binary by attempting to read it as text.
    """
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)  # Read first 1KB to check
        
        if len(chunk) == 0:
            return False  # Empty file is not binary
        
        # Check for UTF-16 BOM
        if chunk.startswith(b'\xff\xfe') or chunk.startswith(b'\xfe\xff'):
            # This is UTF-16 with BOM, treat as text
            return False
        
        # Check for null bytes in typical binary patterns
        # But be more lenient for UTF-16 text patterns
        null_byte_ratio = chunk.count(b'\x00') / len(chunk) if len(chunk) > 0 else 0
        
        if null_byte_ratio > 0.3:  # If more than 30% are null bytes, likely binary
            # But check if it looks like UTF-16 text (alternating pattern)
            utf16_pattern_count = 0
            for i in range(0, len(chunk) - 1, 2):
                if i + 1 < len(chunk):
                    # UTF-16 LE: ASCII character followed by null byte
                    if chunk[i] != 0 and chunk[i + 1] == 0:
                        utf16_pattern_count += 1
                    # UTF-16 BE: null byte followed by ASCII character
                    elif chunk[i] == 0 and chunk[i + 1] != 0:
                        utf16_pattern_count += 1
            
            utf16_ratio = utf16_pattern_count * 2 / len(chunk) if len(chunk) > 0 else 0
            
            # If at least 40% of the content follows UTF-16 pattern, treat as text
            if utf16_ratio > 0.4:
                return False
        
        # Check for other common binary indicators
        binary_indicators = [b'\x00\x00\x00', b'\x00\x00\x01', b'\x01\x00\x00']
        for indicator in binary_indicators:
            if indicator in chunk:
                return True
        
        # Count printable characters
        printable_chars = 0
        for byte in chunk:
            if 32 <= byte <= 126 or byte in [9, 10, 13, 11, 12]:  # printable ASCII + common whitespace
                printable_chars += 1
        
        printable_ratio = printable_chars / len(chunk) if len(chunk) > 0 else 0
        
        # If less than 70% is printable, consider it binary
        if printable_ratio < 0.7:
            return True
        else:
            return False
                
    except Exception:
        return True

def should_ignore_file(file_path):
    """
    Check if a file should be ignored based on common patterns.
    """
    path = Path(file_path)
    file_name = path.name.lower()
    
    # Common files and directories to ignore
    ignore_patterns = [
        '__pycache__',
        '.git',
        '.svn',
        '.hg',
        '.DS_Store',
        '.idea',
        '.vscode',
        '.venv',
        'node_modules',
        '.next',
        '.nuxt',
        'dist',
        'build',
        'target',
        '.gradle',
        '.cargo',
        'Pods',
        '.pytest_cache',
        '__pycache__',
        '*.pyc',
        '*.pyo',
        '*.so',
        '*.dll',
        '*.exe',
        '*.bin',
        '*.zip',
        '*.tar',
        '*.gz',
        '*.rar',
        '*.7z',
        '*.pdf',
        '*.jpg',
        '*.jpeg',
        '*.png',
        '*.gif',
        '*.bmp',
        '*.ico',
        '*.mp3',
        '*.mp4',
        '*.avi',
        '*.mov',
        '*.wav',
        '*.woff',
        '*.woff2',
        '*.ttf',
        '*.eot',
        '*.pptx',
        '*.xlsx',
        '*.docx',
        '*.docx',
        '*.min.js'
    ]
    
    # Check if the file/directory name matches any ignore pattern
    for pattern in ignore_patterns:
        if pattern.startswith('*'):
            # It's a file extension pattern
            if path.suffix.lower() == pattern[1:]:
                return True
        elif file_name == pattern:
            return True
        elif pattern in str(path):
            return True
    
    return False

def is_file_too_large(file_path, max_size=MAX_FILE_SIZE):
    """
    Check if a file exceeds the maximum allowed size.
    """
    try:
        file_size = os.path.getsize(file_path)
        return file_size > max_size
    except OSError:
        # If we can't get the file size, assume it's too large
        return True

def read_file_with_fallback_encoding(file_path):
    """
    Try to read a file with multiple encodings as fallback.
    """
    encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'latin-1', 'cp1252', 'ascii']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
                # print(f"DEBUG: Successfully read {file_path} with encoding {encoding}")
                return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            # print(f"DEBUG: Error reading {file_path} with encoding {encoding}: {e}")
            continue
    
    raise Exception(f"Could not decode file {file_path} with any of the attempted encodings: {encodings}")

def flatten_files(file_list, output_file, max_file_size=MAX_FILE_SIZE):
    """
    Flatten a list of specific files into a single markdown file.
    """
    with open(output_file, 'w', encoding='utf-8') as out_file:
        for file_path in file_list:
            file_path = Path(file_path)
            
            # Check if file exists
            if not file_path.exists():
                print(f"Warning: File does not exist: {file_path}")
                continue
            
            # print(f"Processing: {file_path}")
            
            # Skip if file should be ignored
            if should_ignore_file(file_path):
                print(f"Skipping ignored file: {file_path}")
                continue
            
            # Skip if file is too large
            if is_file_too_large(file_path, max_file_size):
                # print(f"Skipping large file (> {max_file_size/1024:.0f}KB): {file_path}")
                continue
            
            # Try to read the file first with fallback encoding
            # If it fails due to encoding issues, we'll skip it
            # If it succeeds, we know it's not truly binary
            try:
                content = read_file_with_fallback_encoding(file_path)
                # print(f"File {file_path} is readable with text encoding, processing...")
            except Exception as e:
                # If we can't read it as text, check if it's truly binary
                if is_binary_file(file_path):
                    print(f"Skipping binary file: {file_path}")
                    continue
                else:
                    # It's not binary but we couldn't read it - skip with error
                    print(f"Error reading file {file_path}: {e}")
                    continue
            
            # Determine language for syntax highlighting
            language = get_language_extension(file_path)
            
            # Write file header with markdown code block
            out_file.write(f"# {file_path}\n")
            out_file.write(f"```{language}\n")
            
            # Write file content (already read above)
            out_file.write(content)
            
            # Ensure file ends with a newline
            if content and not content.endswith('\n'):
                out_file.write('\n')
            
            # Close the markdown code block
            out_file.write("```\n\n")
            
            print(f"Successfully processed: {file_path}")
    
    print(f"\nFlattened source code written to: {output_file}")
    print(f"Maximum file size: {max_file_size/1024:.0f}KB")

def main():
    # Predefined list of files to include in the flattened output
    # Updated to reflect the new folder structure (modules, web/static, web/templates, etc.)
    FILE_LIST = [
        # # Root files
        "browse_db.py",
        "queue_manager.py",
        # "README.md",
        
        # # # Prompt templates
        # "prompt_templates/classify_template.txt",
        # "prompt_templates/reclassify_template.txt",
        # "prompt_templates/verify_template.txt",
        
        # # # Queue manager module
        "queue_manager/__init__.py",
        "queue_manager/dispatcher.py",
        "queue_manager/logging_utils.py",
        "queue_manager/routes.py",
        "queue_manager/state.py",

        # Meta module
        "meta/agreement_core.py",
        # "meta/agreement_human_cli_v1.4.py",
        # "meta/agreement_3sets_cli_v1.4.py",
        # "meta/time_power_charts_v1.4.py",
        
        # Shared module
        "shared/__init__.py",
        "shared/config.py",
        "shared/db.py",
        
        # Web module
        "web/__init__.py",
        # "web/export_logic.py",
        "web/filters.py",
        # "web/importer.py",
        # "web/routes_data.py",
        # "web/routes_files.py",
        "web/routes_ui.py",
        
        # Web static files
        "web/static/js/agreement_report.js",
        # "web/static/js/comms/comms_batch.js",
        # "web/static/js/comms/comms_files.js",
        # "web/static/js/comms/comms_rendering.js",
        # "web/static/js/comms/comms_save.js",
        # "web/static/js/comms/comms_views.js",
        # "web/static/js/filtering/filtering_actions.js",
        # "web/static/js/filtering/filtering_engine.js",
        # "web/static/js/filtering/filtering_init.js",
        # "web/static/js/filtering/filtering_state.js",
        # "web/static/js/ghpages.js",
        # "web/static/js/stats/stats_core.js",
        # "web/static/js/stats/stats_generic.js",
        # "web/static/js/stats/stats_domain.js",
        # "web/static/js/stats/stats_charts.js",
        # "web/static/js/stats/stats_latex.js",

        "web/static/css/style.css",
        "web/static/css/agreement_report.css",
        # "web/static/css/fonts.css",
        
        # Web static pdfjs files (kept as previously specified)
        # "web/static/pdfjs/web/autosave.js",
        # "web/static/pdfjs/web/viewer.html",
        # "web/static/pdfjs/web/viewer_mods.css",
        
        # Web templates
        # "web/templates/agreement_report.html",
        # "web/templates/about_modal_content.html",
        # "web/templates/detail_row.html",
        # "web/templates/history_row.html",
        "web/templates/index.html",
        # "web/templates/papers_table.html",
        # "web/templates/papers_table_tfoot.html",
        # "web/templates/stats_modal_content.html",
        # "web/templates/static_export/loader.html",
        # "web/templates/static_export/index_static_export.html",
        # "web/templates/static_export/papers_table_static_export.html"
    ]
    
    # Remove any non-existent files from the list
    FILE_LIST = [f for f in FILE_LIST if Path(f).exists()]
    
    if not FILE_LIST:
        print("Error: No files found in the predefined file list.")
        print("Please update the FILE_LIST variable with valid file paths.")
        sys.exit(1)
    
    # Default output file name
    output_file = "flattened_code.txt"
    
    # Parse command line arguments for optional custom output file
    if len(sys.argv) > 1:
        output_file = sys.argv[1]
    
    # Parse optional max file size argument (in KB)
    max_file_size_kb = 100  # default to 100KB
    if len(sys.argv) > 2:
        try:
            max_file_size_kb = int(sys.argv[2])
        except ValueError:
            print("Error: max_file_size_kb must be a valid integer")
            sys.exit(1)
    
    max_file_size_bytes = max_file_size_kb * 1024
    
    flatten_files(FILE_LIST, output_file, max_file_size_bytes)

if __name__ == "__main__":
    main()