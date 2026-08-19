// static/ghpages.js
// Logic exclusive to the client-side-only standalone HTML/GHpages version
const minPageCountInput = document.getElementById('min-page-count');
const yearFromInput = document.getElementById('year-from');
const yearToInput = document.getElementById('year-to');
const allRows = document.querySelectorAll('#papersTable tbody tr[data-paper-id]');
const totalPaperCount = allRows.length;

function toggleDetails(element) {
    const row = element.closest('tr');
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ? row.nextElementSibling : null;
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling && row.nextElementSibling.nextElementSibling.classList.contains('history-row') ? row.nextElementSibling.nextElementSibling : null;
    const isExpanded = detailRow && detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        if (detailRow) {
            detailRow.classList.remove('expanded');
            const detailContentContainer = detailRow.querySelector('.detail-flex-container');
            if (detailContentContainer && detailContentContainer._clickableItemListener) {
                detailContentContainer.removeEventListener('click', detailContentContainer._clickableItemListener);
                detailContentContainer._clickableItemListener = null;
            }
        }
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        openDetailIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            if (historyToggleBtn) {
                historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                historyToggleBtn.classList.remove('toggle-pressed');
            }
            openHistoryIds.delete(paperId);
        }
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
            }
        }
        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
        element.classList.add('toggle-pressed');
        openDetailIds.add(paperId);
        updateUrlWithDetailState();
    }
}

function toggleHistory(element) {
    const row = element.closest('tr');
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling && row.nextElementSibling.nextElementSibling.classList.contains('history-row') ? row.nextElementSibling.nextElementSibling : null;
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ? row.nextElementSibling : null;
    const isExpanded = historyRow && historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        if (historyRow) historyRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            if (detailToggleBtn) {
                detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                detailToggleBtn.classList.remove('toggle-pressed');
            }
            openDetailIds.delete(paperId);
        }
        if (historyRow) historyRow.classList.add('expanded');
        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
        element.classList.add('toggle-pressed');
        openHistoryIds.add(paperId);
        updateUrlWithDetailState();
    }
}

document.addEventListener('DOMContentLoaded', function () {
    hideOfftopicCheckbox.addEventListener('change', applyLocalFilters);
    minPageCountInput.addEventListener('input', applyLocalFilters);
    minPageCountInput.addEventListener('change', applyLocalFilters);
    yearFromInput.addEventListener('input', applyLocalFilters);
    yearFromInput.addEventListener('change', applyLocalFilters);
    yearToInput.addEventListener('input', applyLocalFilters);
    yearToInput.addEventListener('change', applyLocalFilters);
});