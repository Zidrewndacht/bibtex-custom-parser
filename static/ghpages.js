// static/ghpages.js
// Logic exclusive to the client-side-only standalone HTML/GHpages version

const minPageCountInput = document.getElementById('min-page-count');
const yearFromInput = document.getElementById('year-from');
const yearToInput = document.getElementById('year-to');

const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
const totalPaperCount = allRows.length;

/**
 * Toggles the visibility of the detail row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 */
function toggleDetails(element) {
    const row = element.closest('tr');
    // The detail row is the first sibling after the main row
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
                      row.nextElementSibling : null;

    // The history row is the second sibling after the main row
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
                       row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                       row.nextElementSibling.nextElementSibling : null;

    const isExpanded = detailRow && detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        // Hiding the detail row
        if (detailRow) {
            detailRow.classList.remove('expanded');
            // Remove listener if stored
            const detailContentContainer = detailRow.querySelector('.detail-flex-container');
            if (detailContentContainer && detailContentContainer._clickableItemListener) {
                 detailContentContainer.removeEventListener('click', detailContentContainer._clickableItemListener);
                 detailContentContainer._clickableItemListener = null;
            }
        }
        element.innerHTML = '<span>Show</span>';
        // Remove ID from set and update URL (handled by filtering.js)
        openDetailIds.delete(paperId);
        updateUrlWithDetailState(); // Update URL immediately after hiding
        //console.log(`Closed detail for ${paperId}, set now:`, [...openDetailIds]); // Debug log
    } else {
        // Showing the detail row
        // FIRST: Check if the history row for the same paper is open, close it if necessary
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            // Find the corresponding history toggle button in the main row and update its text
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            if (historyToggleBtn) {
                 historyToggleBtn.innerHTML = '<span>Show</span>';
            }
            openHistoryIds.delete(paperId); // Remove history ID from set
        }

        // NOW: Show the detail row
        if (detailRow) {
            detailRow.classList.add('expanded');
            const detailContentContainer = detailRow.querySelector('.detail-flex-container');
            if (detailContentContainer) {
                 if (detailContentContainer._clickableItemListener) {
                     detailContentContainer.removeEventListener('click', detailContentContainer._clickableItemListener);
                 }
                 const clickableItemListener = function(event) {
                     if (event.target.classList.contains('clickable-item')) {
                         event.preventDefault();
                         const searchTerm = event.target.getAttribute('data-search-term');
                         if (searchTerm) {
                             searchInput.value = searchTerm.trim();
                             applyLocalFilters();
                         }
                     }
                 };
                 detailContentContainer.addEventListener('click', clickableItemListener);
                 detailContentContainer._clickableItemListener = clickableItemListener;
            } else {
                 console.warn("Detail content container not found for paper", paperId);
            }
        }
        element.innerHTML = '<span>Hide</span>';
        // Add ID to set and update URL (handled by filtering.js)
        openDetailIds.add(paperId);
        updateUrlWithDetailState(); // Update URL immediately after showing
        //console.log(`Opened detail for ${paperId}, set now:`, [...openDetailIds]); // Debug log
    }
}

/**
 * Toggles the visibility of the history row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 */
function toggleHistory(element) {
    const row = element.closest('tr');
    // The history row is the second sibling after the main row (detail row is the first)
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
                       row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
                       row.nextElementSibling.nextElementSibling : null;

    // The detail row is the first sibling after the main row
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
                      row.nextElementSibling : null;

    const isExpanded = historyRow && historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        // Hiding the history row
        if (historyRow) {
            historyRow.classList.remove('expanded');
            // No specific event listener removal needed for history row if it's just static content
            // If it had dynamic content, you would remove its listener here similarly.
        }
        element.innerHTML = '<span>Show</span>';
        // Remove ID from set and update URL (handled by filtering.js)
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState(); // Update URL immediately after hiding
        //console.log(`Closed history for ${paperId}, set now:`, [...openHistoryIds]); // Debug log
    } else {
        // Showing the history row
        // FIRST: Check if the detail row for the same paper is open, close it if necessary
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            // Find the corresponding detail toggle button in the main row and update its text
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            if (detailToggleBtn) {
                detailToggleBtn.innerHTML = '<span>Show</span>';
            }
            openDetailIds.delete(paperId); // Remove detail ID from set
        }

        // NOW: Show the history row
        if (historyRow) {
            historyRow.classList.add('expanded');
            // Assuming history row content is static HTML loaded initially,
            // no fetch or dynamic listener setup needed here.
        }
        element.innerHTML = '<span>Hide</span>';
        // Add ID to set and update URL (handled by filtering.js)
        openHistoryIds.add(paperId);
        updateUrlWithDetailState(); // Update URL immediately after showing
        //console.log(`Opened history for ${paperId}, set now:`, [...openHistoryIds]); // Debug log
    }
}


document.addEventListener('DOMContentLoaded', function () {
    //These listeners are specific to GH Export:
    
    //server-side search disabled for now as FTS is broken. Using full-client-side search everyhwere instead:
    // searchInput.addEventListener('input', applyLocalFilters); //now defined in filtering.js
    hideOfftopicCheckbox.addEventListener('change', applyLocalFilters);
    minPageCountInput.addEventListener('input', applyLocalFilters);
    minPageCountInput.addEventListener('change', applyLocalFilters);

    yearFromInput.addEventListener('input', applyLocalFilters);
    yearFromInput.addEventListener('change', applyLocalFilters);
    yearToInput.addEventListener('input', applyLocalFilters);
    yearToInput.addEventListener('change', applyLocalFilters);
});

// Ensure global variables openDetailIds and openHistoryIds are defined elsewhere
// or initialize them here if needed, e.g.:
// let openDetailIds = new Set();
// let openHistoryIds = new Set();
// (However, since filtering.js handles URL state and initializes them,
// these variables should ideally be available globally after filtering.js loads).