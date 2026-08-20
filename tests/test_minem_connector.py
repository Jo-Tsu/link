from __future__ import annotations

import json
import sys

from smallink.agent import _enabled_connector_tools
from smallink.connectors import connect_connector, connector_list, make_integration_tools
from smallink.connectors.minem_client import MineMClient
from smallink.secrets import SecretStore


def _fake_cli(tmp_path):
    script = tmp_path / "fake_minem.py"
    script.write_text(
        """
import json
import sys

args = sys.argv[1:]
if args[:1] == ["status"]:
    payload = {
        "schemaVersion": "minem.cli/v1",
        "ok": True,
        "data": {
            "release": {"product": "MineM", "version": "0.5.0", "apiVersion": 1},
            "stats": {"visibleAssets": 1518, "reports": 12},
        },
        "meta": {"serverUrl": "http://127.0.0.1:8790"},
    }
elif args[:2] == ["asset", "search"]:
    payload = {
        "schemaVersion": "minem.cli/v1",
        "ok": True,
        "data": {
            "items": [
                {"code": "RPT-1", "type": "report", "title": "First"},
                {"code": "PAG-2", "type": "page", "title": "Second"},
                {"code": "RES-3", "type": "resource", "title": "Third"},
            ],
            "total": 3,
        },
        "links": {"preview": "http://127.0.0.1:8790/reports/RPT-1"},
    }
else:
    payload = {
        "schemaVersion": "minem.cli/v1",
        "ok": True,
        "resource": {"code": "RPT-1", "type": "report"},
        "data": {"title": "First"},
    }
print(json.dumps(payload))
""".strip(),
        encoding="utf-8",
    )
    return MineMClient([sys.executable, str(script)])


def test_minem_cli_connect_and_search_are_normalised(tmp_path):
    client = _fake_cli(tmp_path)

    status = client.connect()
    assert status["ok"] is True
    assert status["app_version"] == "0.5.0"
    assert status["api_version"] == 1
    assert status["visible_asset_count"] == 1518
    assert status["runtime_url"] == "http://127.0.0.1:8790"

    result = client.search_assets("Smallink", limit=2)
    assert result["ok"] is True
    assert [row["code"] for row in result["results"]] == ["RPT-1", "PAG-2"]
    assert result["truncated"] is True
    assert result["links"]["preview"].startswith("http://127.0.0.1:")


def test_minem_cli_rejects_invalid_json(tmp_path):
    script = tmp_path / "broken_minem.py"
    script.write_text("print('not json')", encoding="utf-8")
    client = MineMClient([sys.executable, str(script)])

    result = client.connect()
    assert result["ok"] is False
    assert "JSON" in result["error"]


def test_minem_cli_uses_validated_manifest_runtime_without_fixed_port(
    tmp_path, monkeypatch
):
    script = tmp_path / "runtime_probe.py"
    script.write_text(
        """
import json
import os

print(json.dumps({
    "schemaVersion": "minem.cli/v1",
    "ok": True,
    "data": {"release": {"version": "0.5.0", "apiVersion": 1}},
    "meta": {"serverUrl": os.environ.get("MINEM_BASE_URL", "")},
}))
""".strip(),
        encoding="utf-8",
    )
    client = MineMClient([sys.executable, str(script)])
    monkeypatch.setattr(
        client,
        "_read_manifest",
        lambda: {
            "status": "running",
            "managedByClient": False,
            "baseUrl": "http://127.0.0.1:43127",
        },
    )

    result = client.status()
    assert result["ok"] is True
    assert result["runtime_url"] == "http://127.0.0.1:43127"


def test_minem_cli_rejects_non_loopback_manifest_runtime(tmp_path, monkeypatch):
    script = tmp_path / "runtime_probe.py"
    script.write_text(
        """
import json
import os

print(json.dumps({
    "schemaVersion": "minem.cli/v1",
    "ok": True,
    "data": {"release": {"version": "0.5.0", "apiVersion": 1}},
    "meta": {"serverUrl": os.environ.get("MINEM_BASE_URL", "")},
}))
""".strip(),
        encoding="utf-8",
    )
    client = MineMClient([sys.executable, str(script)])
    monkeypatch.setattr(
        client,
        "_read_manifest",
        lambda: {"status": "running", "baseUrl": "https://example.com:443"},
    )

    result = client.status()
    assert result["ok"] is True
    assert result["runtime_url"] == ""


def test_minem_capability_allowlist_requires_confirmation(tmp_path):
    client = _fake_cli(tmp_path)

    rejected = client.invoke(
        "asset.delete",
        {"reference": "CTRL-PAGE-001"},
    )
    assert rejected == {
        "ok": False,
        "error": "confirm=true is required for this MineM operation",
        "error_code": "INVALID_ARGUMENT",
    }
    unsupported = client.invoke("shell.exec", {"command": "echo nope"})
    assert unsupported["ok"] is False
    assert unsupported["error_code"] == "INVALID_ARGUMENT"


def test_minem_connector_connects_via_cli_and_enables_read_tools(tmp_path, monkeypatch):
    from smallink.connectors import minem_client

    client = _fake_cli(tmp_path)
    monkeypatch.setattr(minem_client, "_DEFAULT_CLIENT", client)
    secrets = SecretStore(tmp_path / "secrets.json")

    before = {row["name"]: row for row in connector_list(secrets)}["minem"]
    assert before["connected"] is False
    assert before["auth"] == "local_app"

    connected = connect_connector(secrets, "minem", {})
    assert connected["ok"] is True
    assert connected["account"] == "MineM 0.5.0"

    after = {row["name"]: row for row in connector_list(secrets)}["minem"]
    assert after["connected"] is True
    assert all(tool["kind"] == "read" for tool in after["tools"])

    enabled_connectors, enabled_tools = _enabled_connector_tools(secrets)
    assert "minem" in enabled_connectors
    assert {
        "minem_status",
        "minem_search_assets",
        "minem_get_asset",
        "minem_get_report_pages",
        "minem_get_versions",
        "minem_get_lineage",
    }.issubset(enabled_tools)

    tools = make_integration_tools(
        secrets,
        enabled_connectors=enabled_connectors,
        enabled_tools=enabled_tools,
    )
    by_name = {tool.__name__: tool for tool in tools}
    assert by_name["minem_search_assets"].__aisuite_tool_metadata__.requires_approval is False
    assert by_name["minem_search_assets"]("Smallink", limit=1)["count"] == 1


def test_minem_connector_failure_does_not_persist_profile(tmp_path, monkeypatch):
    from smallink.connectors import minem_client

    class BrokenClient:
        def connect(self):
            return {"ok": False, "error": "MineM unavailable"}

        def inspect(self):
            return {
                "app_installed": True,
                "cli_available": True,
                "health": "offline",
            }

    monkeypatch.setattr(minem_client, "_DEFAULT_CLIENT", BrokenClient())
    secrets = SecretStore(tmp_path / "secrets.json")

    assert connect_connector(secrets, "minem", {}) == {
        "ok": False,
        "error": "MineM unavailable",
    }
    assert secrets.get("minem:default") is None
