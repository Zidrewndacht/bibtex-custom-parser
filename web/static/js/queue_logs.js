// queue_logs.js
// Event-oriented queue log viewer.
// The server only delivers raw JSONL text; parsing/rendering happens here.

(function () {
    "use strict";

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    function init() {
        const root = document.getElementById("queue-logs-page");
        if (!root) return;

        const els = {
            root,
            refreshBtn: document.getElementById("refresh-btn"),
            autoRefresh: document.getElementById("auto-refresh"),
            tail: document.getElementById("tail-select"),
            limit: document.getElementById("limit-select"),
            search: document.getElementById("log-search"),
            source: document.getElementById("log-source"),
            count: document.getElementById("log-count"),
            download: document.getElementById("download-link"),
            tabs: document.getElementById("log-view-tabs"),
            status: document.getElementById("log-status"),
            tableWrapper: document.getElementById("log-table-wrapper"),
            table: document.getElementById("log-table"),
            head: document.getElementById("log-table-head"),
            tbody: document.querySelector("#log-table tbody"),
        };

        if (!els.tabs || !els.head || !els.tbody) return;

        const VIEWS = [
            {
                id: "queue_status",
                label: "Queue",
                file: "dispatcher.log",
                event: "queue_status",
                columns: [
                    "Time",
                    "Queue",
                    "In flight",
                    "Classify",
                    "Verify",
                    "Reclassify",
                    "Mode",
                ],
                row: queueRow,
            },
            {
                id: "dispatch",
                label: "Dispatch",
                file: "dispatcher.log",
                event: "dispatch",
                columns: [
                    "Time",
                    "Task",
                    "Type",
                    "Paper",
                    "Set",
                ],
                row: dispatchRow,
            },
            {
                id: "complete",
                label: "Complete",
                file: "tasks.log",
                event: "complete",
                columns: [
                    "Time",
                    "Task",
                    "Type",
                    "Paper",
                    "Set",
                    "Model",
                    "Success",
                    "Error",
                ],
                row: completeRow,
            },
            {
                id: "request",
                label: "Requests",
                file: "requests.log",
                event: "request",
                columns: [
                    "Time",
                    "Endpoint",
                    "Client",
                    "Mode",
                    "Paper",
                ],
                row: requestRow,
            },
            {
                id: "error",
                label: "Errors",
                file: "errors.log",
                event: "error",
                columns: [
                    "Time",
                    "Context",
                    "Error",
                    "Task",
                    "Paper",
                    "Set",
                ],
                row: errorRow,
            },
        ];

        const state = {
            viewId: VIEWS[0].id,
            entries: [],
            filtered: [],
            loading: false,
            requestId: 0,
            timer: null,
            searchTimer: null,
            emptyMessage: "",
            limits: {
                classify: 0,
                verify: 0,
                reclassify: 0,
                mixed: 0,
            },
        };

        // ------------------------------------------------------------------
        // Helpers
        // ------------------------------------------------------------------

        function barCell(value, denominator, category, denominatorLabel, options) {
            const opts = options || {};

            const count = Number(value ?? 0);
            const max = Number(denominator ?? 0);

            const hasDenominator = max > 0;
            const pct = hasDenominator
                ? Math.min(100, (count / max) * 100)
                : 0;

            const full = hasDenominator && count >= max;
            const disabled = opts.disabled || !hasDenominator;

            let title;

            if (hasDenominator) {
                title = `${count} / ${max}${denominatorLabel ? ` (${denominatorLabel})` : ""}`;
            } else {
                title = opts.title || `${count}`;
            }

            return `
                <div class="queue-bar-wrap${disabled ? " is-disabled" : ""}" title="${esc(title)}">
                    <div class="queue-bar-track">
                        <div class="queue-bar-fill fill-${category}${full ? " is-full" : ""}"
                            style="width:${pct}%"></div>
                    </div>
                    <span class="queue-bar-value">${esc(count)}</span>
                </div>
            `;
        }

        function paperLink(paperId) {
            if (paperId === null || paperId === undefined || paperId === "") {
                return "";
            }

            const url = `/?focus_paper=${encodeURIComponent(paperId)}`;

            return `
                <a class="paper-link"
                href="${esc(url)}"
                target="_blank"
                rel="noopener"
                title="Open paper ${esc(paperId)} in the main UI">
                    ${esc(paperId)}
                </a>
            `;
        }

        function esc(value) {
            return String(value ?? "").replace(/[&<>"']/g, function (c) {
                return {
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;",
                }[c];
            });
        }

        function currentView() {
            return viewById(state.viewId) || VIEWS[0];
        }

        function parseQueueMode(mode) {
            const raw = String(mode || "");

            const limitMatch = raw.match(/limit=(\d+)/);
            const thresholdMatch = raw.match(/min_threshold=(\d+)/);

            const limit = limitMatch ? parseInt(limitMatch[1], 10) : 0;
            const threshold = thresholdMatch ? parseInt(thresholdMatch[1], 10) : 0;

            if (raw.startsWith("HOMOGENEOUS_CLASSIFY")) {
                return { type: "classify", limit, threshold };
            }

            if (raw.startsWith("HOMOGENEOUS_VERIFY")) {
                return { type: "verify", limit, threshold };
            }

            if (raw.startsWith("HOMOGENEOUS_RECLASSIFY")) {
                return { type: "reclassify", limit, threshold };
            }

            if (raw.startsWith("MIXED")) {
                return { type: "mixed", limit, threshold };
            }

            return { type: null, limit, threshold };
        }

        function viewById(id) {
            return VIEWS.find(function (v) {
                return v.id === id;
            });
        }

        function setStatus(message) {
            els.status.textContent = message || "";
        }

        function isTrue(value) {
            return value === true || value === 1 || value === "true";
        }

        function isFalse(value) {
            return value === false || value === 0 || value === "false";
        }

        function successCell(value) {
            if (isTrue(value)) return "✔️";
            if (isFalse(value)) return "❌";
            if (value === null || value === undefined || value === "") return "";
            return esc(String(value));
        }

        function formatTimestamp(obj) {
            if (!obj || !obj._ts) return "";
            return new Date(obj._ts).toLocaleString();
        }

        function parseTaskId(taskId) {
            const match = String(taskId || "").match(/^(.+)_set(\d+)_/);
            if (!match) return {};

            return {
                paper_id: match[1],
                set_num: match[2],
            };
        }

        function taskTypePill(type) {
            if (!type) return "";

            let cls = "pill-other";

            if (type === "classify") cls = "pill-classify";
            else if (type === "verify") cls = "pill-verify";
            else if (type === "reclassify") cls = "pill-reclassify";

            return `<span class="log-pill ${cls}">${esc(type)}</span>`;
        }

        function endpointPill(endpoint) {
            if (!endpoint) return "";

            let cls = "pill-other";

            if (endpoint.includes("classify")) cls = "pill-classify";
            else if (endpoint.includes("verify")) cls = "pill-verify";
            else if (endpoint.includes("consensus")) cls = "pill-reclassify";

            return `<span class="log-pill ${cls}">${esc(endpoint)}</span>`;
        }

        function modePill(mode) {
            const raw = String(mode || "");
            if (!raw) return "";

            const key = raw.split(" ")[0];
            const detailStart = raw.indexOf("(");
            const detail = detailStart >= 0 ? raw.slice(detailStart) : "";

            let cls = "pill-status";
            let label = key;

            if (key === "HOMOGENEOUS_CLASSIFY") {
                cls = "pill-classify";
                label = "CLASSIFY";
            } else if (key === "HOMOGENEOUS_VERIFY") {
                cls = "pill-verify";
                label = "VERIFY";
            } else if (key === "HOMOGENEOUS_RECLASSIFY") {
                cls = "pill-reclassify";
                label = "RECLASSIFY";
            } else if (key === "MIXED") {
                cls = "pill-status";
                label = "MIXED";
            }

            return `
                <span class="log-pill ${cls}" title="${esc(raw)}">${esc(label)}</span>
                ${detail ? `<span class="mode-detail">${esc(detail)}</span>` : ""}
            `;
        }

        // ------------------------------------------------------------------
        // Row renderers
        // ------------------------------------------------------------------

        function queueRow(entry) {
            const obj = entry.obj || {};
            const modeInfo = parseQueueMode(obj.mode);

            let rowClass = "";

            if (modeInfo.type === "classify") rowClass = "log-row-classify";
            else if (modeInfo.type === "verify") rowClass = "log-row-verify";
            else if (modeInfo.type === "reclassify") rowClass = "log-row-reclassify";
            else if (modeInfo.type === "mixed") rowClass = "log-row-mixed";

            const denominator = modeInfo.type === "mixed"
                ? modeInfo.threshold
                : modeInfo.limit;

            const denominatorLabel = modeInfo.type === "mixed"
                ? "mixed threshold"
                : "row limit";

            return `
                <tr class="${rowClass}">
                    <td class="log-ts">${esc(formatTimestamp(obj))}</td>
                    <td class="num">${esc(obj.queue_size ?? "")}</td>

                    <td class="bar-cell">
                        ${barCell(obj.in_flight_total, denominator, "total", denominatorLabel)}
                    </td>

                    <td class="bar-cell">
                        ${barCell(obj.in_flight_classify, denominator, "classify", denominatorLabel)}
                    </td>

                    <td class="bar-cell">
                        ${barCell(obj.in_flight_verify, denominator, "verify", denominatorLabel)}
                    </td>

                    <td class="bar-cell">
                        ${barCell(obj.in_flight_reclassify, denominator, "reclassify", denominatorLabel)}
                    </td>

                    <td>${modePill(obj.mode)}</td>
                </tr>
            `;
        }

        function dispatchRow(entry) {
            const obj = entry.obj || {};

            return `
                <tr class="log-row-dispatch">
                    <td class="log-ts">${esc(formatTimestamp(obj))}</td>
                    <td class="log-json">${esc(obj.task_id || "")}</td>
                    <td>${taskTypePill(obj.task_type)}</td>
                    <td>${paperLink(obj.paper_id)}</td>
                    <td class="num">${esc(obj.set_num ?? "")}</td>
                </tr>
            `;
        }

        function completeRow(entry) {
            const obj = entry.obj || {};
            const parsed = parseTaskId(obj.task_id);

            const paperId = parsed.paper_id || obj.paper_id || "";

            const rowClass = isFalse(obj.success)
                ? "log-row-error"
                : isTrue(obj.success)
                    ? "log-row-success"
                    : "";

            return `
                <tr class="${rowClass}">
                    <td class="log-ts">${esc(formatTimestamp(obj))}</td>
                    <td class="log-json">${esc(obj.task_id || "")}</td>
                    <td>${taskTypePill(obj.task_type)}</td>
                    <td>${paperLink(paperId)}</td>
                    <td class="num">${esc(parsed.set_num || obj.set_num || "")}</td>
                    <td>${esc(obj.model_name || "")}</td>
                    <td>${successCell(obj.success)}</td>
                    <td class="log-json">${esc(obj.error || "")}</td>
                </tr>
            `;
        }

        function requestRow(entry) {
            const obj = entry.obj || {};

            return `
                <tr class="log-row-request">
                    <td class="log-ts">${esc(formatTimestamp(obj))}</td>
                    <td>${endpointPill(obj.endpoint)}</td>
                    <td>${esc(obj.client || "")}</td>
                    <td>${esc(obj.mode || "")}</td>
                    <td>${paperLink(obj.paper_id)}</td>
                </tr>
            `;
        }

        function errorRow(entry) {
            const obj = entry.obj || {};

            return `
                <tr class="log-row-error">
                    <td class="log-ts">${esc(formatTimestamp(obj))}</td>
                    <td>${esc(obj.context || "")}</td>
                    <td class="log-json">${esc(obj.error || "")}</td>
                    <td class="log-json">${esc(obj.task_id || "")}</td>
                    <td>${paperLink(obj.paper_id)}</td>
                    <td class="num">${esc(obj.set_num ?? "")}</td>
                </tr>
            `;
        }

        // ------------------------------------------------------------------
        // Tabs / header
        // ------------------------------------------------------------------

        function renderTabs() {
            els.tabs.innerHTML = "";

            VIEWS.forEach(function (view) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `log-tab-btn tab-${view.id}`;
                button.dataset.view = view.id;
                button.title = `${view.label} (${view.file})`;

                const label = document.createElement("span");
                label.className = "tab-label";
                label.textContent = view.label;

                button.appendChild(label);

                button.addEventListener("click", function () {
                    loadView(view.id);
                });

                els.tabs.appendChild(button);
            });

            updateTabs();
        }

        function updateTabs() {
            els.tabs.querySelectorAll(".log-tab-btn").forEach(function (button) {
                button.classList.toggle(
                    "active",
                    button.dataset.view === state.viewId
                );
            });
        }

        function renderHead(view) {
            els.head.innerHTML = view.columns
                .map(function (column) {
                    return `<th>${esc(column)}</th>`;
                })
                .join("");
        }

        // ------------------------------------------------------------------
        // Loading / parsing / rendering
        // ------------------------------------------------------------------

        async function loadView(id) {
            const view = viewById(id);
            if (!view) return;

            if (state.loading) return;

            state.loading = true;
            state.viewId = id;

            const requestId = ++state.requestId;

            history.replaceState(null, "", `#${id}`);

            updateTabs();
            renderHead(view);

            const tail = els.tail.value;
            const tailLabel = els.tail.options[els.tail.selectedIndex].textContent;

            els.source.textContent = `${view.file} · ${tailLabel}`;
            els.download.href = `/queue_logs/raw?name=${encodeURIComponent(view.file)}&download=1`;

            setStatus("");

            const params = new URLSearchParams({
                name: view.file,
            });

            if (tail && tail !== "0") {
                params.set("tail", tail);
            }

            try {
                const response = await fetch(`/queue_logs/raw?${params.toString()}`, {
                    cache: "no-store",
                });

                if (requestId !== state.requestId) return;

                if (!response.ok) {
                    if (response.status === 404) {
                        state.entries = [];
                        state.filtered = [];

                        if (view.id === "error") {
                            state.emptyMessage = "No errors logged yet.";
                            setStatus("This is usually a good sign.");
                        } else {
                            state.emptyMessage = `No ${view.label.toLowerCase()} entries yet.`;
                            setStatus("");
                        }

                        els.count.textContent = "0 / 0";
                        els.source.textContent = `${view.file} · not created yet`;
                        els.download.href = "#";

                        render();
                        restartAutoRefresh();
                        return;
                    }

                    throw new Error(`${response.status} ${response.statusText}`);
                }

                const text = await response.text();

                if (requestId !== state.requestId) return;

                parseEntries(text, view.event);
                render();
                restartAutoRefresh();
            } catch (error) {
                if (requestId !== state.requestId) return;

                state.entries = [];
                state.filtered = [];
                state.emptyMessage = "";
                els.tbody.innerHTML = "";
                els.count.textContent = "0 / 0";

                setStatus(`Could not load ${view.file}: ${error.message}`);
            } finally {
                if (requestId === state.requestId) {
                    state.loading = false;
                }
            }
        }

        function parseEntries(text, event) {
            state.emptyMessage = "";

            const lines = text
                .split(/\r?\n/)
                .filter(function (line) {
                    return line.trim() !== "";
                });

            const entries = [];

            for (const line of lines) {
                let obj = null;

                try {
                    obj = JSON.parse(line);
                } catch (error) {
                    obj = null;
                }

                if (obj && obj.event === event) {
                    entries.push({
                        line,
                        obj,
                    });
                }
            }

            // Newest first.
            state.entries = entries.reverse();
        }

        function applyFilters() {
            const query = els.search.value.trim().toLowerCase();

            state.filtered = state.entries.filter(function (entry) {
                if (!query) return true;
                return entry.line.toLowerCase().includes(query);
            });
        }

        function render() {
            const view = currentView();

            applyFilters();

            els.count.textContent =
                `${state.filtered.length.toLocaleString()} / ${state.entries.length.toLocaleString()}`;

            const limit = parseInt(els.limit.value, 10) || 0;
            const rows = limit > 0
                ? state.filtered.slice(0, limit)
                : state.filtered;

            if (!rows.length) {
                let message;

                if (state.entries.length) {
                    message = "No matching lines.";
                } else {
                    message = state.emptyMessage || "No entries.";
                }

                els.tbody.innerHTML = `
                    <tr>
                        <td colspan="${view.columns.length}" class="queue-empty-state">
                            ${esc(message)}
                        </td>
                    </tr>
                `;

                return;
            }

            els.tbody.innerHTML = rows
                .map(function (entry) {
                    return view.row(entry);
                })
                .join("");
        }
        // ------------------------------------------------------------------
        // Auto refresh
        // ------------------------------------------------------------------

        function restartAutoRefresh() {
            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }

            if (els.autoRefresh.checked && state.viewId) {
                state.timer = setInterval(function () {
                    loadView(state.viewId);
                }, 5000);
            }
        }

        // ------------------------------------------------------------------
        // Events
        // ------------------------------------------------------------------

        els.refreshBtn.addEventListener("click", function () {
            loadView(state.viewId);
        });

        els.tail.addEventListener("change", function () {
            loadView(state.viewId);
        });

        els.limit.addEventListener("change", render);

        els.search.addEventListener("input", function () {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(render, 150);
        });

        els.autoRefresh.addEventListener("change", restartAutoRefresh);

        // ------------------------------------------------------------------
        // Initial state
        // ------------------------------------------------------------------

        renderTabs();

        const hashView = location.hash.replace("#", "");
        const initialView = viewById(hashView) || VIEWS[0];

        loadView(initialView.id);
    }
})();