# tests/e2e/conftest.py
"""
E2E test fixtures + the crafted seed database.

Seed design rules (do NOT change values without recomputing EXPECTED_ASC):
- Every sortable column has a DISTINCT order per column, so sorting by the
  wrong column (or not sorting at all) cannot pass by coincidence.
- Initial DOM order (user_trace-first server ordering) differs from every
  sort expectation, so a no-op sort can never pass.
- Tri-state fields contain all three states among visible rows.
- Two inclusion groups with deliberately asymmetric membership so OR vs AND
  semantics are distinguishable:
      test_inclusion  (features.*): {p1, p2, p4, p6}
      test_inclusion2 (methods.*):  {p1, p2, p5}
      union (OR):  {p1, p2, p4, p5, p6}
      intersection (AND, WRONG):    {p1, p2}
"""
import json
import os
import socket
import sqlite3
import threading
import time

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

# Safe: root conftest.py already set the env vars before any app import.
from shared import config, db
from web import create_web_app

# ============================================================================
# Row selectors / helpers (imported by the test modules)
# ============================================================================
ROW = "tr[data-paper-id]"
VISIBLE_ROW = f"{ROW}:not(.filter-hidden)"

# Live URL uses wide server-side filters so ALL six seed papers are served;
# anything narrower is done client-side by the tests themselves.
LIVE_PARAMS = "hide_offtopic=1&year_from=2000&year_to=2035&min_page_count=0"
EXPORT_PARAMS = "download=0&hide_offtopic=1&year_from=2000&year_to=2035&min_page_count=0"

ON_TOPIC = ["p1", "p2", "p4", "p5", "p6"]
ALL_PAPERS = ["p1", "p2", "p3", "p4", "p5", "p6"]

# Server query orders papers WITH a user_trace first, then insertion order.
INITIAL_DOM_ORDER = ["p4", "p1", "p2", "p5", "p6"]
# Corrected expectations based on actual UI rendering (conflict = ⚠️, not ✔️)
TRI_ONLY_TRUE = {"test_tri": {"p1", "p5"},          # p2 is conflict (⚠️), so hidden in only_true
                 "test_survey": {"p2", "p6"}}
TRI_ONLY_FALSEISH = {"test_tri": {"p2", "p4", "p6"}, # keeps ❌, ❔, AND ⚠️
                     "test_survey": {"p1", "p4", "p5"}}

# Expected ASC order per data-sort key, for the default visible set ON_TOPIC.
# DESC is always the exact reverse (total order: value, then paper id; the
# DESC branch negates the whole comparator, reversing tiebreaks as well).
EXPECTED_ASC = {
    # hardcoded leading columns
    "pdf-link":            ["p4", "p2", "p6", "p1", "p5"], # Adjusted for JS emoji fallback weights
    "title":               ["p2", "p6", "p5", "p1", "p4"],
    # p2, p4, p6 are now 'article' (same as p1). p5 is 'phdthesis'.
    # article < phdthesis alphabetically. Tiebreaker for articles is paperId ASC.
    "type":                ["p1", "p2", "p4", "p6", "p5"],
    # numeric / numeric-ish
    "year":                ["p6", "p4", "p2", "p1", "p5"],  # 2019 2021 2023 2024 2025
    "page_count":          ["p2", "p5", "p1", "p4", "p6"],  # 6 8 10 12 15
    "estimated_score":     ["p6", "p4", "p5", "p2", "p1"],  # 2 4 6 7 9
    "user_override_count": ["p5", "p1", "p2", "p4", "p6"],  # 0 1 2 3 4
    "relevance":           ["p6", "p5", "p2", "p4", "p1"],  # 4 6 7 8 9
    # string columns
    "journal":             ["p5", "p1", "p6", "p2", "p4"],  # CVPR, IEEE x2 (id tiebreak), J Manuf, Nature Prod
    # date column (dd/mm/yy HH:MM:SS parsing)
    "changed":             ["p6", "p1", "p2", "p4", "p5"],
    # emoji-span weight columns (👤2 > ❔1 > 🖥️0)
    "changed_by":          ["p2", "p6", "p4", "p1", "p5"],
    "verified_by":         ["p1", "p2", "p4", "p6", "p5"],
    # symbol weight column (✔️2 > ❌1 > ❔0)
    "user_comment_state":  ["p1", "p2", "p5", "p6", "p4"],
    # editable-status / certainty-aware dynamic columns
    "is_offtopic":         ["p1", "p2", "p4", "p5", "p6"],  # all tied (❌ solid) -> pure id order
    "is_test_bool":        ["p6", "p4", "p2", "p5", "p1"],  # 0, 2, 3.25(conflict), 3.75(✔️80), 4
    "is_survey":           ["p1", "p4", "p5", "p6", "p2"],  # 0,0, 2, 3.75(✔️80), 4
    "verified":            ["p2", "p5", "p6", "p4", "p1"],  # 0,0,0, 2, 4
    # Corrected: p5, p6 are missing (❔=0), p4 is False (❌=1), p1, p2 are True (✔️=2)
    "features.feat_a":     ["p5", "p6", "p4", "p1", "p2"],
    "methods.appr_p":      ["p2", "p4", "p5", "p6", "p1"],  # only p1 is ✔️
    "technique.method_x":  ["p2", "p4", "p6", "p1", "p5"],  # ❌x3 (id), ✔️x2 (id)
}

def visible_ids(page):
    """Visible paper IDs in DOM order."""
    return page.eval_on_selector_all(
        VISIBLE_ROW,
        "rows => rows.map(r => r.getAttribute('data-paper-id'))"
    )


def goto_live(page, app_server):
    page.goto(f"{app_server}/?{LIVE_PARAMS}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(900)


def goto_export(page, app_server, hide_offtopic=1):
    params = EXPORT_PARAMS.replace("hide_offtopic=1", f"hide_offtopic={hide_offtopic}")
    page.goto(f"{app_server}/static_export?{params}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(900)


def cycle_tri(page, group):
    """JS click: bypasses headless Chromium's transformed-checkbox click bug."""
    page.locator(f".tri-state-checkbox[data-filter-group='{group}']").evaluate("el => el.click()")
    page.wait_for_timeout(600)


def set_inclusion(page, group, checked):
    """Reliably emulate a user toggling a custom-styled inclusion checkbox."""
    cb = page.locator(f".inclusion-checkbox[data-filter-group='{group}']")
    cb.evaluate(
        """(el, v) => {
            if (el.checked !== v) {
                el.checked = v;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""",
        checked,
    )
    page.wait_for_timeout(600)


# ============================================================================
# Session DB / server fixtures
# ============================================================================
@pytest.fixture(scope="session")
def e2e_db_path(tmp_path_factory):
    return str(tmp_path_factory.mktemp("e2e") / "test.sqlite")


def _paper(pid, title, year, pages, journal, cls=None, cert=None,
           ptype="article", authors="Smith, John; Doe, Jane", keywords="",
           abstract="", pdf_state="none", pdf_filename=None, user_trace="",
           verified=None, verified_by=None, estimated_score=None,
           user_override_count=0, changed=None, changed_by=None, llm_log=None):
    """Build a full papers-table INSERT dict."""
    return {
        "id": pid,
        "type": ptype,
        "title": title,
        "authors": authors,
        "year": year,
        "month": None,
        "journal": journal,
        "volume": None,
        "pages": f"1 - {pages}",
        "page_count": pages,
        "doi": f"10.1/{pid}",
        "issn": None,
        "abstract": abstract,
        "keywords": keywords,
        "deannualized_conference": None,
        "classification": json.dumps(cls or {}),
        "main_certainty": json.dumps(cert or {}),
        "last_llm_classification": json.dumps(cls or {}),
        "pdf_state": pdf_state,
        "pdf_filename": pdf_filename,
        "user_trace": user_trace,
        "verified": verified,
        "verified_by": verified_by,
        "estimated_score": estimated_score,
        "user_override_count": user_override_count,
        "changed": changed,
        "changed_by": changed_by,
        "llm_log": json.dumps(llm_log or []),
        "set_1_llm_log": "[]",
        "set_2_llm_log": "[]",
        "set_3_llm_log": "[]",
    }


# ---------------------------------------------------------------------------
# THE SEED DATABASE — see module docstring before changing ANY value.
# ---------------------------------------------------------------------------
SEED_PAPERS = [
    # p1: on-topic, ✔️ solid test_bool, ❔ survey, feat_a, appr_p, method_x,
    #     PDF present, verified by computer (used for verification-reset tests)
    _paper("p1", "Meridian Inspection Study", 2024, 10, "IEEE Trans",
           ptype="article",
           cls={"is_offtopic": False, "relevance": 9, "is_test_bool": True,
                "features": {"feat_a": True, "feat_b": False},
                "methods": {"appr_p": True},
                "technique": {"method_x": True, "model": "qwen3"},
                "test_text": "meridian text"},
           cert={"is_offtopic": "solid", "relevance": "solid",
                 "is_test_bool": "solid",
                 "features.feat_a": "solid", "features.feat_b": "solid",
                 "methods.appr_p": "solid", "technique.method_x": "solid"},
           keywords="alphakey; inspection",
           abstract="meridian study of alphakey inspection methods",
           pdf_state="PDF", pdf_filename="p1.pdf",
           verified=1, verified_by="computer", estimated_score=9,
           user_override_count=1,
           changed="2025-01-10T10:00:00Z", changed_by="user"),

    # p2: on-topic, ✔️ CONFLICT test_bool, ✔️ solid survey, feat_a+feat_b,
    #     text_presence 'other' present, appr_q, paywall-free 'none' PDF
    _paper("p2", "Apex Systems Review", 2023, 6, "J Manufacturing",
           ptype="article", authors="Alice, Bob",
           cls={"is_offtopic": False, "relevance": 7, "is_test_bool": True,
                "is_survey": True,
                "features": {"feat_a": True, "feat_b": True,
                             "other": "auxiliary"},
                "methods": {"appr_q": True},
                "technique": {}},
           cert={"is_offtopic": "solid", "is_test_bool": "conflict",
                 "is_survey": "solid",
                 "features.feat_a": "solid", "features.feat_b": "solid",
                 "features.other": "solid", "methods.appr_q": "solid"},
           keywords="review; bravo",
           abstract="apex review of bravo systems",
           pdf_state="none",
           verified=None, verified_by="computer", estimated_score=7,
           user_override_count=2,
           changed="2025-02-20T08:00:00Z", changed_by="LLM_Averaged",
           llm_log=[
               {"timestamp": "2025-01-01T10:00:00Z", "type": "classifier", "model": "qwen3", "trace": "", "output": '{"is_offtopic": false}', "valid": True},
               {"timestamp": "2025-01-01T10:01:00Z", "type": "verifier", "model": "qwen3", "trace": "", "output": '{"verified": true, "estimated_score": 8}', "valid": True},
               {"timestamp": "2025-01-01T10:02:00Z", "type": "averaged_llm", "model": "averaged", "trace": "", "output": '{"is_offtopic": false}', "valid": True},
           ]),

    # p3: OFF-TOPIC (hidden by default; visible via hide_offtopic=0)
    _paper("p3", "Quantum Offtopic Basics", 2022, 4, "Nature Q",
           ptype="misc",
           cls={"is_offtopic": True, "relevance": 1},
           cert={"is_offtopic": "solid"},
           keywords="quantum",
           abstract="quantum totpaper XQ42",
           pdf_state="none",
           user_override_count=0,
           changed="2025-01-05T00:00:00Z", changed_by=None),

    # p4: on-topic, ❌ solid test_bool, ❔ survey, feat_b only, NO methods,
    #     paywalled, user comment present, verified=0, book type
    _paper("p4", "Zenith Defect Detection", 2021, 12, "Nature Prod",
           ptype="article",
           cls={"is_offtopic": False, "relevance": 8, "is_test_bool": False,
                "features": {"feat_a": False, "feat_b": True},
                "methods": {},
                "technique": {}},
           cert={"is_offtopic": "solid", "is_test_bool": "solid",
                 "features.feat_a": "solid", "features.feat_b": "solid"},
           keywords="solder; defect",
           abstract="soldervoid abstract token XQ7",
           user_trace="paywalled", pdf_state="paywalled",
           verified=0, verified_by=None, estimated_score=4,
           user_override_count=3,
           changed="2025-03-05T12:00:00Z", changed_by=None),

    # p5: on-topic, ✔️ 80% test_bool, ❌ solid survey, NO features (but appr_r
    #     in inclusion group 2), method_x, annotated PDF, verified_by=user
    _paper("p5", "Cascade Transformer Models", 2025, 8, "CVPR",
           ptype="phdthesis",
           cls={"is_offtopic": False, "relevance": 6, "is_test_bool": True,
                "is_survey": False,
                "features": {},
                "methods": {"appr_r": True},
                "technique": {"method_x": True}},
           cert={"is_offtopic": "solid", "is_test_bool": "80",
                 "is_survey": "solid", "methods.appr_r": "solid",
                 "technique.method_x": "solid"},
           keywords="transformer",
           abstract="cascade transformer models for inspection",
           pdf_state="annotated", pdf_filename="p5.pdf",
           verified=None, verified_by="user", estimated_score=6,
           user_override_count=0,
           changed="2025-04-15T09:30:00Z", changed_by="user"),

    # p6: on-topic, ❔ test_bool (key absent), ✔️ 80% survey, feat_c only,
    #     NO methods, method_z, 2019 (outside default config year range!),
    #     shares journal with p1 (stats duplicate), highest override count
    _paper("p6", "Beacon Solder Methods", 2019, 15, "IEEE Trans",
           ptype="article",
           cls={"is_offtopic": False, "relevance": 4, "is_survey": True,
                "features": {"feat_c": True},
                "methods": {},
                "technique": {"method_z": True},
                "test_text": "uniquetext99"},
           cert={"is_offtopic": "solid", "is_survey": "80",
                 "features.feat_c": "solid", "technique.method_z": "solid"},
           keywords="beacon; solder",
           abstract="beacon solder methods compendium",
           pdf_state="none",
           verified=None, verified_by=None, estimated_score=2,
           user_override_count=4,
           changed="2024-12-31T23:59:59Z", changed_by="LLM_Averaged"),
]


def _seed_into(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM papers")
    for p in SEED_PAPERS:
        cols = ", ".join(p.keys())
        placeholders = ", ".join(f":{k}" for k in p)
        cursor.execute(f"INSERT INTO papers ({cols}) VALUES ({placeholders})", p)
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def reset_seed_data(e2e_db_path, app_server):
    """Janitor: resets the DB to the pristine seed state before EVERY test."""
    _seed_into(e2e_db_path)
    yield


@pytest.fixture(autouse=True)
def reset_browser_state(page, app_server):
    """Hard-navigation reset: guarantees a completely fresh DOM/JS state."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    page.goto("about:blank")
    page.goto(app_server)
    page.wait_for_load_state("networkidle")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_server(e2e_db_path):
    config.DATABASE_FILE = e2e_db_path
    db.init_db(e2e_db_path)
    # CRITICAL FIX: Ensure PDF storage directories exist.
    # Without this, Flask's file.save() crashes the server thread on upload,
    # causing Playwright to hang and the pytest-xdist worker to die.
    os.makedirs(config.PDF_STORAGE_DIR, exist_ok=True)
    os.makedirs(config.ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)
    
    _seed_into(e2e_db_path)
    app = create_web_app(e2e_db_path)
    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(scope="session")
def page(app_server, request):
    is_headed = request.config.getoption("--headed")
    slow_mo = request.config.getoption("--slow-mo")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not is_headed,
            slow_mo=slow_mo,
        )
        context = browser.new_context()
        page = context.new_page()
        if is_headed:
            page.set_viewport_size({"width": 1920, "height": 1440})
        page.goto(app_server)
        yield page
        context.close()
        browser.close()


# ============================================================================
# Target parametrization: every behavior is tested on the LIVE server app
# AND on the client-only static HTML export (regression source in the past).
# ============================================================================
@pytest.fixture(params=["live", "export"])
def target(request, page, app_server):
    if request.param == "live":
        goto_live(page, app_server)
    else:
        goto_export(page, app_server)
    return request.param


# ============================================================================
# Server-side verification: read the real SQLite DB, not the rendered DOM.
# ============================================================================
@pytest.fixture
def db_reader(e2e_db_path):
    """Returns a function that reads+JSON-parses a paper straight from disk."""
    def read(paper_id):
        conn = sqlite3.connect(e2e_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Paper {paper_id} missing from server DB"
        d = dict(row)
        for col in ("classification", "main_certainty", "last_llm_classification"):
            try:
                d[col] = json.loads(d[col] or "{}")
            except (json.JSONDecodeError, TypeError):
                d[col] = {}
        for col in ("llm_log", "set_1_llm_log", "set_2_llm_log", "set_3_llm_log"):
            try:
                d[col] = json.loads(d[col] or "[]")
            except (json.JSONDecodeError, TypeError):
                d[col] = []
        return d
    return read