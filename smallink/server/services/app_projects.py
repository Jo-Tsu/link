"""Application-center and project-domain orchestration.

The service owns the App/Project behavior that historically lived on
``SessionManager``.  Store and runtime dependencies are injected explicitly so
the domain logic can be exercised without constructing the full server manager.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ...apps import AppManifest, AppRegistry
from ...projects import ProjectRecord
from ...runtime import sensory_safe


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppProjectService:
    """Coordinate registered applications and their project read models."""

    def __init__(
        self,
        *,
        data_base: str | Path,
        app_registry: AppRegistry,
        app_store: Any,
        session_store: Any,
        sensory_store: Any,
        knowledge_store: Any,
        governance_store: Any,
        app_adapter_resolver: Callable[[str], Any],
        connect_app: Callable[[str], dict[str, Any]],
        disconnect_app: Callable[[str], Any],
        list_sessions: Callable[[], list[dict[str, Any]]],
        list_runtime_tasks: Callable[..., list[dict[str, Any]]],
        now: Callable[[], str] = _now_iso,
        safe_payload: Callable[[Any], Any] = sensory_safe,
    ) -> None:
        self._data_base = Path(data_base).expanduser()
        self.app_registry = app_registry
        self.app_store = app_store
        self.session_store = session_store
        self.sensory_store = sensory_store
        self.knowledge_store = knowledge_store
        self.governance_store = governance_store
        self._app_adapter_resolver = app_adapter_resolver
        self._connect_app = connect_app
        self._disconnect_app = disconnect_app
        self._list_sessions = list_sessions
        self._list_runtime_tasks = list_runtime_tasks
        self._now = now
        self._safe_payload = safe_payload

    def _ensure_builtin_app_projects(self) -> None:
        for manifest in self.app_registry.list():
            self._ensure_app_project(manifest)
            self.app_store.ensure_instance(manifest.app_id, enabled=True)

    def _ensure_app_project(self, manifest: AppManifest) -> ProjectRecord:
        existing = self.session_store.get_project_by_system_key(
            manifest.system_project_id
        )
        if existing is not None:
            return existing
        by_id = self.session_store.get_project(manifest.system_project_id)
        if by_id is not None:
            return by_id
        managed_workspace = self._data_base / "apps" / manifest.app_id / "workspace"
        managed_workspace.mkdir(parents=True, exist_ok=True)
        project = ProjectRecord(
            project_id=manifest.system_project_id,
            name=manifest.system_project_name,
            icon="S",
            workspace_path=str(managed_workspace.resolve()),
            description=manifest.description,
            status="active",
            default_agent=manifest.default_agent,
            pinned=True,
            sort_order=-100,
            project_type="system_app",
            owner_app_id=manifest.app_id,
            system_key=manifest.system_project_id,
        )
        self.session_store.create_project(project)
        return project

    def _app_manifest(self, app_id: str) -> AppManifest:
        manifest = self.app_registry.get(app_id)
        if manifest is None:
            raise KeyError(app_id)
        return manifest

    def _app_adapter(self, app_id: str) -> Any:
        adapter = self._app_adapter_resolver(app_id)
        if adapter is None:
            raise ValueError("application adapter is not available")
        return adapter

    def _app_status_payload(self, app_id: str) -> dict[str, Any]:
        self._app_manifest(app_id)
        if app_id != "minem":
            return {
                "app_installed": False,
                "cli_available": False,
                "health": "offline",
            }
        inspected = self._app_adapter(app_id).inspect()
        self.app_store.update_instance(
            app_id,
            install_state=(
                "installed"
                if inspected.get("app_installed") or inspected.get("cli_available")
                else "not_installed"
            ),
            runtime_state=(
                "available" if inspected.get("health") == "running" else "offline"
            ),
            status=inspected,
            last_checked_at=self._now(),
        )
        return inspected

    def app_descriptor(
        self, app_id: str, *, inspect_runtime: bool = True
    ) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        project = self._ensure_app_project(manifest)
        instance = self.app_store.ensure_instance(app_id)
        status = (
            self._app_status_payload(app_id)
            if inspect_runtime
            else instance.get("status", {})
        )
        instance = self.app_store.get_instance(app_id) or instance
        return {
            **manifest.to_dict(),
            "instance": instance,
            "runtime": status,
            "project": self.get_project(project.project_id),
        }

    def list_apps(self) -> list[dict[str, Any]]:
        return [
            self.app_descriptor(item.app_id) for item in self.app_registry.list()
        ]

    def enable_app(self, app_id: str) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        self._ensure_app_project(manifest)
        if app_id != "minem":
            raise ValueError("application adapter is not available")
        result = self._connect_app(manifest.connector_id)
        self.app_store.update_instance(
            app_id,
            enabled=bool(result.get("ok")),
            install_state="installed" if result.get("ok") else "not_installed",
            runtime_state="available" if result.get("ok") else "error",
            app_version=result.get("app_version"),
            protocol_version=result.get("api_version"),
            status=result,
            last_checked_at=self._now(),
            last_error=None if result.get("ok") else result.get("error"),
        )
        if result.get("ok"):
            self.session_store.update_project(
                manifest.system_project_id, status="active"
            )
        return {
            "ok": bool(result.get("ok")),
            "app": self.app_descriptor(app_id, inspect_runtime=False),
            "result": result,
        }

    def check_app(self, app_id: str) -> dict[str, Any]:
        self._app_manifest(app_id)
        result = (
            self._app_adapter(app_id).status()
            if app_id == "minem"
            else {"ok": False, "error": "adapter unavailable"}
        )
        self.app_store.update_instance(
            app_id,
            install_state=(
                "installed"
                if result.get("app_installed") or result.get("cli_available")
                else "not_installed"
            ),
            runtime_state="available" if result.get("ok") else "error",
            app_version=result.get("app_version"),
            protocol_version=result.get("api_version"),
            status=result,
            last_checked_at=self._now(),
            last_error=None if result.get("ok") else result.get("error"),
        )
        return {
            "ok": bool(result.get("ok")),
            "app": self.app_descriptor(app_id, inspect_runtime=False),
            "result": result,
        }

    def disable_app(self, app_id: str) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        self._disconnect_app(manifest.connector_id)
        self.app_store.update_instance(
            app_id, enabled=False, runtime_state="disabled", last_error=None
        )
        self.session_store.update_project(manifest.system_project_id, status="paused")
        return {
            "ok": True,
            "app": self.app_descriptor(app_id, inspect_runtime=False),
        }

    def _record_app_result(
        self,
        app_id: str,
        capability: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        *,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        project = self._ensure_app_project(manifest)
        run = self.app_store.record_capability_run(
            app_id=app_id,
            project_id=project.project_id,
            session_id=session_id,
            capability=capability,
            arguments=self._safe_payload(arguments),
            result=self._safe_payload(result),
        )
        sensory = self.sensory_store.add(
            source_type=app_id,
            connector_id=manifest.connector_id,
            content_type="app_capability_result",
            raw_content={
                "capability": capability,
                "arguments": self._safe_payload(arguments),
                "result": self._safe_payload(result),
            },
            external_id=run["capability_run_id"],
            project_path=project.workspace_path,
            conversation_id=session_id,
            sensitivity="private",
            metadata={
                "app_id": app_id,
                "project_id": project.project_id,
                "capability": capability,
                "capability_run_id": run["capability_run_id"],
            },
            source_locator=f"{app_id}://capability/{run['capability_run_id']}",
        )
        self._capture_app_assets(
            app_id, project.project_id, result, sensory.record_id
        )
        return {
            **result,
            "smallink": {**run, "sensory_record_id": sensory.record_id},
        }

    def _capture_app_assets(
        self, app_id: str, project_id: str, payload: Any, sensory_record_id: str
    ) -> None:
        seen: set[tuple[str, str]] = set()

        def visit(
            value: Any, inherited_links: Optional[dict[str, Any]] = None
        ) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item, inherited_links)
                return
            if not isinstance(value, dict):
                return
            links = (
                value.get("links")
                if isinstance(value.get("links"), dict)
                else inherited_links
            )
            asset_type = str(value.get("type") or value.get("assetType") or "").lower()
            code = str(value.get("code") or value.get("assetCode") or "").strip()
            external_id = str(value.get("id") or value.get("assetId") or "").strip()
            looks_like_asset = asset_type in {
                "report",
                "page",
                "resource",
                "case",
                "single_html",
                "html",
                "ppt",
            }
            looks_like_asset = looks_like_asset or code.startswith(
                ("RPT-", "CTRL-", "RES-")
            )
            if looks_like_asset and (external_id or code):
                stable_id = external_id or code
                version_id = str(
                    value.get("versionId")
                    or value.get("version_id")
                    or value.get("version")
                    or ""
                )
                key = (stable_id, version_id)
                if key not in seen:
                    seen.add(key)
                    preview = (
                        value.get("previewUrl")
                        or value.get("preview")
                        or value.get("url")
                    )
                    if not preview and links:
                        preview = links.get("preview")
                    digest = hashlib.sha256(
                        json.dumps(
                            value, ensure_ascii=False, sort_keys=True, default=str
                        ).encode("utf-8")
                    ).hexdigest()
                    self.app_store.upsert_asset(
                        app_id=app_id,
                        project_id=project_id,
                        external_asset_id=stable_id,
                        external_code=code or None,
                        asset_type=asset_type or None,
                        version_id=version_id,
                        title=str(value.get("title") or value.get("name") or "")
                        or None,
                        preview_ref=str(preview) if preview else None,
                        content_hash=digest,
                        sensory_record_id=sensory_record_id,
                    )
                    self.knowledge_store.upsert(
                        project_id=project_id,
                        source_type=f"app:{app_id}",
                        external_id=stable_id,
                        title=str(
                            value.get("title")
                            or value.get("name")
                            or code
                            or stable_id
                        ),
                        content=json.dumps(
                            value, ensure_ascii=False, sort_keys=True, default=str
                        ),
                        source_record_id=sensory_record_id,
                        metadata={
                            "app_id": app_id,
                            "asset_type": asset_type or None,
                            "external_code": code or None,
                            "version_id": version_id or None,
                            "source_locator": f"{app_id}://asset/{stable_id}",
                        },
                    )
            for child in value.values():
                if child is not links:
                    visit(child, links)

        visit(payload)

    def app_assets(
        self,
        app_id: str,
        *,
        query: str = "",
        asset_type: str = "all",
        limit: int = 60,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        if app_id != "minem":
            raise ValueError("application adapter is not available")
        adapter = self._app_adapter(app_id)
        arguments = {"query": query, "type": asset_type, "limit": limit}
        if query.strip():
            result = adapter.search_assets(
                query, asset_type=asset_type, limit=limit
            )
            items = result.get("results", [])
            capability = "asset.search"
        else:
            result = adapter.list_assets(asset_type=asset_type, limit=limit)
            items = result.get("assets", [])
            capability = "asset.list"
        recorded = self._record_app_result(
            app_id, capability, arguments, result, session_id=session_id
        )
        return {
            **recorded,
            "items": items,
            "project_id": manifest.system_project_id,
        }

    def invoke_app_capability(
        self,
        app_id: str,
        capability: str,
        arguments: dict[str, Any],
        *,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        manifest = self._app_manifest(app_id)
        if capability not in manifest.capabilities:
            raise ValueError("capability is not declared by this application")
        if app_id != "minem":
            raise ValueError("application adapter is not available")
        result = self._app_adapter(app_id).invoke(capability, arguments)
        return self._record_app_result(
            app_id, capability, arguments, result, session_id=session_id
        )

    def app_activity(
        self, app_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        self._app_manifest(app_id)
        return self.app_store.list_runs(app_id, limit=limit)

    @staticmethod
    def _project_payload(
        project: ProjectRecord, session_count: int
    ) -> dict[str, Any]:
        return {
            "project_id": project.project_id,
            "name": project.name,
            "icon": project.icon,
            "workspace_path": project.workspace_path,
            "description": project.description,
            "status": project.status,
            "default_agent": project.default_agent,
            "default_model": project.default_model,
            "pinned": project.pinned,
            "sort_order": project.sort_order,
            "project_type": project.project_type,
            "owner_app_id": project.owner_app_id,
            "system_key": project.system_key,
            "disabled_at": project.disabled_at,
            "session_count": session_count,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    def list_projects(
        self, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        return [
            self._project_payload(
                project, self.session_store.project_session_count(project.project_id)
            )
            for project in self.session_store.list_projects(status=status)
        ]

    def create_project(self, body: dict[str, Any]) -> dict[str, Any]:
        workspace_path = body.get("workspace_path", "")
        if not workspace_path:
            return {"ok": False, "error": "workspace_path required"}
        path = Path(workspace_path).expanduser()
        if not path.is_dir():
            return {"ok": False, "error": "directory does not exist"}
        resolved = str(path.resolve())

        existing = self.session_store.get_project_by_workspace(resolved)
        if existing:
            return {
                "ok": False,
                "error": "project already exists for this directory",
                "project_id": existing.project_id,
            }

        project_id = str(uuid.uuid4())
        record = ProjectRecord(
            project_id=project_id,
            name=body.get("name") or path.name,
            icon=body.get("icon", "\U0001f4c1"),
            workspace_path=resolved,
            description=body.get("description", ""),
            status="active",
            default_agent=body.get("default_agent"),
            default_model=body.get("default_model"),
        )
        self.session_store.create_project(record)
        for session in self.session_store.list():
            if session.workspace == resolved and not session.project_id:
                self.session_store.set_session_project(session.session_id, project_id)
        return {"ok": True, "project": self.get_project(project_id)}

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        project = self.session_store.get_project(project_id)
        if not project:
            return None
        return self._project_payload(
            project, self.session_store.project_session_count(project.project_id)
        )

    def update_project(
        self, project_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        ok = self.session_store.update_project(project_id, **body)
        if not ok:
            return {"ok": False, "error": "project not found or no changes"}
        return {"ok": True, "project": self.get_project(project_id)}

    def delete_project(self, project_id: str) -> dict[str, Any]:
        project = self.session_store.get_project(project_id)
        if project is not None and project.project_type == "system_app":
            return {
                "ok": False,
                "error": "system application projects cannot be deleted",
            }
        ok = self.session_store.delete_project(project_id)
        if not ok:
            return {"ok": False, "error": "project not found"}
        return {"ok": True}

    def project_sessions(self, project_id: str) -> list[dict[str, Any]]:
        return [
            session
            for session in self._list_sessions()
            if session.get("project_id") == project_id
        ]

    def project_overview(self, project_id: str) -> Optional[dict[str, Any]]:
        project = self.get_project(project_id)
        if project is None:
            return None
        workspace = str(project["workspace_path"])
        sessions = self.project_sessions(project_id)
        tasks = self._list_runtime_tasks(limit=100, project_id=project_id)
        source_records = self.sensory_store.list(project_path=workspace, limit=100)
        source_statuses = {
            status: self.sensory_store.count(
                project_path=workspace, governance_status=status
            )
            for status in (
                "pending",
                "processing",
                "processed",
                "skipped",
                "failed",
            )
        }
        source_total = self.sensory_store.count(project_path=workspace)
        governance = self.governance_store.source_summary(workspace)
        governed_items = self.governance_store.project_items(workspace, limit=100)
        knowledge = self.knowledge_store.list(project_id=project_id, limit=100)
        app_assets: list[dict[str, Any]] = []
        app_asset_total = 0
        owner_app_id = project.get("owner_app_id")
        if owner_app_id:
            app_assets = self.app_store.list_assets(
                str(owner_app_id), project_id=project_id, limit=100
            )
            app_asset_total = self.app_store.count_assets(
                str(owner_app_id), project_id=project_id
            )
        return {
            "project": project,
            "metrics": {
                "sessions": len(sessions),
                "tasks": len(tasks),
                "source_records": source_total,
                "pending_governance": source_statuses["pending"],
                "memory_candidates": governance["candidate_total"],
                "memories": governance["memory_total"],
                "app_assets": app_asset_total,
                "knowledge": self.knowledge_store.count(project_id=project_id),
            },
            "sessions": sessions[:100],
            "tasks": tasks,
            "source_records": [record.to_dict() for record in source_records],
            "source_statuses": source_statuses,
            "candidates": governed_items["candidates"],
            "memories": governed_items["memories"],
            "memory_types": governance["memory_types"],
            "app_assets": app_assets,
            "knowledge": knowledge,
        }
