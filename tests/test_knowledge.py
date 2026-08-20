from __future__ import annotations

from fastapi.testclient import TestClient

from smallink.knowledge import SQLiteKnowledgeStore
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager, create_app


class NoopProvider(ProviderClient):
    def complete(self, **kwargs) -> AssistantTurn:
        return AssistantTurn(text="")

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


def test_knowledge_store_versions_chunks_and_explains_hybrid_results(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    first = store.upsert(
        project_id="project-1",
        source_type="document",
        external_id="doc-1",
        title="Smallink product architecture",
        content="Smallink keeps MineM materials inside a system project with source provenance.",
        source_record_id="sensory-1",
    )
    duplicate = store.upsert(
        project_id="project-1",
        source_type="document",
        external_id="doc-1",
        title="Smallink product architecture",
        content="Smallink keeps MineM materials inside a system project with source provenance.",
        source_record_id="sensory-1",
    )
    assert duplicate["item_id"] == first["item_id"]
    assert duplicate["current_version"] == 1
    assert duplicate["chunk_count"] == 1

    updated = store.upsert(
        project_id="project-1",
        source_type="document",
        external_id="doc-1",
        title="Smallink 产品架构",
        content="Smallink 把 MineM 素材放在系统项目中，并保留来源链和版本。",
        source_record_id="sensory-2",
    )
    assert updated["current_version"] == 2

    result = store.search("MineM 来源链", project_id="project-1")
    assert result["strategy"] == "hybrid_lexical_v1"
    assert result["results"][0]["item_id"] == first["item_id"]
    assert result["results"][0]["citation"]["source_record_id"] == "sensory-2"
    assert result["results"][0]["score"] > 0
    assert "full-text rank" in result["results"][0]["explanation"]


def test_knowledge_api_indexes_source_searches_and_archives(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=NoopProvider())
    created = manager.create_project(
        {"workspace_path": str(workspace), "name": "Research"}
    )["project"]
    source = manager.sensory_store.add(
        source_type="files",
        content_type="document_text",
        raw_content="The retrieval design combines full-text rank with transparent source citations.",
        external_id="doc-1",
        project_path=str(workspace.resolve()),
        source_locator="file:///research/retrieval.md",
    )
    client = TestClient(create_app(manager))

    indexed = client.post(
        "/v1/knowledge/index-source",
        json={
            "record_id": source.record_id,
            "project_id": created["project_id"],
            "title": "Retrieval design",
        },
    )
    assert indexed.status_code == 200
    item = indexed.json()["item"]
    assert item["source_record_id"] == source.record_id

    search = client.get(
        "/v1/knowledge/search",
        params={"q": "transparent source citations", "project_id": created["project_id"]},
    )
    assert search.status_code == 200
    assert search.json()["results"][0]["title"] == "Retrieval design"
    assert search.json()["results"][0]["citation"]["source_locator"].endswith(
        "retrieval.md"
    )

    overview = client.get(
        f"/v1/projects/{created['project_id']}/overview"
    ).json()
    assert overview["metrics"]["knowledge"] == 1
    assert overview["knowledge"][0]["item_id"] == item["item_id"]

    archived = client.patch(
        f"/v1/knowledge/{item['item_id']}/archive", json={"archived": True}
    )
    assert archived.status_code == 200
    assert archived.json()["item"]["status"] == "archived"
    assert client.get(
        "/v1/knowledge", params={"project_id": created["project_id"]}
    ).json()["items"] == []


def test_project_agent_gets_scoped_explainable_knowledge_search(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=NoopProvider())
    project = manager.create_project(
        {"workspace_path": str(workspace), "name": "Scoped project"}
    )["project"]
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    other_project = manager.create_project(
        {"workspace_path": str(other_workspace), "name": "Other project"}
    )["project"]
    manager.knowledge_store.upsert(
        project_id=project["project_id"],
        source_type="file",
        external_id="decision.md",
        title="Architecture decision",
        content="Smallink uses Postgres as the durable personal data source.",
    )
    manager.knowledge_store.upsert(
        project_id=other_project["project_id"],
        source_type="file",
        external_id="secret.md",
        title="Other project decision",
        content="Smallink uses Chroma for this unrelated project.",
    )

    engine = manager.get_engine(
        "knowledge-session", workspace=str(workspace), agent="link"
    )

    assert engine is not None
    tool = engine.registry.get("knowledge_search")
    assert tool is not None
    result = tool.func(query="Smallink durable data source")
    assert result["project_id"] == project["project_id"]
    assert len(result["results"]) == 1
    assert "Postgres" in result["results"][0]["content"]
    assert result["results"][0]["explanation"]
    assert tool.metadata.requires_approval is False
