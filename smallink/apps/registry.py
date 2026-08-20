"""Declarative application registry.

Applications are user-facing domain products. Connectors remain implementation details of an
application runtime, so the client never has to scatter checks for a particular connector name.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class AppManifest:
    schema_version: str
    app_id: str
    name: str
    description: str
    icon: str
    runtime_kind: str
    connector_id: str
    system_project_id: str
    system_project_name: str
    default_agent: str
    capabilities: tuple[str, ...]
    memory_types: tuple[str, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        value["memory_types"] = list(self.memory_types)
        return value


class AppRegistry:
    def __init__(self, manifests: tuple[AppManifest, ...]) -> None:
        self._items: dict[str, AppManifest] = {}
        project_ids: set[str] = set()
        for manifest in manifests:
            if manifest.schema_version != "smallink.app/v1":
                raise ValueError(f"unsupported app schema: {manifest.schema_version}")
            if not manifest.app_id or manifest.app_id in self._items:
                raise ValueError(f"duplicate app id: {manifest.app_id}")
            if manifest.system_project_id in project_ids:
                raise ValueError(f"duplicate app project: {manifest.system_project_id}")
            if not manifest.capabilities:
                raise ValueError(f"app has no capabilities: {manifest.app_id}")
            self._items[manifest.app_id] = manifest
            project_ids.add(manifest.system_project_id)

    def list(self) -> list[AppManifest]:
        return list(self._items.values())

    def get(self, app_id: str) -> Optional[AppManifest]:
        return self._items.get(app_id)


MINEM_MANIFEST = AppManifest(
    schema_version="smallink.app/v1",
    app_id="minem",
    name="MineM",
    description="Search, organize, create, and reuse materials through the local MineM app.",
    icon="minem",
    runtime_kind="hybrid_local_app",
    connector_id="minem",
    system_project_id="system:minem",
    system_project_name="MineM",
    default_agent="link",
    capabilities=(
        "asset.list",
        "asset.search",
        "asset.get",
        "asset.versions",
        "asset.lineage",
        "asset.rename",
        "asset.delete",
        "import.report",
        "import.page",
        "page.build",
        "case.brief",
        "case.import",
        "task.list",
        "task.get",
        "task.wait",
        "report.create",
        "report.get",
        "report.pages",
        "report.page.add",
        "report.page.replace",
        "report.page.move",
        "report.page.hide",
        "report.page.show",
        "report.page.remove",
        "report.export",
    ),
    memory_types=(
        "user_preference",
        "project_context",
        "product_decision",
        "reasoning_process",
        "open_question",
        "reusable_pattern",
        "work_habit",
        "artifact_summary",
        "document_insight",
    ),
)


def builtin_app_registry() -> AppRegistry:
    return AppRegistry((MINEM_MANIFEST,))
