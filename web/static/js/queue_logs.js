// queue_logs.js
// Event-oriented queue log viewer.
// The server only delivers raw JSONL text; parsing/rendering happens here.

class QueueLogViewer {
    constructor() {
        this.root = document.getElementById("queue-logs-page");
        if (!this.root) return;

        this.cacheDom();
        if (!this.els.tabs || !this.els.head || !this.els.tbody) return;

        this.initState();
        this.defineViews();
        this.bindEvents();
        
        this.renderTabs();
        this.loadInitialView();
    }

    cacheDom() {
        this.els = {
            refreshBtn: document.getElementById("refresh-btn"),
            autoRefresh: document.getElementById("auto-refresh"),
            tail: document.getElementById("tail-select"),
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
    }

    initState() {
        this.state = {
            viewId: null,
            entries: [],
            filtered: [],
            loading: false,
            requestId: 0,
            timer: null,
            searchTimer: null,
            emptyMessage: "",
        };
        this.stickToBottom = true;
    }

    defineViews() {
        this.VIEWS = [
            {
                id: "queue_status",
                label: "Queue",
                file: "dispatcher.log",
                event: "queue_status",
                columns: ["Time", "Queue", "In flight", "Classify", "Verify", "Reclassify", "Mode"],
                row: (entry) => this.queueRow(entry),
            },
            {
                id: "dispatch",
                label: "Dispatch",
                file: "dispatcher.log",
                event: "dispatch",
                columns: ["Time", "Task", "Type", "Paper", "Set"],
                row: (entry) => this.dispatchRow(entry),
            },
            {
                id: "complete",
                label: "Complete",
                file: "tasks.log",
                event: "complete",
                columns: ["Time", "Task", "Type", "Paper", "Set", "Model", "Success", "Error"],
                row: (entry) => this.completeRow(entry),
            },
            {
                id: "request",
                label: "Requests",
                file: "requests.log",
                event: "request",
                columns: ["Time", "Endpoint", "Client", "Mode", "Paper"],
                row: (entry) => this.requestRow(entry),
            },
            {
                id: "error",
                label: "Errors",
                file: "errors.log",
                event: "error",
                columns: ["Time", "Context", "Error", "Task", "Paper", "Set"],
                row: (entry) => this.errorRow(entry),
            },
        ];
    }

    bindEvents() {
        this.els.refreshBtn.addEventListener("click", () => this.loadView(this.state.viewId));
        this.els.tail.addEventListener("change", () => this.loadView(this.state.viewId));
        
        this.els.search.addEventListener("input", () => {
            clearTimeout(this.state.searchTimer);
            this.state.searchTimer = setTimeout(() => this.render(), 150);
        });
        
        this.els.autoRefresh.addEventListener("change", () => this.restartAutoRefresh());

        // Track manual scrolling to decide whether to auto-scroll on new data
        this.els.tableWrapper.addEventListener("scroll", () => {
            const el = this.els.tableWrapper;
            const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
            this.stickToBottom = distanceFromBottom < 50;
        });
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    esc(value) {
        return String(value ?? "").replace(/[&<>"']/g, (c) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[c]));
    }

    currentView() {
        return this.viewById(this.state.viewId) || this.VIEWS[0];
    }

    viewById(id) {
        return this.VIEWS.find((v) => v.id === id);
    }

    setStatus(message) {
        this.els.status.textContent = message || "";
    }

    isTrue(value) {
        return value === true || value === 1 || value === "true";
    }

    isFalse(value) {
        return value === false || value === 0 || value === "false";
    }

    successCell(value) {
        if (this.isTrue(value)) return "✔️";
        if (this.isFalse(value)) return "❌";
        if (value === null || value === undefined || value === "") return "";
        return this.esc(String(value));
    }

    formatTimestamp(obj) {
        if (!obj || !obj._ts) return "";
        return new Date(obj._ts).toLocaleString();
    }

    parseTaskId(taskId) {
        const match = String(taskId || "").match(/^(.+)_set(\d+)_/);
        if (!match) return {};
        return { paper_id: match[1], set_num: match[2] };
    }

    parseQueueMode(mode) {
        const raw = String(mode || "");
        const limitMatch = raw.match(/limit=(\d+)/);
        const thresholdMatch = raw.match(/min_threshold=(\d+)/);

        const limit = limitMatch ? parseInt(limitMatch[1], 10) : 0;
        const threshold = thresholdMatch ? parseInt(thresholdMatch[1], 10) : 0;

        if (raw.startsWith("HOMOGENEOUS_CLASSIFY")) return { type: "classify", limit, threshold };
        if (raw.startsWith("HOMOGENEOUS_VERIFY")) return { type: "verify", limit, threshold };
        if (raw.startsWith("HOMOGENEOUS_RECLASSIFY")) return { type: "reclassify", limit, threshold };
        if (raw.startsWith("MIXED")) return { type: "mixed", limit, threshold };

        return { type: null, limit, threshold };
    }

    barCell(value, denominator, category, denominatorLabel, options) {
        const opts = options || {};
        const count = Number(value ?? 0);
        const max = Number(denominator ?? 0);
        const hasDenominator = max > 0;
        const pct = hasDenominator ? Math.min(100, (count / max) * 100) : 0;
        const full = hasDenominator && count >= max;
        const disabled = opts.disabled || !hasDenominator;

        let title;
        if (hasDenominator) {
            title = `${count} / ${max}${denominatorLabel ? ` (${denominatorLabel})` : ""}`;
        } else {
            title = opts.title || `${count}`;
        }

        return `
            <div class="queue-bar-wrap${disabled ? " is-disabled" : ""}" title="${this.esc(title)}">
                <div class="queue-bar-track">
                    <div class="queue-bar-fill fill-${category}${full ? " is-full" : ""}"
                        style="width:${pct}%"></div>
                </div>
                <span class="queue-bar-value">${this.esc(count)}</span>
            </div>
        `;
    }

    paperLink(paperId) {
        if (paperId === null || paperId === undefined || paperId === "") return "";
        const url = `/?focus_paper=${encodeURIComponent(paperId)}`;
        return `
            <a class="paper-link"
               href="${this.esc(url)}"
               target="_blank"
               rel="noopener"
               title="Open paper ${this.esc(paperId)} in the main UI">
                ${this.esc(paperId)}
            </a>
        `;
    }

    taskTypePill(type) {
        if (!type) return "";
        let cls = "pill-other";
        if (type === "classify") cls = "pill-classify";
        else if (type === "verify") cls = "pill-verify";
        else if (type === "reclassify") cls = "pill-reclassify";
        return `<span class="log-pill ${cls}">${this.esc(type)}</span>`;
    }

    endpointPill(endpoint) {
        if (!endpoint) return "";
        let cls = "pill-other";
        if (endpoint.includes("classify")) cls = "pill-classify";
        else if (endpoint.includes("verify")) cls = "pill-verify";
        else if (endpoint.includes("consensus")) cls = "pill-reclassify";
        return `<span class="log-pill ${cls}">${this.esc(endpoint)}</span>`;
    }

    modePill(mode) {
        const raw = String(mode || "");
        if (!raw) return "";

        const key = raw.split(" ")[0];
        const detailStart = raw.indexOf("(");
        const detail = detailStart >= 0 ? raw.slice(detailStart) : "";

        let cls = "pill-status";
        let label = key;

        if (key === "HOMOGENEOUS_CLASSIFY") { cls = "pill-classify"; label = "CLASSIFY"; }
        else if (key === "HOMOGENEOUS_VERIFY") { cls = "pill-verify"; label = "VERIFY"; }
        else if (key === "HOMOGENEOUS_RECLASSIFY") { cls = "pill-reclassify"; label = "RECLASSIFY"; }
        else if (key === "MIXED") { cls = "pill-status"; label = "MIXED"; }

        return `
            <span class="log-pill ${cls}" title="${this.esc(raw)}">${this.esc(label)}</span>
            ${detail ? `<span class="mode-detail">${this.esc(detail)}</span>` : ""}
        `;
    }

    // ------------------------------------------------------------------
    // Row renderers
    // ------------------------------------------------------------------

    queueRow(entry) {
        const obj = entry.obj || {};
        const modeInfo = this.parseQueueMode(obj.mode);

        let rowClass = "";
        if (modeInfo.type === "classify") rowClass = "log-row-classify";
        else if (modeInfo.type === "verify") rowClass = "log-row-verify";
        else if (modeInfo.type === "reclassify") rowClass = "log-row-reclassify";
        else if (modeInfo.type === "mixed") rowClass = "log-row-mixed";

        const denominator = modeInfo.type === "mixed" ? modeInfo.threshold : modeInfo.limit;
        const denominatorLabel = modeInfo.type === "mixed" ? "mixed threshold" : "row limit";

        return `
            <tr class="${rowClass}">
                <td class="log-ts">${this.esc(this.formatTimestamp(obj))}</td>
                <td class="num">${this.esc(obj.queue_size ?? "")}</td>
                <td class="bar-cell">${this.barCell(obj.in_flight_total, denominator, "total", denominatorLabel)}</td>
                <td class="bar-cell">${this.barCell(obj.in_flight_classify, denominator, "classify", denominatorLabel)}</td>
                <td class="bar-cell">${this.barCell(obj.in_flight_verify, denominator, "verify", denominatorLabel)}</td>
                <td class="bar-cell">${this.barCell(obj.in_flight_reclassify, denominator, "reclassify", denominatorLabel)}</td>
                <td>${this.modePill(obj.mode)}</td>
            </tr>
        `;
    }

    dispatchRow(entry) {
        const obj = entry.obj || {};
        return `
            <tr class="log-row-dispatch">
                <td class="log-ts">${this.esc(this.formatTimestamp(obj))}</td>
                <td class="log-json">${this.esc(obj.task_id || "")}</td>
                <td>${this.taskTypePill(obj.task_type)}</td>
                <td>${this.paperLink(obj.paper_id)}</td>
                <td class="num">${this.esc(obj.set_num ?? "")}</td>
            </tr>
        `;
    }

    completeRow(entry) {
        const obj = entry.obj || {};
        const parsed = this.parseTaskId(obj.task_id);
        const paperId = parsed.paper_id || obj.paper_id || "";

        const rowClass = this.isFalse(obj.success)
            ? "log-row-error"
            : this.isTrue(obj.success)
                ? "log-row-success"
                : "";

        return `
            <tr class="${rowClass}">
                <td class="log-ts">${this.esc(this.formatTimestamp(obj))}</td>
                <td class="log-json">${this.esc(obj.task_id || "")}</td>
                <td>${this.taskTypePill(obj.task_type)}</td>
                <td>${this.paperLink(paperId)}</td>
                <td class="num">${this.esc(parsed.set_num || obj.set_num || "")}</td>
                <td>${this.esc(obj.model_name || "")}</td>
                <td>${this.successCell(obj.success)}</td>
                <td class="log-json">${this.esc(obj.error || "")}</td>
            </tr>
        `;
    }

    requestRow(entry) {
        const obj = entry.obj || {};
        return `
            <tr class="log-row-request">
                <td class="log-ts">${this.esc(this.formatTimestamp(obj))}</td>
                <td>${this.endpointPill(obj.endpoint)}</td>
                <td>${this.esc(obj.client || "")}</td>
                <td>${this.esc(obj.mode || "")}</td>
                <td>${this.paperLink(obj.paper_id)}</td>
            </tr>
        `;
    }

    errorRow(entry) {
        const obj = entry.obj || {};
        return `
            <tr class="log-row-error">
                <td class="log-ts">${this.esc(this.formatTimestamp(obj))}</td>
                <td>${this.esc(obj.context || "")}</td>
                <td class="log-json">${this.esc(obj.error || "")}</td>
                <td class="log-json">${this.esc(obj.task_id || "")}</td>
                <td>${this.paperLink(obj.paper_id)}</td>
                <td class="num">${this.esc(obj.set_num ?? "")}</td>
            </tr>
        `;
    }

    // ------------------------------------------------------------------
    // Tabs / header
    // ------------------------------------------------------------------

    renderTabs() {
        this.els.tabs.innerHTML = "";

        this.VIEWS.forEach((view) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `log-tab-btn tab-${view.id}`;
            button.dataset.view = view.id;
            button.title = `${view.label} (${view.file})`;

            const label = document.createElement("span");
            label.className = "tab-label";
            label.textContent = view.label;

            button.appendChild(label);
            button.addEventListener("click", () => this.loadView(view.id));

            this.els.tabs.appendChild(button);
        });

        this.updateTabs();
    }

    updateTabs() {
        this.els.tabs.querySelectorAll(".log-tab-btn").forEach((button) => {
            button.classList.toggle("active", button.dataset.view === this.state.viewId);
        });
    }

    renderHead(view) {
        this.els.head.innerHTML = view.columns
            .map((column) => `<th>${this.esc(column)}</th>`)
            .join("");
    }

    // ------------------------------------------------------------------
    // Loading / parsing / rendering
    // ------------------------------------------------------------------

    async loadView(id) {
        const view = this.viewById(id);
        if (!view || this.state.loading) return;

        // Always stick to bottom when manually changing tabs or refreshing
        this.stickToBottom = true;

        this.state.loading = true;
        this.state.viewId = id;
        const requestId = ++this.state.requestId;

        history.replaceState(null, "", `#${id}`);

        this.updateTabs();
        this.renderHead(view);

        const tail = this.els.tail.value;
        const tailLabel = this.els.tail.options[this.els.tail.selectedIndex].textContent;

        this.els.source.textContent = `${view.file} · ${tailLabel}`;
        this.els.download.href = `/queue_logs/raw?name=${encodeURIComponent(view.file)}&download=1`;
        this.setStatus("");

        const params = new URLSearchParams({ name: view.file });
        if (tail && tail !== "0") params.set("tail", tail);

        try {
            const response = await fetch(`/queue_logs/raw?${params.toString()}`, { cache: "no-store" });
            if (requestId !== this.state.requestId) return;

            if (!response.ok) {
                if (response.status === 404) {
                    this.state.entries = [];
                    this.state.filtered = [];

                    if (view.id === "error") {
                        this.state.emptyMessage = "No errors logged yet.";
                        this.setStatus("This is usually a good sign.");
                    } else {
                        this.state.emptyMessage = `No ${view.label.toLowerCase()} entries yet.`;
                        this.setStatus("");
                    }

                    this.els.count.textContent = "0 / 0";
                    this.els.source.textContent = `${view.file} · not created yet`;
                    this.els.download.href = "#";

                    this.render();
                    this.restartAutoRefresh();
                    return;
                }
                throw new Error(`${response.status} ${response.statusText}`);
            }

            const text = await response.text();
            if (requestId !== this.state.requestId) return;

            this.parseEntries(text, view.event);
            this.render();
            this.restartAutoRefresh();
        } catch (error) {
            if (requestId !== this.state.requestId) return;

            this.state.entries = [];
            this.state.filtered = [];
            this.state.emptyMessage = "";
            this.els.tbody.innerHTML = "";
            this.els.count.textContent = "0 / 0";

            this.setStatus(`Could not load ${view.file}: ${error.message}`);
        } finally {
            if (requestId === this.state.requestId) {
                this.state.loading = false;
            }
        }
    }

    parseEntries(text, event) {
        this.state.emptyMessage = "";
        const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
        const entries = [];

        for (const line of lines) {
            let obj = null;
            try {
                obj = JSON.parse(line);
            } catch (error) {
                obj = null;
            }

            if (obj && obj.event === event) {
                entries.push({ line, obj });
            }
        }

        // Chronological order: oldest first, latest at bottom.
        this.state.entries = entries;
    }

    applyFilters() {
        const query = this.els.search.value.trim().toLowerCase();
        this.state.filtered = this.state.entries.filter((entry) => {
            if (!query) return true;
            return entry.line.toLowerCase().includes(query);
        });
    }

    render() {
        const view = this.currentView();
        this.applyFilters();

        this.els.count.textContent = `${this.state.filtered.length.toLocaleString()} / ${this.state.entries.length.toLocaleString()}`;

        if (!this.state.filtered.length) {
            const message = this.state.entries.length
                ? "No matching lines."
                : (this.state.emptyMessage || "No entries.");

            this.els.tbody.innerHTML = `
                <tr>
                    <td colspan="${view.columns.length}" class="queue-empty-state">
                        ${this.esc(message)}
                    </td>
                </tr>
            `;
            this.scrollToBottomIfSticky();
            return;
        }

        this.els.tbody.innerHTML = this.state.filtered
            .map((entry) => view.row(entry))
            .join("");
            
        this.scrollToBottomIfSticky();
    }

    scrollToBottomIfSticky() {
        if (this.stickToBottom) {
            this.els.tableWrapper.scrollTop = this.els.tableWrapper.scrollHeight;
        }
    }

    // ------------------------------------------------------------------
    // Auto refresh
    // ------------------------------------------------------------------

    restartAutoRefresh() {
        if (this.state.timer) {
            clearInterval(this.state.timer);
            this.state.timer = null;
        }

        if (this.els.autoRefresh.checked && this.state.viewId) {
            this.state.timer = setInterval(() => {
                this.loadView(this.state.viewId);
            }, 5000);
        }
    }

    // ------------------------------------------------------------------
    // Initial state
    // ------------------------------------------------------------------

    loadInitialView() {
        const hashView = location.hash.replace("#", "");
        const initialView = this.viewById(hashView) || this.VIEWS[0];
        this.loadView(initialView.id);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("queue-logs-page")) {
        new QueueLogViewer();
    }
});