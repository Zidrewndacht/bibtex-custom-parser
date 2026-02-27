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
        // Show button: down arrow, no pressed state
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        // Remove ID from set and update URL (handled by filtering.js)
        openDetailIds.delete(paperId);
        updateUrlWithDetailState(); // Update URL immediately after hiding
    } else {
        // Showing the detail row
        // FIRST: Check if the history row for the same paper is open, close it if necessary
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            // Find the corresponding history toggle button in the main row and update it
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            if (historyToggleBtn) {
                 historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                 historyToggleBtn.classList.remove('toggle-pressed'); // FIX: Remove from historyToggleBtn, not element
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
        // Hide button: up arrow, pressed state
        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
        element.classList.add('toggle-pressed');
        // Add ID to set and update URL (handled by filtering.js)
        openDetailIds.add(paperId);
        updateUrlWithDetailState(); // Update URL immediately after showing
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
        }
        // Show button: down arrow, no pressed state
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        // Remove ID from set and update URL (handled by filtering.js)
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState(); // Update URL immediately after hiding
    } else {
        // Showing the history row
        // FIRST: Check if the detail row for the same paper is open, close it if necessary
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            // Find the corresponding detail toggle button in the main row and update it
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            if (detailToggleBtn) {
                detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                detailToggleBtn.classList.remove('toggle-pressed'); // FIX: Remove from detailToggleBtn, not element
            }
            openDetailIds.delete(paperId); // Remove detail ID from set
        }

        // NOW: Show the history row
        if (historyRow) {
            historyRow.classList.add('expanded');
            // Assuming history row content is static HTML loaded initially,
            // no fetch or dynamic listener setup needed here.
        }
        // Hide button: up arrow, pressed state
        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
        element.classList.add('toggle-pressed');
        // Add ID to set and update URL (handled by filtering.js)
        openHistoryIds.add(paperId);
        updateUrlWithDetailState(); // Update URL immediately after showing
    }
}


document.addEventListener('DOMContentLoaded', function () {
    //These listeners are specific to GH Export:
    
    //server-side search disabled for now as FTS is broken. Using full-client-side search everywhere instead:
    // searchInput.addEventListener('input', applyLocalFilters); //now defined in filtering.js
    hideOfftopicCheckbox.addEventListener('change', applyLocalFilters);
    minPageCountInput.addEventListener('input', applyLocalFilters);
    minPageCountInput.addEventListener('change', applyLocalFilters);

    yearFromInput.addEventListener('input', applyLocalFilters);
    yearFromInput.addEventListener('change', applyLocalFilters);
    yearToInput.addEventListener('input', applyLocalFilters);
    yearToInput.addEventListener('change', applyLocalFilters);
});
