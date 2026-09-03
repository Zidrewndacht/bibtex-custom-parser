import json
import socket
import sqlite3
import threading
import time

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

# These imports are SAFE because root conftest.py already set the env vars
from shared import db
from web import create_web_app


@pytest.fixture(scope="session")
def e2e_db_path(tmp_path_factory):
    """Provides the temporary database path for the entire test session."""
    return str(tmp_path_factory.mktemp("e2e") / "test.sqlite")


from shared import config


@pytest.fixture(autouse=True)
def reset_seed_data(e2e_db_path, app_server, page): 
    """
    Janitor fixture: Resets the DB to the pristine seed state before EVERY test.
    """
    # Requesting `app_server` ensures the server is up.
    # Requesting `e2e_db_path` gives us the exact string path safely.
    conn = sqlite3.connect(e2e_db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    
    # Wipe ALL papers including placeholder
    cursor.execute("DELETE FROM papers")
    # (no need to re-insert placeholder; seed papers are sufficient)
    
    # Re-insert the pristine seed papers
    for p in SEED_PAPERS:
        cols = ", ".join(p.keys())
        placeholders = ", ".join(f":{k}" for k in p.keys())
        cursor.execute(f"INSERT INTO papers ({cols}) VALUES ({placeholders})", p)
    conn.commit()
    conn.close()
    
    # Reset the shared session page to the root URL before every test
    page.goto(app_server)
    page.wait_for_load_state("networkidle")
    
    yield

@pytest.fixture(autouse=True)
def reset_browser_state(page):
    """Reset browser UI state before each test."""
    # Close any open modals
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    page.keyboard.press("Escape")  # double-tap for stacked modals
    page.wait_for_timeout(100)

    # Clear search
    search = page.locator("#search-input")
    if search.count() > 0:
        search.fill("")
    page.wait_for_timeout(200)

    # Reset URL to base (clears all filter/sort/detail state)
    page.goto(page.url.split("?")[0])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)

    yield

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def _paper(pid, title, year=2024, pages=8, journal="J Test",
           cls=None, cert=None, authors="Smith, John; Doe, Jane",
           keywords="test; domain", pdf_state="none", pdf_filename=None,
           user_trace="", verified=None, verified_by=None,
           estimated_score=None, llm_log=None):
    """Build a full papers-table INSERT dict."""
    return {
        "id": pid,
        "type": "article",
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "pages": f"1 - {pages}",
        "page_count": pages,
        "doi": f"10.1/{pid}",
        "classification": json.dumps(cls or {}),
        "main_certainty": json.dumps(cert or {}),
        "last_llm_classification": json.dumps(cls or {}),
        "pdf_state": pdf_state,
        "pdf_filename": pdf_filename,
        "user_trace": user_trace,
        "verified": verified,
        "verified_by": verified_by,
        "estimated_score": estimated_score,
        "user_override_count": 0,
        "changed": None,
        "changed_by": None,
        "llm_log": json.dumps(llm_log or []),
        "set_1_llm_log": "[]",
        "set_2_llm_log": "[]",
        "set_3_llm_log": "[]",
    }


# Seed data matching the FIXED test domain config schema
SEED_PAPERS = [
    # p1: On-topic, fully classified, solid, PDF present, is_test_bool=True, feat_a=True
    _paper("p1", "Deep Learning for Test Inspection", 2024, 10, "IEEE Trans",
           cls={"is_offtopic": False, "relevance": 9, "is_test_bool": True,
                "features": {"feat_a": True, "feat_b": False},
                "technique": {"method_x": True}},
           cert={"is_offtopic": "solid", "relevance": "solid",
                 "is_test_bool": "solid",
                 "features.feat_a": "solid", "features.feat_b": "solid",
                 "technique.method_x": "solid"},
           keywords="Test; deep learning",
           pdf_state="PDF", pdf_filename="p1.pdf",
           verified=1, verified_by="computer", estimated_score=9),

    # p2: On-topic, conflict on is_test_bool, paywalled, feat_a=True, feat_b=True
    _paper("p2", "Test Systems Review", 2023, 6, "J Manufacturing",
           cls={"is_offtopic": False, "relevance": 7, "is_test_bool": True,
                "features": {"feat_a": True, "feat_b": True}},
           cert={"is_offtopic": "solid", "is_test_bool": "conflict",
                 "features.feat_a": "solid", "features.feat_b": "solid"},
           keywords="Test; review",
           authors="Alice, Bob",
           pdf_state="paywalled",
           llm_log=[
               {"timestamp": "2025-01-01T10:00:00Z", "type": "classifier", "model": "qwen3", "trace": "", "output": '{"is_offtopic": false}', "valid": True},
               {"timestamp": "2025-01-01T10:01:00Z", "type": "verifier", "model": "qwen3", "trace": "", "output": '{"verified": true, "estimated_score": 8}', "valid": True},
               {"timestamp": "2025-01-01T10:02:00Z", "type": "averaged_llm", "model": "averaged", "trace": "", "output": '{"is_offtopic": false}', "valid": True},
           ]),

    # p3: Off-topic
    _paper("p3", "Quantum Computing Basics", 2022, 4, "Nature",
           cls={"is_offtopic": True, "relevance": 1},
           cert={"is_offtopic": "solid"},
           keywords="quantum"),

    # p4: On-topic, unverified, user comment "paywalled", is_test_bool=False, feat_b=True
    _paper("p4", "Solder Defect Detection", 2024, 12, "IEEE Trans",
           cls={"is_offtopic": False, "relevance": 8, "is_test_bool": False,
                "features": {"feat_a": False, "feat_b": True}},
           cert={"is_offtopic": "solid", "is_test_bool": "solid",
                 "features.feat_a": "solid", "features.feat_b": "solid"},
           keywords="solder; defect",
           user_trace="paywalled",
           pdf_state="paywalled"),

    # p5: On-topic, partial certainty (80%) on is_test_bool, annotated PDF, NO features
    _paper("p5", "Transformer Models for Test", 2025, 8, "CVPR",
           cls={"is_offtopic": False, "relevance": 6, "is_test_bool": True,
                "technique": {"method_x": True}},
           cert={"is_offtopic": "solid", "is_test_bool": "80",
                 "technique.method_x": "solid"},
           keywords="transformer",
           pdf_state="annotated", pdf_filename="p5.pdf"),
]

# 3. Update app_server to request e2e_db_path
@pytest.fixture(scope="session")
def app_server(e2e_db_path):
    # Point the global config to the test DB so /agreement_report works
    config.DATABASE_FILE = e2e_db_path 
    
    db.init_db(e2e_db_path)
    
    # Initial seed
    conn = sqlite3.connect(e2e_db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM papers")
    for p in SEED_PAPERS:
        cols = ", ".join(p.keys())
        placeholders = ", ".join(f":{k}" for k in p.keys())
        cursor.execute(f"INSERT INTO papers ({cols}) VALUES ({placeholders})", p)
    conn.commit()
    conn.close()

    # Start Flask server (using e2e_db_path)
    app = create_web_app(e2e_db_path)
    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    
    yield f"http://127.0.0.1:{port}"
    
    server.shutdown()


@pytest.fixture(scope="session")
def browser_instance():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def page(app_server, request): # Ensure 'request' is in the arguments
    # 1. Read the CLI flags
    is_headed = request.config.getoption("--headed")
    slow_mo = request.config.getoption("--slow-mo")
    
    with sync_playwright() as p:
        # 2. Pass them to the browser launch
        browser = p.chromium.launch(
            headless=not is_headed,  # If --headed is True, headless becomes False
            slow_mo=slow_mo          # Adds a delay between every Playwright action
        )
        
        context = browser.new_context()
        page = context.new_page()
        
        if is_headed:
            page.set_viewport_size({"width": 1920, "height": 1440})
            
        page.goto(app_server)
        
        yield page
        
        context.close()
        browser.close()
        
ROW = "tr[data-paper-id]"
VISIBLE_ROW = f"{ROW}:not(.filter-hidden)"


def visible_ids(page):
    """Return list of visible paper IDs in DOM order."""
    return page.eval_on_selector_all(
        VISIBLE_ROW,
        "rows => rows.map(r => r.getAttribute('data-paper-id'))"
    )