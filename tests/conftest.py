import os
import json
import pytest

# ==============================================================================
# MUST execute BEFORE any app imports
# ==============================================================================
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

os.environ["PARSA_BASE_DIR"] = ROOT_DIR
os.environ["PARSA_CONFIG_PATH"] = os.path.join(FIXTURES_DIR, 'config.yaml')
os.environ["PARSA_DOMAIN_CONFIG_PATH"] = os.path.join(FIXTURES_DIR, 'domain_config.yaml')
os.environ["PARSA_DATA_DIR"] = os.path.join(FIXTURES_DIR, 'dummy_data')
os.makedirs(os.environ["PARSA_DATA_DIR"], exist_ok=True)

# --- NOW safe to import app code ---
from shared import config, db


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.sqlite")
    monkeypatch.setattr(config, "DATABASE_FILE", db_path)
    monkeypatch.setattr(config, "PDF_STORAGE_DIR", str(tmp_path / "pdf"))
    monkeypatch.setattr(config, "ANNOTATED_PDF_STORAGE_DIR", str(tmp_path / "pdf_annotated"))
    os.makedirs(config.PDF_STORAGE_DIR, exist_ok=True)
    os.makedirs(config.ANNOTATED_PDF_STORAGE_DIR, exist_ok=True)
    db.init_db(db_path)
    with db.get_db() as conn:
        conn.execute("DELETE FROM papers WHERE id = '1'")
    yield db_path


@pytest.fixture()
def seed_paper(test_db):
    with db.get_db() as conn:
        conn.execute("INSERT INTO papers (id, title, year) VALUES ('p1', 'Seed', 2024)")

    def _set_blobs(set1, set2, set3):
        with db.get_db() as conn:
            conn.execute(
                "UPDATE papers SET set_1_llm=?, set_2_llm=?, set_3_llm=? WHERE id='p1'",
                (json.dumps(set1), json.dumps(set2), json.dumps(set3)),
            )
    return _set_blobs