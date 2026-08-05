//static/pdfjs/web/autosave.js
//Autosave script for ResearchParsa Annotator based on PDF.js
document.addEventListener('DOMContentLoaded', function () {
    const PDFViewerApplication = window.PDFViewerApplication;
    if (!PDFViewerApplication) {
        console.error("PDFViewerApplication is not available.");
        return;
    }

    // --- 1. Get the paper_id from the URL ---
    const urlParams = new URLSearchParams(window.location.search);
    const fileUrl = urlParams.get('file');
    let paperId = '';
    if (fileUrl) {
        // The URL is now /serve_pdf/paper_id
        paperId = decodeURIComponent(fileUrl.split('/').pop());
    }

    if (!paperId) {
        console.error("Could not determine the paper_id from the URL.");
        return;
    }
    
    // --- NEW: Function to show auto-save notification ---
    function showAutoSaveNotification() {
        // Remove any existing notification first
        const existingNotification = document.getElementById('autosave-notification');
        if (existingNotification) {
            existingNotification.remove();
        }
        
        // Create notification element
        const notification = document.createElement('div');
        notification.id = 'autosave-notification';
        notification.innerHTML = 'Annotations <b>auto-saved</b> ✓';
        
        // Style the notification
        notification.style.position = 'fixed';
        notification.style.top = '60px';
        notification.style.right = '250px';
        notification.style.backgroundColor = '#4CAF50';
        notification.style.color = 'white';
        notification.style.padding = '10px 15px';
        notification.style.borderRadius = '6px';
        notification.style.textShadow = '1px 0 5px #454d';
        notification.style.border = '1px solid var(--primary-ui-color)';
        notification.style.boxShadow = '0 4px 8px 1px #0004';
        notification.style.zIndex = '10000';
        notification.style.transition = 'opacity 0.5s ease';
        notification.style.fontFamily = 'sans-serif';
        notification.style.fontSize = '16px';
        
        // Add to document
        document.body.appendChild(notification);
        
        // Set timeout to fade out and remove
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 500); // Wait for fade-out transition
        }, 7500); // Show for 7.5 seconds, then fade out for 0.5s
    }

    // --- 2. Debounce function ---
    function debounce(func, delay) {
        let timeoutId;
        return function (...args) {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => func.apply(this, args), delay);
        };
    }

    // --- 3. Function to save and upload the annotated PDF ---
    async function saveAndUploadPdf() {
        try {
            // This is the core PDF.js function to get the modified file data [13-15]
            const updatedPdfData = await PDFViewerApplication.pdfDocument.saveDocument();
            const blob = new Blob([updatedPdfData], { type: 'application/pdf' });
            const formData = new FormData();
            formData.append('pdf_file', blob, "annotated.pdf");

            // Construct the NEW server route using the paper_id
            const uploadUrl = `/upload_annotated_pdf/${encodeURIComponent(paperId)}`;
            
            // --- 4. Send the file to the new server route ---
            const response = await fetch(uploadUrl, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                throw new Error(`Server responded with status: ${response.status}`);
            }
            const result = await response.json();
            if (result.status === 'success') {
                console.log('Auto-save successful:', result.message);
                // Show user feedback for successful auto-save
                showAutoSaveNotification();
            } else {
                console.error('Auto-save failed:', result.message);
            }
        } catch (error) {
            console.error('An error occurred during auto-save:', error);
        }
    }

    // --- 5. Create debounced version of the save function ---
    const debouncedSaveAndUploadPdf = debounce(saveAndUploadPdf, 5000); // 5 seconds

    // --- 6. Listen for annotation events to trigger the debounced auto-save ---
    // 'annotationeditorstateschanged' is a robust event for this purpose [16]
    PDFViewerApplication.eventBus.on('annotationeditorstateschanged', (evt) => {
        if (evt.details.isEditing) {
            console.log('Annotation change detected, triggering debounced auto-save.');
            debouncedSaveAndUploadPdf();
        }
    });

    console.log(`Auto-save script initialized for paper_id: ${paperId}.`);
});