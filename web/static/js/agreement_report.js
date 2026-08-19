// agreement_report.js
// Client-side logic for the whole-dataset 3-Run Agreement Report (/agreement_report).
// Charts, LaTeX copy buttons, and deep links back into the main window.

document.addEventListener('DOMContentLoaded', function () {
    const D = window.REPORT_DATA || { strata: {}, relevance_bins: [] };

    if (typeof Chart !== 'undefined') {
        Chart.defaults.font = { size: 12.5, family: 'Arial Narrow', weight: '300' };
    }

    // ------------------------------------------------------------------
    // LaTeX copy buttons (same pattern as stats_latex.js)
    // ------------------------------------------------------------------
    document.querySelectorAll('.latex-copy-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            const key = this.dataset.latexKey;
            const latex = (window.LATEX_TABLES || {})[key];
            if (!latex) return;
            const originalText = this.innerHTML;
            this.innerHTML = 'Copied!';
            navigator.clipboard.writeText(latex).catch(() => alert('Failed to copy LaTeX.'));
            setTimeout(() => { this.innerHTML = originalText; }, 2000);
        });
    });
        
    // Collapsible sections: toggle on header click. Only applied to table/text
    // sections (marked .collapsible) — chart sections stay expanded so Chart.js
    // never has to size itself inside a hidden container.
    document.querySelectorAll('.report-section.collapsible > h3').forEach(function (h3) {
        h3.addEventListener('click', function (e) {
            // Don't collapse when clicking the LaTeX copy button.
            if (e.target.closest('.latex-copy-btn')) return;
            this.closest('.report-section').classList.toggle('collapsed');
        });
    });
    setupFieldTableSorting();
    setupTitlebarControls();
    if (typeof Chart === 'undefined') return;

    renderOverviewChart(D);
    renderRawDistributionChart(D);
    renderContradictionChart(D);
    renderRelevanceChart(D);
    buildRelevanceInsight(D);
    renderProgressChart();
});

// ======================================================================
// Helpers
// ======================================================================

// Client-side sorting for the per-category "Fields by Agreement" tables.
// Rows carry data-perfect / data-contradiction; both sorts are descending.
function setupFieldTableSorting() {
    document.querySelectorAll('#agreement-report table.field-table').forEach(function (table) {
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        table.querySelectorAll('th.sortable-col').forEach(function (th) {
            th.addEventListener('click', function () {
                const key = this.dataset.sortKey;
                const rows = Array.from(tbody.querySelectorAll('tr'));
                rows.sort(function (a, b) {
                    const av = parseFloat(a.dataset[key]) || 0;
                    const bv = parseFloat(b.dataset[key]) || 0;
                    return bv - av; // descending
                });
                rows.forEach(function (r) { tbody.appendChild(r); });
                table.querySelectorAll('th.sortable-col').forEach(function (h) {
                    h.classList.remove('sorted');
                });
                this.classList.add('sorted');
            });
        });
    });
}

function fmtCount(v) {
    return Number(v || 0).toLocaleString();
}

function renderProgressChart() {
    const progress = window.CONSENSUS_PROGRESS;
    if (!progress || !progress.events || progress.events.length === 0) return;
    
    const ctx = document.getElementById('progressChart');
    if (!ctx) return;
    
    const points = progress.events.map(e => ({ x: e.elapsed, y: e.remaining }));
    
    new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            datasets: [{
                label: 'Remaining Papers',
                data: points,
                borderColor: '#1f77b4',
                backgroundColor: 'rgba(31, 119, 180, 0.1)',
                borderWidth: 2.5,
                stepped: 'after', 
                pointRadius: 0,
                fill: true
            }]
        },
        options: {
            responsive: true, 
            maintainAspectRatio: false, 
            devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => `Elapsed: ${Number(items[0].parsed.x).toFixed(1)} min`,
                        label: (item) => `Remaining: ${item.parsed.y} papers`
                    }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Elapsed Time (minutes)' },
                    ticks: { 
                        callback: v => v + 'm',
                        autoSkip: true,
                        maxTicksLimit: 10
                    }
                },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Remaining Papers' },
                    ticks: { precision: 0 }
                }
            }
        }
    });
}

// Titlebar controls: collapse/expand all, copy all LaTeX, refresh.
function setupTitlebarControls() {
    // Collapse / expand all collapsible sections
    const collapseBtn = document.getElementById('collapse-all-btn');
    if (collapseBtn) {
        collapseBtn.addEventListener('click', function () {
            const sections = document.querySelectorAll('#agreement-report .report-section.collapsible');
            const anyExpanded = Array.from(sections).some(function (s) {
                return !s.classList.contains('collapsed');
            });
            sections.forEach(function (s) {
                s.classList.toggle('collapsed', anyExpanded);
            });
            this.textContent = anyExpanded ? 'Expand all' : 'Collapse all';
        });
    }

    // Copy ALL LaTeX tables at once (same strings the per-section buttons use)
    const copyBtn = document.getElementById('copy-all-latex-btn');
    if (copyBtn) {
        copyBtn.addEventListener('click', function () {
            const tables = window.LATEX_TABLES || {};
            const all = Object.keys(tables).map(function (k) {
                return '% ===== ' + k + ' =====\n' + tables[k];
            }).join('\n');
            if (!all) return;
            const originalText = this.textContent;
            this.textContent = 'Copied!';
            navigator.clipboard.writeText(all).catch(function () { alert('Failed to copy LaTeX.'); });
            setTimeout(function () { copyBtn.textContent = originalText; }, 2000);
        });
    }
}

// Mirrors getChartDPR() from stats_charts.js: explicit devicePixelRatio
// (doubled for fractional DPR between 1 and 2) so charts render sharp on hiDPI.
function getChartDPR() {
    const nativeDPR = window.devicePixelRatio || 1;
    if (nativeDPR > 1.0 && nativeDPR < 2.0) {
        return nativeDPR * 2;
    }
    return nativeDPR;
}

function stratumLabels(D) {
    const s = D.strata;
    const label = (key, name) => `${name} (${fmtCount(s[key].n_observations)} obs)`;
    return [
        label('on_topic_only', 'On-topic'),
        label('off_topic_only', 'Off-topic'),
        label('all_papers', 'All papers')
    ];
}

// ======================================================================
// Charts
// ======================================================================

function renderOverviewChart(D) {
    const ctx = document.getElementById('overviewChart');
    if (!ctx) return;
    const s = D.strata;
    const keys = ['on_topic_only', 'off_topic_only', 'all_papers'];
    const pick = (suffix) => keys.map(k => s[k][suffix]);

    new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: stratumLabels(D),
            datasets: [
                {
                    label: 'Perfect',
                    data: pick('perfect_pct'),
                    backgroundColor: 'hsla(96, 87%, 37%, 0.95)',
                    counts: pick('perfect'), cis: keys.map(k => s[k].perfect_ci)
                },
                {
                    label: 'Biased Certain (YYU/NNU)',
                    data: pick('uncertain_biased_certain_pct'),
                    backgroundColor: 'hsla(242, 69%, 56%, 0.95)',
                    counts: pick('uncertain_biased_certain'), cis: null
                },
                {
                    label: 'Biased Uncertain (YUU/NUU)',
                    data: pick('uncertain_biased_uncertain_pct'),
                    backgroundColor: 'hsla(42, 100%, 55%, 0.90)',
                    counts: pick('uncertain_biased_uncertain'), cis: null
                },
                {
                    label: 'Contradiction',
                    data: pick('contradiction_pct'),
                    backgroundColor: 'hsla(347, 60%, 60%, 0.95)',
                    counts: pick('contradiction'), cis: keys.map(k => s[k].contradiction_ci)
                }
            ]
        },
        options: {
            indexAxis: 'y',
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle' } },
                title: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => {
                            const ds = c.dataset;
                            let txt = `${ds.label}: ${Number(c.raw).toFixed(2)}% (${fmtCount(ds.counts[c.dataIndex])})`;
                            if (ds.cis) {
                                const ci = ds.cis[c.dataIndex];
                                txt += ` [95% CI ${Number(ci[0]).toFixed(2)}–${Number(ci[1]).toFixed(2)}%]`;
                            }
                            return txt;
                        }
                    }
                }
            },
            scales: {
                x: { stacked: true, max: 100, ticks: { callback: v => v + '%' } },
                y: { stacked: true }
            }
        }
    });
}

function renderRawDistributionChart(D) {
    const ctx = document.getElementById('rawDistChart');
    if (!ctx) return;
    const st = D.strata.on_topic_only;
    const total = st.raw_total || 0;

    new Chart(ctx.getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: ['Yes', 'No', 'Unknown'],
            datasets: [{
                label: 'Raw responses (on-topic)',
                data: [st.raw_yes, st.raw_no, st.raw_unknown],
                backgroundColor: [
                    'hsla(96, 87%, 37%, 0.95)',   // yes-leaning
                    'hsla(347, 60%, 50%, 0.95)',  // no-leaning
                    'hsla(42, 100%, 55%, 0.90)'   // chaotic
                ],
                borderColor: '#333', borderWidth: 1, hoverOffset: 4
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle' } },
                title: { display: true, text: 'Raw Response Distribution (On-Topic)' },
                tooltip: {
                    callbacks: {
                        label: (c) => {
                            const pct = total ? (c.raw / total * 100).toFixed(2) : '0.00';
                            return `${c.label}: ${fmtCount(c.raw)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

function renderContradictionChart(D) {
    // One chart per stratum; each shows the three contradiction (bias) types.
    const configs = [
        { key: 'on_topic_only', canvasId: 'contradictionChartOnTopic', title: 'On-topic' },
        { key: 'off_topic_only', canvasId: 'contradictionChartOffTopic', title: 'Off-topic' },
        { key: 'all_papers', canvasId: 'contradictionChartAll', title: 'All papers' }
    ];
    const labels = ['Biased Yes (YYN)', 'Biased No (YNN)', 'Chaotic (YNU)'];
    const typeKeys = ['contradiction_biased_yes', 'contradiction_biased_no', 'contradiction_chaotic'];
    const colors = [
        'hsla(96, 87%, 37%, 0.95)',   // yes-leaning
        'hsla(347, 60%, 50%, 0.95)',  // no-leaning
        'hsla(42, 100%, 55%, 0.90)'   // chaotic
    ];

    configs.forEach(function (cfg) {
        const el = document.getElementById(cfg.canvasId);
        if (!el) return;
        const s = D.strata[cfg.key];
        new Chart(el.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: cfg.title,
                    data: typeKeys.map(t => s[t + '_pct']),
                    counts: typeKeys.map(t => s[t]),
                    backgroundColor: colors
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: `${cfg.title} (${fmtCount(s.n_observations)} obs)` },
                    tooltip: {
                        callbacks: {
                            label: (c) => ` ${Number(c.raw).toFixed(2)}% (${fmtCount(c.dataset.counts[c.dataIndex])})`
                        }
                    }
                },
                scales: {
                    x: { beginAtZero: true, ticks: { callback: v => v + '%' } }
                }
            }
        });
    });
}

function renderRelevanceChart(D) {
    const ctx = document.getElementById('relevanceChart');
    if (!ctx) return;
    const bins = D.relevance_bins || [];

    new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: bins.map(b => b.label),
            datasets: [
                {
                    label: 'Perfect',
                    data: bins.map(b => b.perfect_pct),
                    counts: bins.map(b => b.perfect),
                    backgroundColor: 'hsla(96, 87%, 37%, 0.95)'
                },
                {
                    label: 'Uncertain',
                    data: bins.map(b => b.uncertain_pct),
                    counts: bins.map(b => b.uncertain),
                    backgroundColor: 'hsla(42, 100%, 55%, 0.90)'
                },
                {
                    label: 'Contradiction',
                    data: bins.map(b => b.contradiction_pct),
                    counts: bins.map(b => b.contradiction),
                    backgroundColor: 'hsla(347, 60%, 60%, 0.95)'
                }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle' } },
                tooltip: {
                    callbacks: {
                        label: (c) => {
                            const bin = bins[c.dataIndex];
                            return `${c.dataset.label}: ${Number(c.raw).toFixed(2)}% (${fmtCount(c.dataset.counts[c.dataIndex])}; n=${fmtCount(bin.n_observations)} obs)`;
                        }
                    }
                }
            },
            scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + '%' } }
            }
        }
    });
}

// Auto-evaluates the heuristics from the CLI interpretation guide.
function buildRelevanceInsight(D) {
    const el = document.getElementById('relevance-insight');
    if (!el) return;

    const bins = (D.relevance_bins || []).filter(b => b.n_observations > 0);
    if (bins.length < 2) {
        el.textContent = 'ℹ️ Not enough data across relevance bins to evaluate correlation.';
        return;
    }

    const lowest = bins[0];              // lowest relevance bin with data
    const highest = bins[bins.length - 1]; // highest relevance bin with data
    const contraDelta = lowest.contradiction_pct - highest.contradiction_pct;
    const unknownDelta = lowest.raw_unknown_pct - highest.raw_unknown_pct;

    let msg;
    if (contraDelta > 1) {
        msg = '⚠️ Contradiction rate rises as relevance drops — the prompt may benefit from relevance-aware tuning.';
    } else if (contraDelta < -1) {
        msg = '✅ Contradiction rate does not increase for lower-relevance papers.';
    } else {
        msg = 'ℹ️ Contradiction rate is roughly flat across relevance bins — any issues are prompt-wide rather than relevance-specific.';
    }
    if (unknownDelta > 2) {
        msg += ' Unknown responses increase as relevance drops — the model correctly hedges on ambiguous papers. ✓';
    }
    el.textContent = msg;
}