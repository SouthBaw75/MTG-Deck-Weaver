from pathlib import Path

import pytest

from weaver.db.connection import connect
from weaver.db.schema import apply_schema

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def db(tmp_path):
    """Fresh in-temp-dir knowledge base with the full schema applied."""
    conn = connect(tmp_path / "weaver.db")
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def cache_dir(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture()
def fixtures_dir():
    return FIXTURES
