import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ux_workspace_fixtures.py"
SPEC = importlib.util.spec_from_file_location("ux_workspace_fixtures", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fixture_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_module)
WorkspaceFixture = fixture_module.WorkspaceFixture


class FakeRoute:
    def __init__(self, method, path):
        self.request = SimpleNamespace(method=method, url="http://localhost" + path, post_data=None)
        self.response = None

    def fulfill(self, **kwargs):
        self.response = kwargs


@pytest.mark.parametrize("path", ["/api/v1/prices", "/api/v1/prices/latest"])
def test_price_list_fixture_matches_api_array_contract(path):
    route = FakeRoute("GET", path)
    assert WorkspaceFixture().handle(route) is True
    assert route.response["status"] == 200
    assert json.loads(route.response["body"])["data"] == []


def test_price_write_is_not_handled_as_a_read_fixture():
    route = FakeRoute("POST", "/api/v1/prices")
    assert WorkspaceFixture().handle(route) is False
    assert route.response is None
