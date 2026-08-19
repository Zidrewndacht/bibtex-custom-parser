// static/js/comms_batch.js
/**
 * Batch LLM operations and modal management.
 * Depends on: nothing from other comms files (fully self-contained).
 */

// --- Batch State ---
let isBatchRunning = false; // Simple flag to prevent multiple simultaneous batches

// --- Modal References ---
const batchModal = document.getElementById("batchModal");
const importModal = document.getElementById("importModal");
const exportModal = document.getElementById("exportModal");

// --- Toolbar Button References ---
const parçaToolsBtn = document.getElementById('parça-tools-btn');
const classifyAllBtn = document.getElementById('classify-all-btn');
const classifyRemainingBtn = document.getElementById('classify-remaining-btn');
const classifyConsensusBtn = document.getElementById('classify-consensus-btn');
const verifyAllBtn = document.getElementById('verify-all-btn');
const verifyRemainingBtn = document.getElementById('verify-remaining-btn');
const batchStatusMessage = document.getElementById('batch-status-message');
const backupStatusMessage = document.getElementById('backup-status-message');
const importActionsBtn = document.getElementById('import-btn');
const exportActionsBtn = document.getElementById('export-btn');

// --- Modal Show/Hide ---
function showBatchActions() {
    batchModal.offsetHeight;
    batchModal.classList.add('modal-active');
}
function closeBatchModal() { batchModal.classList.remove('modal-active'); }

function showImportActions() {
    importModal.offsetHeight;
    importModal.classList.add('modal-active');
}
function closeImportModal() { importModal.classList.remove('modal-active'); }

function showExportActions() {
    exportModal.offsetHeight;
    exportModal.classList.add('modal-active');
    backupStatusMessage.innerHTML = 'Backups include the database, original and annotated PDFs, HTML export and a XLSX spreadsheet.<br><br>Restoring from a backup overwrites all existing data!';
    backupStatusMessage.style.color = '';
}
function closeExporthModal() { exportModal.classList.remove('modal-active'); }

// --- Batch Action Buttons ---
// Define all batch buttons so they can be managed together
const allBatchButtons = [
    classifyAllBtn,
    classifyRemainingBtn,
    classifyConsensusBtn,
    verifyAllBtn,
    verifyRemainingBtn
];

function runBatchAction(mode, actionType) {
    if (isBatchRunning) {
        alert(`A ${actionType} batch is already running.`);
        return;
    }

    let modeDescription = mode;
    if (mode === 'all') {
        modeDescription = 'ALL';
    } else if (mode === 'remaining') {
        modeDescription = 'remaining';
    } else if (mode === 'consensus') {
        modeDescription = 'misclassifications until consensus (reclassify + verify loop)';
    }

    if (!confirm(`Are you sure you want to ${actionType} ${modeDescription} papers? This might take a while.`)) {
        return;
    }

    isBatchRunning = true;

    // Disable ALL batch buttons when any batch action starts
    allBatchButtons.forEach(btn => {
        if (btn) btn.disabled = true; // Check if btn exists before disabling
    });

    if (batchStatusMessage) batchStatusMessage.textContent = `Starting ${actionType} (${mode})...`;

    const endpoint = actionType === 'classify' ? '/classify' : '/verify';

    fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mode: mode }) // Send the mode (including 'consensus')
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
            batchStatusMessage.innerHTML = data.message;
            // Optionally, you could add logic here to re-enable buttons after a certain time
            // or based on some other signal if the process is known to have finished.
        })
        .catch(error => {
            console.error(`Error initiating batch ${actionType} (${mode}):`, error);
            alert(`Failed to start ${actionType} (${mode}): ${error.message}`);
            isBatchRunning = false;
            // Re-enable ALL batch buttons on error
            allBatchButtons.forEach(btn => {
                if (btn) btn.disabled = false; // Check if btn exists before enabling
            });
            if (batchStatusMessage) batchStatusMessage.innerHTML = '';
        });
}

// ============================================================================
// DOMContentLoaded — Batch / Modal wiring
// ============================================================================
document.addEventListener('DOMContentLoaded', function () {
    parçaToolsBtn.addEventListener('click', showBatchActions);
    classifyAllBtn.addEventListener('click', () => runBatchAction('all', 'classify'));
    classifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'classify'));
    classifyConsensusBtn.addEventListener('click', () => runBatchAction('consensus', 'classify'));
    verifyAllBtn.addEventListener('click', () => runBatchAction('all', 'verify'));
    verifyRemainingBtn.addEventListener('click', () => runBatchAction('remaining', 'verify'));

    importActionsBtn.addEventListener('click', showImportActions);
    exportActionsBtn.addEventListener('click', showExportActions);
});