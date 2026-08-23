from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from smallink.apps import SQLiteAppStore, builtin_app_registry
from smallink.conversations import ConversationStore
from smallink.knowledge import SQLiteKnowledgeStore
from smallink.sensory import SQLiteSensoryStore
from smallink.server.services.app_projects import AppProjectService
from smallink.sessions import SessionRecord


class FakeAppAdapter:
    def inspect(self) -> dict[str, Any]:
        return {
            "app_installed": True,
            "cli_available": True,
            "health": "running",
            "runtime_url": "http://127.0.0.1:8790",
        }

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "app_installed": True,
            "cli_available": True,
            "health": "running",
            "app_version": "0.5.0",
            "api_version": "minem.cli/v1",
        }

    def list_assets(self, asset_type: str = "all", limit: int = 30) -> dict[str, Any]:
        return {"ok": True, "assets": [self._asset()], "count": 1}

    def search_assets(
        self, query: str, asset_type: str = "all", limit: int = 10
    ) -> dict[str, Any]:
        return {"ok": True, "results": [self._asset()], "count": 1}

    def invoke(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        asset = self._asset()
        asset["title"] = arguments.get("name", asset["title"])
        return {"ok": True, "command": capability, "resource": asset}

    @staticmethod
    def _asset() -> dict[str, Any]:
        return {
            "id": "page-1",
            "code": "CTRL-PAGE-001",
            "type": "page",
            "title": "Smallink architecture",
            "previewUrl": "http://127.0.0.1:8790/assets/page-1",
        }


class FakeGovernanceStore:
    def source_summary(self, project_path: str) -> dict[str, Any]:
        return {
            "candidates": {"pending": 1},
            "candidate_total": 1,
            "memory_types": {"artifact_summary": 1},
            "memory_total": 1,
        }

    def project_items(
        self, project_path: str, *, limit: int = 100
    ) -> dict[str, Any]:
        return {
            "candidates": [{"candidate_id": "candidate-1"}],
            "memories": [{"id": 1, "key": "artifact_summary"}],
        }


class ServiceHarness:
    def __init__(self, root: Path) -> None:
        self.base = root / "data"
        self.session_store = ConversationStore(self.base)
        database = self.base / "link.db"
        self.app_store = SQLiteAppStore(database)
        self.sensory_store = SQLiteSensoryStore(database)
        self.knowledge_store = SQLiteKnowledgeStore(database)
        self.adapter = FakeAppAdapter()
        self.connected: list[str] = []
        self.disconnected: list[str] = []
        self.tasks: list[dict[str, Any]] = []
        self.service = AppProjectService(
            data_base=self.base,
            app_registry=builtin_app_registry(),
            app_store=self.app_store,
            session_store=self.session_store,
            sensory_store=self.sensory_store,
            knowledge_store=self.knowledge_store,
            governance_store=FakeGovernanceStore(),
            app_adapter_resolver=(
                lambda app_id: self.adapter if app_id == "minem" else None
            ),
            connect_app=self.connect_app,
            disconnect_app=self.disconnect_app,
            list_sessions=self.list_sessions,
            list_runtime_tasks=self.list_runtime_tasks,
            now=lambda: "2026-08-23T00:00:00+00:00",
        )

    def connect_app(self, connector_id: str) -> dict[str, Any]:
        self.connected.append(connector_id)
        return {
            "ok": True,
            "app_version": "0.5.0",
            "api_version": "minem.cli/v1",
        }

    def disconnect_app(self, connector_id: str) -> dict[str, Any]:
        self.disconnected.append(connector_id)
        return {"ok": True}

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": record.session_id,
                "workspace": record.workspace,
                "project_id": record.project_id,
            }
            for record in self.session_store.list()
            if not record.session_id.startswith("__")
        ]

    def list_runtime_tasks(
        self, *, limit: int = 100, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            task
            for task in self.tasks
            if project_id is None or task.get("project_id") == project_id
        ][:limit]

    def close(self) -> None:
        self.knowledge_store.close()
        self.sensory_store.close()
        self.app_store.close()
        self.session_store.close()


@pytest.fixture
def harness(tmp_path: Path):
    value = ServiceHarness(tmp_path)
    try:
        yield value
    finally:
        value.close()


def test_builtin_bootstrap_and_app_lifecycle_are_preserved(harness: ServiceHarness):
    service = harness.service
    service._ensure_builtin_app_projects()
    service._ensure_builtin_app_projects()

    projects = harness.session_store.list_projects()
    assert {project.project_id for project in projects} == {
        "system:minem",
        "system:bwf",
    }
    minem_project = harness.session_store.get_project("system:minem")
    assert minem_project is not None
    assert minem_project.project_type == "system_app"
    assert minem_project.owner_app_id == "minem"
    assert minem_project.pinned is True
    assert Path(minem_project.workspace_path).is_dir()

    descriptor = service.app_descriptor("minem")
    assert descriptor["runtime"]["health"] == "running"
    assert descriptor["instance"]["runtime_state"] == "available"
    assert service.check_app("minem")["result"]["api_version"] == "minem.cli/v1"

    assert service.disable_app("minem")["ok"] is True
    assert harness.disconnected == ["minem"]
    assert service.get_project("system:minem")["status"] == "paused"
    assert service.enable_app("minem")["ok"] is True
    assert harness.connected == ["minem"]
    assert service.get_project("system:minem")["status"] == "active"

    with pytest.raises(KeyError):
        service.app_descriptor("not-real")
    with pytest.raises(ValueError, match="adapter is not available"):
        service.enable_app("bwf")


def test_app_results_create_provenance_and_stable_asset_refs(
    harness: ServiceHarness,
):
    service = harness.service

    first = service.app_assets("minem", asset_type="page", session_id="s1")
    second = service.app_assets("minem", query="architecture")

    assert first["items"][0]["code"] == "CTRL-PAGE-001"
    assert first["smallink"]["sensory_record_id"].startswith("sensory-")
    assert second["project_id"] == "system:minem"
    assert harness.sensory_store.count(source_type="minem") == 2
    refs = harness.app_store.list_assets("minem", project_id="system:minem")
    assert len(refs) == 1
    assert refs[0]["external_asset_id"] == "page-1"
    assert harness.knowledge_store.count(project_id="system:minem") == 1
    assert len(service.app_activity("minem")) == 2

    renamed = service.invoke_app_capability(
        "minem", "asset.rename", {"name": "Renamed"}
    )
    assert renamed["resource"]["title"] == "Renamed"
    with pytest.raises(ValueError, match="not declared"):
        service.invoke_app_capability("minem", "shell.exec", {})


def test_project_crud_validates_and_retroactively_links_sessions(
    harness: ServiceHarness, tmp_path: Path
):
    service = harness.service
    workspace = tmp_path / "project"
    workspace.mkdir()
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    harness.session_store.save(
        SessionRecord(
            session_id="matching",
            workspace=str(workspace.resolve()),
            model="model",
            mode="interactive",
        )
    )
    harness.session_store.save(
        SessionRecord(
            session_id="other",
            workspace=str(other_workspace.resolve()),
            model="model",
            mode="interactive",
        )
    )

    assert service.create_project({}) == {
        "ok": False,
        "error": "workspace_path required",
    }
    assert service.create_project({"workspace_path": str(tmp_path / "missing")}) == {
        "ok": False,
        "error": "directory does not exist",
    }
    created = service.create_project(
        {"workspace_path": str(workspace), "name": "Project"}
    )
    project_id = created["project"]["project_id"]
    assert harness.session_store.load("matching").project_id == project_id
    assert harness.session_store.load("other").project_id is None
    duplicate = service.create_project({"workspace_path": str(workspace)})
    assert duplicate == {
        "ok": False,
        "error": "project already exists for this directory",
        "project_id": project_id,
    }

    updated = service.update_project(project_id, {"name": "Renamed", "pinned": True})
    assert updated["project"]["name"] == "Renamed"
    assert updated["project"]["session_count"] == 1
    assert service.project_sessions(project_id)[0]["session_id"] == "matching"
    assert service.delete_project(project_id) == {"ok": True}
    assert harness.session_store.load("matching").project_id is None
    assert service.delete_project(project_id) == {
        "ok": False,
        "error": "project not found",
    }

    service._ensure_builtin_app_projects()
    assert service.delete_project("system:minem") == {
        "ok": False,
        "error": "system application projects cannot be deleted",
    }


def test_project_overview_aggregates_injected_domains(harness: ServiceHarness):
    service = harness.service
    service._ensure_builtin_app_projects()
    project = service.get_project("system:minem")
    assert project is not None
    harness.session_store.save(
        SessionRecord(
            session_id="project-session",
            workspace=project["workspace_path"],
            model="model",
            mode="interactive",
            project_id="system:minem",
        )
    )
    harness.tasks.append({"task_id": "task-1", "project_id": "system:minem"})
    service.app_assets("minem", asset_type="page")

    overview = service.project_overview("system:minem")

    assert overview is not None
    assert overview["metrics"] == {
        "sessions": 1,
        "tasks": 1,
        "source_records": 1,
        "pending_governance": 1,
        "memory_candidates": 1,
        "memories": 1,
        "app_assets": 1,
        "knowledge": 1,
    }
    assert overview["sessions"][0]["session_id"] == "project-session"
    assert overview["source_records"][0]["source_type"] == "minem"
    assert overview["memory_types"] == {"artifact_summary": 1}
    assert overview["app_assets"][0]["external_asset_id"] == "page-1"
    assert service.project_overview("missing") is None
