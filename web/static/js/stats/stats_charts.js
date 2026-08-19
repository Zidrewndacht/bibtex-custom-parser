/**
 * Pure Chart.js rendering logic, helpers, and state-dependent chart utilities.
 */

window.chartRegistry = {};

function destroyChartInstance(name) {
    if (window.chartRegistry[name]) {
        window.chartRegistry[name].destroy();
        delete window.chartRegistry[name];
    }
}

function registerChartInstance(name, instance) {
    if (instance) window.chartRegistry[name] = instance;
    return instance;
}

function destroyAllCharts() {
    Object.values(window.chartRegistry).forEach(c => {
        if (c && typeof c.destroy === 'function') c.destroy();
    });
    window.chartRegistry = {};
}

function getChartInstance(name) {
    return window.chartRegistry[name];
}

function getChartDPR() {
    const nativeDPR = window.devicePixelRatio || 1;
    if (nativeDPR > 1.0 && nativeDPR < 2.0) {
        return nativeDPR * 2;
    }
    return nativeDPR;
}

function reorderDatasetsForStacking() {
    if (typeof isStacked === 'undefined' || !isStacked) return;
    
    Object.values(window.chartRegistry).forEach(chart => {
        if (chart.config.type === 'line') {
            const { datasets } = chart.data;
            const totals = datasets.map((ds, idx) => ({
                idx,
                total: ds.data.reduce((a, b) => a + b, 0)
            }));
            totals.sort((A, B) => A.total - B.total);
            chart.data.datasets = totals.map(t => datasets[t.idx]);
            chart.update();
        }
    });
}

function cumulativeLegendLabels(chart) {
    const defaults = Chart.defaults.plugins.legend.labels.generateLabels;
    const labels = defaults.call(this, chart);
    
    if (typeof isCumulative === 'undefined' || !isCumulative) return labels;
    
    labels.forEach(lbl => {
        const ds = chart.data.datasets[lbl.datasetIndex];
        const data = ds.data;
        const last = (Array.isArray(data) && data.length) ? data[data.length - 1] : 0;
        lbl.text = `${lbl.text}  (${last})`;
    });
    return labels;
}

function getBarLabelPosition(value, maxBarValue) {
    const halfMax = maxBarValue / 2;
    if (value < halfMax) {
        return { align: 'end', anchor: 'end' };
    } else {
        return { align: 'start', anchor: 'end' };
    }
}

function renderBarOrPieChart(ctx, chartData, chartLabel, chartType) {
    if (!ctx) return null;
    const isBar = chartType === 'bar';
    let datalabelsPluginConfig = {};
    let datalabelsPlugin = [];

    if (isBar && typeof ChartDataLabels !== 'undefined') {
        let maxBarValue = 0;
        if (chartData.datasets && chartData.datasets.length > 0) {
            chartData.datasets.forEach(dataset => {
                if (dataset.data && Array.isArray(dataset.data)) {
                    const datasetMax = Math.max(...dataset.data.map(v => Math.abs(v)));
                    if (datasetMax > maxBarValue) maxBarValue = datasetMax;
                }
            });
        }
        datalabelsPluginConfig = {
            datalabels: {
                formatter: value => value > 0 ? value : '',
                color: '#444',
                font: { size: 11, weight: '400' },
                anchor: function(context) { return getBarLabelPosition(context.dataset.data[context.dataIndex], maxBarValue).anchor; },
                align: function(context) { return getBarLabelPosition(context.dataset.data[context.dataIndex], maxBarValue).align; },
                offset: 4
            }
        };
        datalabelsPlugin = [ChartDataLabels];
    }

    if (!isBar && typeof ChartDataLabels !== 'undefined') {
        datalabelsPluginConfig = {
            datalabels: {
                color: '#444',
                font: ctx => {
                    const h = ctx.chart.width || 280;
                    return { size: Math.max(10, h * 0.035), weight: '300' };
                },
                anchor: 'end', align: 'start', offset: -2,
                formatter: (value, ctx) => {
                    const sum = ctx.dataset.data.reduce((a, b) => a + b, 0);
                    const pct = sum ? Math.round((value / sum) * 100) : 0;
                    return pct > 3 ? pct + '%' : '';
                }
            }
        };
        datalabelsPlugin = [ChartDataLabels];
    }

    const options = {
        type: chartType,
        data: chartData,
        options: {
            ...(isBar ? { indexAxis: 'y' } : { radius: '90%' }),
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { display: !isBar, position: 'top', labels: { usePointStyle: true, pointStyle: 'circle' } },
                title: { display: false },
                tooltip: { callbacks: { label: ctx => `${ctx.label}: ${ctx.raw}` } },
                ...datalabelsPluginConfig
            },
            scales: { ...(isBar ? { x: { beginAtZero: true, ticks: { precision: 0 } } } : {}) }
        },
        plugins: datalabelsPlugin
    };
    return new Chart(ctx, options);
}

function renderHistogram(ctx, chartData, title) {
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: { legend: { display: false }, title: { display: false, text: title } },
            scales: {
                x: { title: { display: false, text: title.split(' ')[0] }, ticks: { precision: 0 } },
                y: { title: { display: true, text: 'Frequency' }, beginAtZero: true, ticks: { precision: 0 } }
            }
        }
    });
}

function renderGenericLineChart(ctx, chartData, title) {
    if (!ctx) return null;
    if (!chartData || !chartData.datasets || chartData.datasets.length === 0) {
        return new Chart(ctx, {
            type: 'line', data: { labels: [], datasets: [] },
            options: { responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(), plugins: { legend: { display: false }, title: { display: true, text: `${title} (No Data)` } } }
        });
    }

    const stacked = (typeof isStacked !== 'undefined') ? isStacked : false;
    return new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: {
            responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
            plugins: {
                legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } },
                title: { display: false, text: title },
                tooltip: { callbacks: { label: function (context) { return `${context.dataset.label}: ${context.raw}`; } } }
            },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 }, stacked: stacked },
                x: { ticks: { precision: 0 }, stacked: stacked }
            }
        }
    });
}