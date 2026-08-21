// static/js/comms_files.js
/**
 * File I/O operations: PDF upload, BibTeX/CSV import,
 * HTML/XLSX export, backup & restore.
 * Depends on: pdfCellIndex (from filtering.js)
 */

// --- Status message references (shared DOM elements, local refs) ---
const batchStatusMessage_files = document.getElementById('batch-status-message');
const backupStatusMessage_files = document.getElementById('backup-status-message');

// ============================================================================
// PDF Upload
// ============================================================================

// Add a hidden file input element dynamically if it doesn't exist already
// (This avoids needing to add it to index.html)
if (!document.getElementById('pdf-file-input')) {
    const hiddenFileInput = document.createElement('input');
    hiddenFileInput.type = 'file';
    hiddenFileInput.id = 'pdf-file-input';
    hiddenFileInput.accept = '.pdf'; // Only accept PDF files
    hiddenFileInput.style.display = 'none';
    document.body.appendChild(hiddenFileInput);
}

// Reference the hidden input
const pdfFileInput = document.getElementById('pdf-file-input');

// Function to handle the actual upload
function uploadPDFForPaper(paperId) {
    const file = pdfFileInput.files[0];
    if (!file) {
        console.error("No file selected for upload.");
        alert("No file selected.");
        return;
    }

    if (!file.name.toLowerCase().endsWith('.pdf')) {
        alert("Please select a PDF file.");
        return;
    }

    const formData = new FormData();
    formData.append('pdf_file', file);

    // Show a simple loading indicator or disable interaction temporarily
    const uploadLink = document.querySelector(`.pdf-upload-link[data-paper-id="${paperId}"]`);
    if (uploadLink) {
        uploadLink.textContent = '⏳'; // Change icon to indicate processing
        uploadLink.style.pointerEvents = 'none'; // Disable clicks temporarily
    }

    fetch(`/upload_pdf/${encodeURIComponent(paperId)}`, { // Use encodeURIComponent for the string ID
        method: 'POST',
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                //console.log("PDF uploaded successfully for paper ID:", paperId);
                // Update the table row with the new PDF info
                // Pass the filename and state received from the server
                updateTableRowWithPDFData(paperId, data.pdf_filename, data.pdf_state);
            } else {
                console.error("Upload failed:", data.message);
                alert(`Upload failed: ${data.message}`);
                // Re-enable the link if it failed
                if (uploadLink) {
                    uploadLink.textContent = '❔';
                    uploadLink.style.pointerEvents = 'auto';
                }
            }
        })
        .catch(error => {
            console.error("Error during upload:", error);
            alert("An error occurred during upload.");
            // Re-enable the link if it failed
            if (uploadLink) {
                uploadLink.textContent = '❔';
                uploadLink.style.pointerEvents = 'auto';
            }
        });
}

function updateTableRowWithPDFData(paperId, filename, pdfState) {
    const row = document.querySelector(`tr[data-paper-id="${paperId}"]`);
    if (!row) return;
    const pdfCell = row.cells[pdfCellIndex];
    if (!pdfCell) return;

    pdfCell.innerHTML = '';
    pdfCell.title = "PDF Status";

    if (filename && (pdfState === 'PDF' || pdfState === 'annotated')) {
        const filenameWithoutExtension = filename.replace(/\.pdf$/i, '');
        const pdfLink = document.createElement('a');
        pdfLink.href = `/static/pdfjs/web/viewer.html?file=/serve_pdf/${encodeURIComponent(filenameWithoutExtension)}`;
        pdfLink.target = '_blank';
        pdfLink.title = pdfState === 'annotated'
            ? 'Open this annotated PDF in the Annotator'
            : 'Open this PDF in the Annotator';
        pdfLink.textContent = pdfState === 'annotated' ? '📗' : '📕';
        pdfCell.appendChild(pdfLink);
    } else {
        const uploadLink = document.createElement('a');
        uploadLink.href = '#';
        uploadLink.className = 'pdf-upload-link';
        uploadLink.setAttribute('data-paper-id', paperId);
        const isPaywalled = pdfState === 'paywalled';
        uploadLink.title = isPaywalled
            ? 'Article is paywalled. Click to upload if a copy is available'
            : 'No PDF stored yet. Click to upload PDF';
        uploadLink.textContent = isPaywalled ? '💰' : '❔';
        pdfCell.appendChild(uploadLink);
    }
}

// Event delegation for the PDF upload links
document.addEventListener('click', function (event) {
    if (event.target.classList.contains('pdf-upload-link')) {
        event.preventDefault(); // Prevent default link behavior

        // Get the paper ID as a string directly
        const paperId = event.target.getAttribute('data-paper-id');
        if (!paperId) { // Check if the ID string is empty or null
            console.error("Invalid or missing paper ID for PDF upload link.");
            return;
        }
        //console.log("Attempting upload for paper ID:", paperId); // Debug log

        // Reset the file input to allow selecting the same file again
        pdfFileInput.value = '';

        // Add event listener for when a file is selected
        pdfFileInput.onchange = function (e) {
            if (e.target.files.length > 0) {
                uploadPDFForPaper(paperId);
            }
        };

        // Trigger the hidden file input click
        pdfFileInput.click();
    }
});

// ============================================================================
// DOMContentLoaded — File I/O wiring
// ============================================================================
document.addEventListener('DOMContentLoaded', function () {
    // --- BibTeX Import Logic ---
    const importBibtexBtn = document.getElementById('import-bibtex-btn');
    const bibtexFileInput = document.getElementById('bibtex-file-input');

    // Clicking the button triggers the hidden file input
    importBibtexBtn.addEventListener('click', () => {
        bibtexFileInput.click();
    });

    // Handle file selection and upload
    bibtexFileInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (file) {
            if (!file.name.toLowerCase().endsWith('.bib') && !file.name.toLowerCase().endsWith('.csv')) {
                alert('Please select a .bib or .csv file.');
                bibtexFileInput.value = ''; // Clear the input
                return;
            }

            if (!confirm(`Are you sure you want to import '${file.name}'?`)) {
                bibtexFileInput.value = ''; // Clear the input
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            // Disable button and show status
            importBibtexBtn.disabled = true;
            importBibtexBtn.textContent = 'Importing...';
            if (batchStatusMessage_files) {
                batchStatusMessage_files.textContent = `Uploading and importing '${file.name}'...`;
                batchStatusMessage_files.style.color = ''; // Reset color
            }

            fetch('/upload_bibtex', {
                method: 'POST',
                body: formData // Use FormData for file uploads
                // Don't set Content-Type header, let browser set it with boundary
            })
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(errData => {
                            throw new Error(errData.message || `HTTP error! status: ${response.status}`);
                        }).catch(() => {
                            throw new Error(`HTTP error! status: ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.status === 'success') {
                        //console.log(data.message);
                        if (batchStatusMessage_files) {
                            batchStatusMessage_files.textContent = data.message;
                            batchStatusMessage_files.style.color = 'green'; // Success color
                        }
                        // Optional: Reload the page or fetch new data to show imported papers
                        // window.location.reload(); // Simple reload
                        // Or, fetch updated papers list (requires more JS logic)
                        setTimeout(() => { window.location.reload(); }, 1500); // Reload after delay
                    } else {
                        console.error("Import Error:", data.message);
                        if (batchStatusMessage_files) {
                            batchStatusMessage_files.textContent = `Import Error: ${data.message}`;
                            batchStatusMessage_files.style.color = 'red'; // Error color
                        }
                        alert(`Import failed: ${data.message}`);
                    }
                })
                .catch(error => {
                    console.error('Error uploading BibTeX file:', error);
                    if (batchStatusMessage_files) {
                        batchStatusMessage_files.textContent = `Upload Error: ${error.message}`;
                        batchStatusMessage_files.style.color = 'red'; // Error color
                    }
                    alert(`An error occurred during upload: ${error.message}`);
                })
                .finally(() => {    // Re-enable button and reset file input
                    importBibtexBtn.disabled = false;
                    importBibtexBtn.innerHTML = 'Import <strong>BibTeX</strong>'; // Restore original HTML
                    bibtexFileInput.value = '';
                });
        }
    });
    // --- End BibTeX Import Logic ---

    // --- Export HTML Button ---
    const exportHtmlBtn = document.getElementById('export-html-btn');
    exportHtmlBtn.addEventListener('click', function () {
        //console.log("Export HTML button clicked");

        // Gather current filter values from the UI elements
        const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
        const yearFromInput = document.getElementById('year-from');
        const yearToInput = document.getElementById('year-to');
        const minPageCountInput = document.getElementById('min-page-count');
        const searchInput = document.getElementById('search-input'); // Get search input

        let exportUrl = '/static_export?'; // Start building the URL

        // // Make lite export optional: Read checkbox state
        const liteExportCheckbox = document.getElementById('lite-export-checkbox');
        exportUrl += `lite=${liteExportCheckbox.checked ? '1' : '0'}&`;
        
        const skipAbstractsCheckbox = document.getElementById('skip-abstracts-checkbox');
        exportUrl += `skip_abstracts=${skipAbstractsCheckbox.checked ? '1' : '0'}&`;

        // Add filters to the URL query parameters
        if (hideOfftopicCheckbox) {
            exportUrl += `hide_offtopic=${hideOfftopicCheckbox.checked ? '1' : '0'}&`;
        }
        if (yearFromInput && yearFromInput.value) {
            exportUrl += `year_from=${encodeURIComponent(yearFromInput.value)}&`;
        }
        if (yearToInput && yearToInput.value) {
            exportUrl += `year_to=${encodeURIComponent(yearToInput.value)}&`;
        }
        if (minPageCountInput && minPageCountInput.value) {
            exportUrl += `min_page_count=${encodeURIComponent(minPageCountInput.value)}&`;
        }
        if (searchInput && searchInput.value) { // Add search query
            exportUrl += `search_query=${encodeURIComponent(searchInput.value)}&`;
        }
        // Remove trailing '&' or '?' if present
        exportUrl = exportUrl.replace(/&$/, '');

        //console.log("Export URL:", exportUrl);

        // --- Trigger the download asynchronously ---
        // Create a temporary invisible anchor element
        const link = document.createElement('a');
        link.href = exportUrl;
        link.style.display = 'none';
        // The filename will be suggested by the server's Content-Disposition header
        // link.download = 'PCBPapers_export.html'; // Optional: Suggest a default name if server doesn't set it
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        // Note: The browser's download manager should handle the file save dialog.
    });

    document.getElementById('export-xlsx-btn').addEventListener('click', function () {
        // Reuse the logic from exportStaticBtn or create a specific one
        // This example reuses the core logic
        const currentUrlParams = new URLSearchParams(window.location.search);
        const exportUrlParams = new URLSearchParams();

        // Copy relevant filter parameters
        const relevantParams = ['hide_offtopic', 'year_from', 'year_to', 'min_page_count', 'search_query'];
        relevantParams.forEach(param => {
            const value = currentUrlParams.get(param);
            if (value !== null) {
                exportUrlParams.set(param, value);
            }
        });

        // Construct the URL for the Excel export endpoint
        const exportUrl = `/xlsx_export?${exportUrlParams.toString()}`;
        //console.log("Exporting Excel with URL:", exportUrl);

        // Trigger the download
        window.location.href = exportUrl;
    });

    const backupBtn = document.getElementById('backup-btn');
    backupBtn.addEventListener('click', function () {
        document.documentElement.classList.add('busyCursor');
        //console.log("Backup button clicked");
        backupStatusMessage_files.textContent = 'Creating backup...';
        backupStatusMessage_files.style.color = '';

        // Create backup URL with current filters
        const currentUrlParams = new URLSearchParams(window.location.search);
        const backupUrl = `/backup?${currentUrlParams.toString()}`;

        // Use fetch to get the backup file
        fetch(backupUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Backup failed: ${response.status} ${response.statusText}`);
                }
                // Extract filename from Content-Disposition header
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'backup.parsa.tzst';
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
                    if (filenameMatch) {
                        filename = filenameMatch[1];
                    }
                }
                return response.blob().then(blob => ({ blob, filename }));
            })
            .then(({ blob, filename }) => {
                // Create a download link for the backup file
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);

                backupStatusMessage_files.textContent = 'Backup created successfully!';
                backupStatusMessage_files.style.color = 'green';
                document.documentElement.classList.remove('busyCursor');
            })
            .catch(error => {
                console.error('Backup error:', error);
                backupStatusMessage_files.textContent = `Backup Error: ${error.message}`;
                backupStatusMessage_files.style.color = 'red';
                alert(`An error occurred during backup: ${error.message}`);
                document.documentElement.classList.remove('busyCursor');
            });
    });

    const restoreBtn = document.getElementById('restore-btn');
    restoreBtn.addEventListener('click', function () {
        // Create file input for backup selection
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.tzst';
        fileInput.style.display = 'none';

        fileInput.addEventListener('change', function (event) {
            const file = event.target.files[0];
            if (!file) return;

            // Validate file extension
            if (!file.name.endsWith('.parsa.tzst')) {
                alert('Invalid backup file. Expected .parsa.tzst file.');
                return;
            }

            // Create FormData and send restore request
            const formData = new FormData();
            formData.append('backup_file', file);

            // Show status message
            backupStatusMessage_files.textContent = `Restoring from ${file.name}...`;
            backupStatusMessage_files.style.color = '';

            fetch('/restore', {
                method: 'POST',
                body: formData
            })
                .then(response => response.json())
                .then(data => {
                    document.documentElement.classList.add('busyCursor');
                    if (data.status === 'success') {
                        //console.log(data.message);
                        backupStatusMessage_files.textContent = data.message;
                        backupStatusMessage_files.style.color = 'green';
                        // Reload page after successful restore
                        setTimeout(() => { window.location.reload(); }, 2000);
                    } else {
                        console.error("Restore Error:", data.message);
                        backupStatusMessage_files.textContent = `Restore Error: ${data.message}`;
                        backupStatusMessage_files.style.color = 'red';
                        alert(`Restore failed: ${data.message}`);
                    }
                    document.documentElement.classList.remove('busyCursor');
                })
                .catch(error => {
                    document.documentElement.classList.add('busyCursor');
                    console.error('Restore error:', error);
                    backupStatusMessage_files.textContent = `Restore Error: ${error.message}`;
                    backupStatusMessage_files.style.color = 'red';
                    alert(`An error occurred during restore: ${error.message}`);
                    document.documentElement.classList.remove('busyCursor');
                });
        });

        // Trigger file selection
        document.body.appendChild(fileInput);
        fileInput.click();
        document.body.removeChild(fileInput);
    });
});