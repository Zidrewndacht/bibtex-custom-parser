/**
 * For GitHub Pages static demo:
 */
document.addEventListener('DOMContentLoaded', function () {
    // --- Disable Server-Side Buttons ---
    // List of button IDs that require server interaction
    const serverButtonIds = [
        'import-bibtex',
        'classify-remaining-btn',
        'classify-all-btn',
        'verify-remaining-btn',
        'verify-all-btn'
    ];

    serverButtonIds.forEach(id => {
        const button = document.getElementById(id);
        if (button) {
            button.disabled = true;
        }
    });

    document.querySelectorAll('.classify-btn').forEach(button => { button.disabled = true; });
    document.querySelectorAll('.verify-btn').forEach(button => { button.disabled = true; });
    document.querySelectorAll('.save-btn').forEach(button => { button.disabled = true; });
    document.querySelectorAll('form input.editable, form textarea.editable').forEach(input => { input.disabled = true;  });
})