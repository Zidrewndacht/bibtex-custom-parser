import re
import pytest
from playwright.sync_api import expect
from conftest import visible_ids

# (query, expected visible ids in DOM order)
SEARCH_CASES = [
    ("Apex",         ["p2"]),        # title
    ("meridian",     ["p1"]),        # title, case-insensitive
    ("alphakey",     ["p1"]),        # hidden keywords cell
    ("Alice",        ["p2"]),        # hidden authors cell
    ("paywalled",    ["p4"]),        # hidden user_trace cell
    ("uniquetext99", ["p6"]),        # hidden editable-field cell (test_text)
    ("transformer",  ["p5"]),        # hidden keywords + title
    ("XQ7",          ["p4"]),        # hidden abstract token
    ("IEEE Trans",   ["p1", "p6"]),  # visible journal cell, multi-row
]

@pytest.mark.parametrize("query,expected", SEARCH_CASES)
def test_search_matches_exactly(page, target, query, expected):
    page.fill("#search-input", query)
    page.wait_for_timeout(600)
    assert visible_ids(page) == expected, \
        f"query={query!r}: got {visible_ids(page)}, want {expected}"

def test_search_no_match_hides_everything(page, target):
    page.fill("#search-input", "zzz_no_such_token_xyz")
    page.wait_for_timeout(600)
    assert visible_ids(page) == []
    # p3 is hidden by default off-topic filter, so 5 rows remain in DOM
    assert page.locator("tr[data-paper-id]").count() >= 5

def test_clear_button_restores_all(page, target):
    page.fill("#search-input", "zzz_no_such_token_xyz")
    page.wait_for_timeout(600)
    assert visible_ids(page) == []
    page.click("#clear-search-btn")
    page.wait_for_timeout(600)
    assert sorted(visible_ids(page)) == ["p1", "p2", "p4", "p5", "p6"]

def test_f3_focuses_search(page, target):
    page.keyboard.press("F3")
    assert page.evaluate("document.activeElement.id") == "search-input"

def test_search_persisted_in_url_and_restored(page, target):
    page.fill("#search-input", "solder")  # matches p4 (keywords) + p6 (title)
    page.wait_for_timeout(700)
    expect(page).to_have_url(re.compile(r"search=solder"))
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(900)
    assert visible_ids(page) == ["p4", "p6"]

def test_search_visible_count_updates(page, target):
    before = len(visible_ids(page))
    page.fill("#search-input", "Apex")
    page.wait_for_timeout(600)
    assert len(visible_ids(page)) == 1 < before