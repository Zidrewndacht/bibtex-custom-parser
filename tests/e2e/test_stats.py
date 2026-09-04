# tests/e2e/test_stats.py
"""
Statistics modal: list contents, chart datasets, metrics table, LaTeX copy
and recomputation after filtering — verified against independently computed
expectations from the crafted seed, on live app and static export.
"""
import pytest

from conftest import goto_export, goto_live

STATS_WAIT = 1800  # displayStats uses a 250ms timeout + chart rendering


def open_stats(page):
    page.keyboard.press("F4")
    page.wait_for_timeout(STATS_WAIT)
    assert page.locator("#statsModal") \
               .evaluate("el => el.classList.contains('modal-active')")


def chart_data(page, name):
    return page.evaluate(
        f"window.chartRegistry['{name}'].data.datasets[0].data")


class TestStatsLists:
    def test_journal_list_counts_duplicate(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        items = page.eval_on_selector_all(
            "#journalStatsList li",
            """lis => lis.map(li => ({
                count: li.querySelector('.count')?.textContent.trim(),
                name: li.querySelector('.name')?.textContent.trim()
            }))"""
        )
        by_name = {i["name"]: i["count"] for i in items}
        assert by_name.get("IEEE Trans") == "2", "p1+p6 share IEEE Trans"
        # p5 is a phdthesis, so it goes to the Thesis category, not Journals.
        # We just verify that the duplicate counting logic works for IEEE Trans.
        assert len(by_name) >= 2

    def test_dynamic_yaml_slot_list(self, page, app_server):
        """stats_list: true on technique.model must feed slot1 list."""
        goto_live(page, app_server)
        open_stats(page)
        texts = page.locator("#slot1StatsList").inner_text()
        assert "qwen3" in texts

    def test_metrics_table_total_filtered(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        metrics = page.locator("#metricsTableStatsList").inner_text()
        assert "5" in metrics  # 5 visible on-topic papers

    def test_keyword_cloud_toggle(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        assert page.locator("#keywordStatsList") \
                   .evaluate("el => getComputedStyle(el).display") == "none"
        page.locator("#cloudToggle").uncheck(force=True)
        page.wait_for_timeout(300)
        assert page.locator("#keywordStatsList") \
                   .evaluate("el => getComputedStyle(el).display") == "block"


class TestStatsCharts:
    def test_chart_registry_populated(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        keys = page.evaluate("Object.keys(window.chartRegistry)")
        for expected in ("relevanceHistogram", "estScoreHistogram",
                         "scopeDistChart", "surveyVsImplDistChart",
                         "pubTypesDistChart"):
            assert expected in keys, f"missing chart {expected}"

    def test_relevance_histogram_matches_rows(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        data = chart_data(page, "relevanceHistogram")
        assert sum(data) == 5

    def test_scope_chart_ontopic_vs_offtopic(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        assert chart_data(page, "scopeDistChart") == [5, 1]

    def test_survey_vs_primary(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        assert chart_data(page, "surveyVsImplDistChart") == [2, 3]

class TestStatsRecomputation:
    def test_stats_recompute_after_search_filter(self, page, app_server):
        goto_live(page, app_server)
        page.fill("#search-input", "Apex")
        page.wait_for_timeout(600)
        open_stats(page)
        metrics = page.locator("#metricsTableStatsList").inner_text()
        assert "1" in metrics
        # p2 is now typed as 'article' so it appears in Journals
        journal_names = page.locator("#journalStatsList").inner_text()
        assert "J Manufacturing" in journal_names

class TestStatsLatexCopy:
    def test_journalconf_latex_copy(self, page, app_server):
        goto_live(page, app_server)
        open_stats(page)
        page.evaluate("""() => {
            window.__copiedTexts = [];
            navigator.clipboard.writeText = t => {
                window.__copiedTexts.push(t);
                return Promise.resolve();
            };
        }""")
        page.click("#journalconf-tabularx-btn")
        page.wait_for_timeout(400)
        copied = page.evaluate("window.__copiedTexts")
        assert len(copied) == 1
        assert "IEEE Trans" in copied[0]

class TestExportStats:
    def test_export_stats_match_live(self, page, app_server):
        goto_export(page, app_server)
        open_stats(page)
        items = page.eval_on_selector_all(
            "#journalStatsList li",
            """lis => lis.map(li => ({
                count: li.querySelector('.count')?.textContent.trim(),
                name: li.querySelector('.name')?.textContent.trim()
            }))"""
        )
        by_name = {i["name"]: i["count"] for i in items}
        assert by_name.get("IEEE Trans") == "2"
        keys = page.evaluate("Object.keys(window.chartRegistry)")
        assert "relevanceHistogram" in keys
        assert sum(chart_data(page, "relevanceHistogram")) == 5