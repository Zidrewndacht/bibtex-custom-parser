// focus_paper.js
// Handles /?focus_paper=<id> deep links (opened from the Agreement Report's outlier
// links in a new tab). The URL already carries narrowly-scoped server-side filters
// (the paper's year, hide_offtopic=0, min_page_count=0) plus the paper ID as
// search_query, so the new tab renders fast and shows essentially only the target.
// This script just makes sure the ID search is applied, then reveals the row,
// highlights it briefly, and expands its history.

(function () {
    'use strict';

    function findRow(paperId) {
        if (typeof CSS !== 'undefined' && CSS.escape) {
            return document.querySelector('#papersTable tbody tr[data-paper-id="' + CSS.escape(paperId) + '"]');
        }
        return Array.prototype.slice
            .call(document.querySelectorAll('#papersTable tbody tr[data-paper-id]'))
            .find(function (r) { return r.getAttribute('data-paper-id') === paperId; }) || null;
    }

    function applyFiltersSafe() {
        if (typeof applyLocalFilters === 'function') {
            try { applyLocalFilters(); } catch (e) { /* ignore */ }
        }
    }

    function highlightAndOpen(row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('focus-highlight');
        setTimeout(function () { row.classList.remove('focus-highlight'); }, 4000);

        // Expand the history row unless already expanded.
        // Row structure: data row -> detail-row -> history-row.
        const detailRow = row.nextElementSibling;
        const historyRow = detailRow ? detailRow.nextElementSibling : null;
        const historyExpanded = historyRow && historyRow.classList.contains('expanded');
        const historyBtn = row.querySelector('.history-btn');
        if (historyBtn && !historyExpanded) {
            historyBtn.click(); // invokes onclick="toggleHistory(this)" — same path as a user click
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!window.FOCUS_PAPER_ID) return;
        const paperId = String(window.FOCUS_PAPER_ID);

        setTimeout(function () {
            // Ensure the ID search is active (index() prefills the input from search_query).
            const searchEl = document.getElementById('search-input');
            if (searchEl && searchEl.value.trim() !== paperId) {
                searchEl.value = paperId;
            }
            applyFiltersSafe();

            let row = findRow(paperId);
            if (!row && searchEl) {
                // Fallback: if the search doesn't match IDs in this setup, drop the
                // search and rely on the year-filtered table alone.
                searchEl.value = '';
                applyFiltersSafe();
                row = findRow(paperId);
            }
            if (!row) {
                console.warn('[focus_paper] Paper not found: ' + paperId);
                alert('Paper "' + paperId + '" was not found in the database.');
                return;
            }
            highlightAndOpen(row);
        }, 150);
    });
})();