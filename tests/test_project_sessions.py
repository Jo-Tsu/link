from __future__ import annotations

from smallink.conversations import ConversationStore
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server.manager import SessionManager
from smallink.sessions import SessionRecord
from smallink.projects import ProjectRecord


class NoopProvider(ProviderClient):
    def complete(self, **kwargs) -> AssistantTurn:
        return AssistantTurn(text="")

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


def test_first_save_assigns_session_to_matching_project(tmp_path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path / "data",
        provider=NoopProvider(),
    )
    created = manager.create_project({"workspace_path": str(workspace), "name": "Project"})
    project_id = created["project"]["project_id"]

    engine = manager.get_engine("project-session", workspace=str(workspace), agent="link")
    assert engine is not None
    manager.save("project-session", engine)

    record = manager.session_store.load("project-session")
    assert record is not None
    assert record.project_id == project_id


def test_store_startup_backfills_legacy_project_session(tmp_path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = ConversationStore(tmp_path / "data")
    store.save(
        SessionRecord(
            session_id="legacy-session",
            workspace=str(workspace),
            model="model",
            mode="interactive",
        )
    )
    store.create_project(
        ProjectRecord(
            project_id="project-1",
            name="Project",
            workspace_path=str(workspace),
        )
    )
    assert store.load("legacy-session").project_id is None

    reopened = ConversationStore(tmp_path / "data")

    assert reopened.load("legacy-session").project_id == "project-1"
