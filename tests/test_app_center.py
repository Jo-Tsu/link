from __future__ import annotations

from fastapi.testclient import TestClient

from smallink.apps import SQLiteAppStore
from smallink.memory import Scope
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager, create_app


class NoopProvider(ProviderClient):
    def complete(self, **kwargs) -> AssistantTurn:
        return AssistantTurn(text="")

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


class FakeMineM:
    def inspect(self):
        return {
            "app_installed": True,
            "cli_available": True,
            "health": "running",
            "runtime_url": "http://127.0.0.1:8790",
        }

    def status(self):
        return {
            "ok": True,
            "app_installed": True,
            "cli_available": True,
            "health": "running",
            "app_version": "0.5.0",
            "api_version": "minem.cli/v1",
        }

    def list_assets(self, asset_type="all", limit=30, *, query=""):
        return {
            "ok": True,
            "assets": [
                {
                    "id": "page-1",
                    "code": "CTRL-PAGE-001",
                    "type": "page",
                    "title": "Smallink architecture",
                    "previewUrl": "http://127.0.0.1:8790/assets/page-1",
                }
            ],
            "count": 1,
        }

    def search_assets(self, query, asset_type="all", limit=10):
        result = self.list_assets(asset_type, limit, query=query)
        result["results"] = result.pop("assets")
        return result

    def invoke(self, capability, arguments):
        return {
            "ok": True,
            "command": capability,
            "resource": {
                "id": "page-1",
                "code": "CTRL-PAGE-001",
                "type": "page",
                "title": arguments.get("name", "Smallink architecture"),
            },
        }


def test_app_store_can_close_and_reopen(tmp_path):
    path = tmp_path / "smallink.db"
    store = SQLiteAppStore(path)
    store.ensure_instance("minem")
    store.close()

    reopened = SQLiteAppStore(path)
    try:
        assert reopened.get_instance("minem") is not None
    finally:
        reopened.close()


def _manager(tmp_path, monkeypatch):
    fake = FakeMineM()
    monkeypatch.setattr("smallink.server.manager.get_minem_client", lambda: fake)
    return SessionManager(data_dir=tmp_path / "data", provider=NoopProvider())


def test_builtin_minem_app_creates_one_protected_system_project(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    apps = manager.list_apps()
    assert len(apps) == 1
    assert apps[0]["app_id"] == "minem"
    assert apps[0]["project"]["project_id"] == "system:minem"
    assert apps[0]["project"]["project_type"] == "system_app"
    assert apps[0]["project"]["owner_app_id"] == "minem"
    assert manager.delete_project("system:minem") == {
        "ok": False,
        "error": "system application projects cannot be deleted",
    }

    manager._ensure_builtin_app_projects()
    assert [item.project_id for item in manager.session_store.list_projects()].count("system:minem") == 1


def test_minem_asset_reads_create_source_facts_and_stable_refs(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    result = manager.app_assets("minem", asset_type="page")

    assert result["ok"] is True
    assert result["items"][0]["code"] == "CTRL-PAGE-001"
    assert result["smallink"]["sensory_record_id"].startswith("sensory-")
    records = manager.sensory_store.list(source_type="minem")
    assert len(records) == 1
    assert records[0].metadata["project_id"] == "system:minem"
    refs = manager.app_store.list_assets("minem", project_id="system:minem")
    assert len(refs) == 1
    assert refs[0]["external_asset_id"] == "page-1"
    assert refs[0]["sensory_record_id"] == records[0].record_id

    manager.app_assets("minem", asset_type="page")
    assert len(manager.app_store.list_assets("minem")) == 1


def test_app_center_rest_exposes_manifest_assets_and_activity(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    client = TestClient(create_app(manager))

    catalog = client.get("/v1/apps")
    assert catalog.status_code == 200
    assert catalog.json()["apps"][0]["project"]["system_key"] == "system:minem"

    assets = client.get("/v1/apps/minem/assets", params={"asset_type": "page"})
    assert assets.status_code == 200
    assert assets.json()["items"][0]["title"] == "Smallink architecture"

    renamed = client.post(
        "/v1/apps/minem/capabilities/asset.rename",
        json={"arguments": {"reference": "CTRL-PAGE-001", "name": "Renamed"}},
    )
    assert renamed.status_code == 200
    assert renamed.json()["resource"]["title"] == "Renamed"

    activity = client.get("/v1/apps/minem/activity").json()["activity"]
    assert [item["capability"] for item in activity[:2]] == ["asset.rename", "asset.list"]


def test_unknown_or_undeclared_app_capability_is_rejected(tmp_path, monkeypatch):
    client = TestClient(create_app(_manager(tmp_path, monkeypatch)))

    assert client.get("/v1/apps/not-real").status_code == 404
    response = client.post(
        "/v1/apps/minem/capabilities/shell.exec",
        json={"arguments": {"command": "rm -rf /"}},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "capability is not declared by this application"


def test_project_overview_and_provenance_connect_source_to_memory(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    client = TestClient(create_app(manager))
    manager.app_assets("minem", asset_type="page")
    source = manager.sensory_store.list(source_type="minem")[0]
    task_id = manager.governance_store.create_task(
        [source.record_id], model="test-model", prompt_version="test-v1"
    )
    candidate = manager.governance_store.add_candidate(
        task_id=task_id,
        content="Smallink architecture is maintained in MineM.",
        memory_type="artifact_summary",
        scope=Scope.WORKSPACE,
        workspace=source.project_path,
        session_id=None,
        model="test-model",
        prompt_version="test-v1",
        source_ids=[source.record_id],
        confidence=0.9,
    )
    manager.decide_memory_candidate(candidate.candidate_id, {"action": "accept"})

    overview = client.get("/v1/projects/system:minem/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["metrics"]["source_records"] == 1
    assert payload["metrics"]["app_assets"] == 1
    assert payload["metrics"]["memory_candidates"] == 1
    assert payload["metrics"]["memories"] == 1
    assert payload["memories"][0]["key"] == "artifact_summary"

    provenance = client.get(
        f"/v1/sensory-records/{source.record_id}/provenance"
    )
    assert provenance.status_code == 200
    chain = provenance.json()
    assert chain["source"]["record_id"] == source.record_id
    assert chain["candidates"][0]["candidate_id"] == candidate.candidate_id
    assert chain["decisions"][0]["action"] == "accept"
    assert chain["memories"][0]["content"].startswith("Smallink architecture")
