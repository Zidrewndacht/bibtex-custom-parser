// static/js/comms_rendering.js
/**
 * Display layer: constants, pure render helpers, and DOM cell update functions.
 * No fetch calls. No event listeners.
 * Depends on: APP_CONFIG, getJsonPath (from filtering.js)
 */

// --- Status Cycling Logic ---
const STATUS_CYCLE = {
    '❔': { next: '✔️', value: 'true' },
    '✔️': { next: '❌', value: 'false' },
    '❌': { next: '❔', value: 'unknown' }
};

const VERIFIED_BY_CYCLE = {
    '👤': { next: '❔', value: 'unknown' },
    '❔': { next: '👤', value: 'user' },
    // If user sees Computer (🖥️), next is User:
    // We assume the user wants to override/review it, not set it to computer.
    '🖥️': { next: '👤', value: 'user' }
};

/**
 * Renders a status value (true, false, null, etc.) as an emoji.
 * Replicates Python's render_status logic on the client.
 * @param {*} value - The value to render.
 * @returns {string} The emoji string.
 */
function renderStatus(value) {
    if (value === 1 || value === true) {
        return '✔️';
    } else if (value === 0 || value === false) {
        return '❌';
    } else {
        return '❔';
    }
}

/**
 * Renders a verified_by value (user, model_name, null) as an emoji with tooltip.
 * Replicates Python's render_verified_by logic on the client.
 * @param {*} value - The raw database value.
 * @returns {string} The HTML string for the emoji span.
 */
function renderVerifiedBy(value) {
    if (value === 'user') {
        return '<span title="User">👤</span>';
    } else if (value === null || value === undefined || value === '') {
        return '<span title="Unverified">❔</span>';
    } else {
        // Escape the model name for HTML attribute safety (basic escaping)
        let escapedModelName = String(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `<span title="${escapedModelName}">🖥️</span>`;
    }
}

// --- Helper function to render changed_by value as emoji (Client-Side) ---
function renderChangedBy(value) {
    // This replicates the logic from Python's render_changed_by function
    if (value === 'user') {
        return '<span title="User">👤</span>';
    } else if (value === null || value === undefined || value === '') {
        return '<span title="Unknown">❔</span>';
    } else {
        // Escape the model name for HTML attribute safety (basic escaping)
        // Using a simple replace for quotes. For more robust escaping, consider a library.
        let escapedModelName = String(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `<span title="${escapedModelName}">🖥️</span>`;
    }
}

/**
 * Formats a relevance float to 1 decimal place, stripping trailing zeros.
 * Matches the Jinja template logic: (val|round(1)|string).rstrip('0').rstrip('.')
 */
function formatRelevance(val) {
    if (val === null || val === undefined || val === '') return '';
    let num = parseFloat(val);
    if (isNaN(num)) return '';
    let rounded = Math.round(num * 10) / 10;
    let str = rounded.toFixed(1);
    return str.replace(/\.?0+$/, '');
}

/**
 * Centralized function to clear stuck CSS classes, apply new certainty states,
 * update emojis, and format relevance.
 * FIX: Swapped order so emojis are populated BEFORE conflict overlays are applied,
 * preventing both from being visible simultaneously.
 */
function applyCertaintyAndUpdates(row, data) {
    // 1. CRITICAL: Clear ALL certainty/conflict states from all inferred cells first.
    const inferredCells = row.querySelectorAll('[data-field]');
    inferredCells.forEach(c => {
        c.classList.remove('certainty-60', 'certainty-80', 'certainty-conflict', 'certainty-solid');
        const conflictWarning = c.querySelector('.conflict-warning');
        if (conflictWarning) conflictWarning.remove();
        const emojiSpan = c.querySelector('.emoji-content');
        if (emojiSpan) emojiSpan.style.display = '';
    });

    // 2. Update Inferred Cells (emojis) FIRST
    // This ensures every cell has an .emoji-content span with the latest value.
    if (typeof updateInferredCells === 'function') {
        updateInferredCells(row, data.classification);
    }

    // 3. Apply new certainty classes and handle conflicts SECOND
    if (data.main_certainty) {
        for (const [fieldName, certainty] of Object.entries(data.main_certainty)) {
            const c = row.querySelector(`[data-field="${fieldName}"]`);
            if (c && certainty) {
                c.classList.add(`certainty-${certainty}`);
                const emojiSpan = c.querySelector('.emoji-content');
                const conflictWarning = c.querySelector('.conflict-warning');
                if (certainty === 'conflict') {
                    // Hide the emoji (which now definitely exists thanks to step 2)
                    if (emojiSpan) emojiSpan.style.display = 'none';
                    // Add warning if missing
                    if (!conflictWarning) {
                        c.insertAdjacentHTML('beforeend', '<span class="conflict-warning">⚠️</span>');
                    }
                } else {
                    // Ensure emoji is visible if not a conflict
                    if (emojiSpan) emojiSpan.style.display = '';
                    // Remove conflict warning if it exists but certainty is no longer conflict
                    if (conflictWarning) conflictWarning.remove();
                }
            }
        }
    }

    // 4. Update Relevance with proper formatting
    const relevanceCell = row.querySelector('[data-field="relevance"]');
    if (relevanceCell && data.classification && data.classification.relevance !== undefined) {
        relevanceCell.textContent = formatRelevance(data.classification.relevance);
    }
}

/**
 * Helper to update a cell's status symbol based on boolean/null value.
 * CRITICAL FIX: Never use cell.textContent directly, as it destroys inner spans (like conflict warnings).
 */
function updateRowCell(row, selector, value) {
    const cell = row.querySelector(selector);
    if (cell) {
        const emojiSpan = cell.querySelector('.emoji-content');
        if (emojiSpan) {
            emojiSpan.textContent = renderStatus(value);
        } else {
            // If the span doesn't exist, create it instead of wiping the cell's innerHTML
            const newSpan = document.createElement('span');
            newSpan.className = 'emoji-content';
            newSpan.textContent = renderStatus(value);
            cell.appendChild(newSpan);
        }
    }
}

function updateInferredCells(row, classification) {
    if (!classification) return;
    for (const group of APP_CONFIG.groups) {
        if (group.filter_type === 'tri_state') {
            updateRowCell(row, `[data-field="${group.json_path}"]`, getJsonPath(classification, group.json_path));
        } else if (group.filter_type === 'inclusion' || group.filter_type === 'none') {
            for (const field_def of group.fields) {
                const path = `${group.json_path}.${field_def.key}`;
                if (field_def.render_type === 'text_presence') {
                    const val = getJsonPath(classification, path);
                    const cell = row.querySelector(`[data-field="${path}"]`);
                    if (cell) {
                        const emojiSpan = cell.querySelector('.emoji-content');
                        if (emojiSpan) emojiSpan.textContent = (val && String(val).trim()) ? '✔️' : '❌';
                    }
                } else {
                    updateRowCell(row, `[data-field="${path}"]`, getJsonPath(classification, path));
                }
            }
        }
    }
}