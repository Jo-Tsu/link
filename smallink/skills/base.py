"""Skill discovery, cataloguing, and progressive loading.

`SKILL.md` remains the source of truth. The runtime receives only the effective
name/description catalog, while Skill Hub can inspect every discovered variant and load
full instructions on demand.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import aisuite as ai
import yaml


@dataclass(frozen=True)
class SkillSource:
    directory: Path
    source: str
    source_label: str
    scope: str


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""
    path: Optional[str] = None
    allowed_tools: list[str] = field(default_factory=list)
    id: str = ""
    display_name: str = ""
    short_description: str = ""
    source: str = "custom"
    source_label: str = "Custom"
    scope: str = "user"
    category: str = "General"
    tags: list[str] = field(default_factory=list)
    active: bool = False
    shadowed_by: Optional[str] = None
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    resources: dict[str, int] = field(
        default_factory=lambda: {
            "scripts": 0,
            "references": 0,
            "assets": 0,
            "other": 0,
        }
    )

    def to_dict(self, *, include_instructions: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "short_description": self.short_description or self.description,
            "path": self.path,
            "allowed_tools": self.allowed_tools,
            "source": self.source,
            "source_label": self.source_label,
            "scope": self.scope,
            "category": self.category,
            "tags": self.tags,
            "active": self.active,
            "shadowed_by": self.shadowed_by,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "resources": self.resources,
        }
        if include_instructions:
            result["instructions"] = self.instructions
        return result


def default_skill_sources(
    workspace: Optional[str | Path] = None,
    *,
    state_root: Optional[str | Path] = None,
) -> list[SkillSource]:
    """Return every supported Skill source in increasing precedence order."""
    home = Path.home()
    sources = [
        SkillSource(
            Path(__file__).parent / "builtin", "builtin", "Smallink built-in", "builtin"
        ),
        SkillSource(
            home / ".agents" / "skills", "agents", "Shared agent skills", "user"
        ),
        SkillSource(home / ".codex" / "skills", "codex", "Codex skills", "user"),
    ]
    if state_root is not None:
        sources.append(
            SkillSource(
                Path(state_root).expanduser() / "skills",
                "smallink",
                "Smallink user skills",
                "user",
            )
        )
    if workspace is not None:
        root = Path(workspace).expanduser()
        sources.extend(
            [
                SkillSource(
                    root / ".link" / "skills",
                    "project_legacy",
                    "Project skills (compatible)",
                    "project",
                ),
                SkillSource(
                    root / ".smallink" / "skills",
                    "project",
                    "Project skills",
                    "project",
                ),
            ]
        )
    return sources


class SkillLoader:
    def __init__(self, dirs: list[str | Path | SkillSource]) -> None:
        self._entries = list(dirs)
        self.refresh()

    def refresh(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._inventory: list[Skill] = []
        self._by_id: dict[str, Skill] = {}
        self._seen_directories: set[str] = set()
        for entry in self._entries:
            source = (
                entry
                if isinstance(entry, SkillSource)
                else SkillSource(Path(entry), "custom", "Custom", "user")
            )
            self._discover(source)
        self._mark_effective()

    def _discover(self, source: SkillSource) -> None:
        directory = source.directory.expanduser()
        try:
            canonical = str(directory.resolve())
        except OSError:
            canonical = str(directory.absolute())
        if canonical in self._seen_directories:
            return
        self._seen_directories.add(canonical)
        if not directory.is_dir():
            return
        for sub in sorted(directory.iterdir()):
            md = sub / "SKILL.md"
            if not md.is_file():
                continue
            skill = _parse_skill(md, source)
            self._inventory.append(skill)
            self._by_id[skill.id] = skill
            if skill.valid:
                self._skills[skill.name] = skill

    def _mark_effective(self) -> None:
        for skill in self._inventory:
            effective = self._skills.get(skill.name)
            skill.active = skill.valid and effective is skill
            skill.shadowed_by = (
                effective.id if skill.valid and effective is not None and effective is not skill else None
            )

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def get_by_id(self, skill_id: str) -> Optional[Skill]:
        return self._by_id.get(skill_id)

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": skill.name, "description": _context_description(skill.description)}
            for skill in self._skills.values()
        ]

    def inventory(self) -> list[dict[str, Any]]:
        return [skill.to_dict() for skill in self._inventory]

    def detail(self, skill_id: str) -> Optional[dict[str, Any]]:
        skill = self.get_by_id(skill_id)
        return skill.to_dict(include_instructions=True) if skill else None

    def summary(self) -> dict[str, int]:
        sources = {skill.source for skill in self._inventory}
        return {
            "total": len(self._inventory),
            "active": sum(1 for skill in self._inventory if skill.active),
            "issues": sum(
                1
                for skill in self._inventory
                if not skill.valid or bool(skill.warnings)
            ),
            "sources": len(sources),
        }


def _stable_id(path: Path) -> str:
    canonical = str(path.expanduser().resolve())
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"skill_{digest}"


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _context_description(value: str, limit: int = 320) -> str:
    """Keep the always-in-context catalog useful without letting verbose metadata dominate."""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _resource_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in ("scripts", "references", "assets"):
        directory = root / name
        counts[name] = (
            sum(1 for item in directory.rglob("*") if item.is_file())
            if directory.is_dir()
            else 0
        )
    counts["other"] = sum(
        1
        for item in root.rglob("*")
        if item.is_file()
        and item.relative_to(root) not in {Path("SKILL.md"), Path("agents/openai.yaml")}
        and item.relative_to(root).parts[0] not in {"scripts", "references", "assets"}
    )
    return counts


def _interface_metadata(root: Path) -> tuple[dict[str, Any], list[str]]:
    path = root / "agents" / "openai.yaml"
    if not path.is_file():
        return {}, []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        interface = raw.get("interface", {}) if isinstance(raw, dict) else {}
        if not isinstance(interface, dict):
            return {}, ["agents/openai.yaml interface must be an object"]
        return interface, []
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return {}, [f"agents/openai.yaml could not be read: {exc}"]


def _parse_skill(md: Path, source: Optional[SkillSource] = None) -> Skill:
    source = source or SkillSource(md.parent.parent, "custom", "Custom", "user")
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        text = ""
        errors.append(f"SKILL.md could not be read: {exc}")

    data: dict[str, Any] = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        except StopIteration:
            errors.append("SKILL.md frontmatter is not closed")
        else:
            try:
                loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    errors.append("SKILL.md frontmatter must be a YAML object")
            except yaml.YAMLError as exc:
                errors.append(f"SKILL.md frontmatter is invalid YAML: {exc}")
            body = "\n".join(lines[end + 1 :]).strip()
    else:
        errors.append("SKILL.md must start with YAML frontmatter")

    folder_name = md.parent.name
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        errors.append("name is required")
        name = folder_name
    if not description:
        errors.append("description is required")
    if name != folder_name:
        warnings.append(f"folder name '{folder_name}' differs from skill name '{name}'")

    allowed = _list_value(data.get("allowed-tools", data.get("allowed_tools", [])))
    tags = _list_value(data.get("tags", []))
    interface, interface_warnings = _interface_metadata(md.parent)
    warnings.extend(interface_warnings)
    display_name = str(interface.get("display_name") or "").strip()
    short_description = str(interface.get("short_description") or "").strip()
    category = str(data.get("category") or interface.get("category") or "General").strip()

    return Skill(
        id=_stable_id(md.parent),
        name=name,
        description=description,
        instructions=body,
        path=str(md.parent.resolve()),
        allowed_tools=allowed,
        display_name=display_name or name.replace("-", " ").title(),
        short_description=short_description or description,
        source=source.source,
        source_label=source.source_label,
        scope=source.scope,
        category=category or "General",
        tags=tags,
        valid=not errors,
        errors=errors,
        warnings=warnings,
        resources=_resource_counts(md.parent),
    )


def skill_catalog_text(loader: SkillLoader) -> str:
    catalog = loader.catalog()
    if not catalog:
        return ""
    lines = [f"- {item['name']}: {item['description']}" for item in catalog]
    return (
        "Available skills — call load_skill(name) to load one's full instructions when "
        "it's relevant to the task:\n" + "\n".join(lines)
    )


def skill_tools(loader: SkillLoader, store: Any = None) -> list:
    def load_skill(name: str) -> dict:
        """Load a skill's full instructions + resources path by name."""
        skill = loader.get(name)
        if skill is None:
            return {"error": f"unknown skill: {name}", "available": loader.names()}
        return {
            "name": skill.name,
            "instructions": skill.instructions,
            "resources_path": skill.path,
        }

    tools = [
        ai.tool(
            load_skill,
            metadata=ai.ToolMetadata(
                category="skills", risk_level="low", capabilities=["load_skill"]
            ),
        )
    ]
    if store is not None:
        def create_skill(
            name: str,
            description: str,
            instructions: str,
            display_name: str = "",
            short_description: str = "",
            scope: str = "user",
        ) -> dict:
            """Create a reusable Skill after gathering enough detail and showing a preview."""
            try:
                skill = store.create(
                    name=name,
                    description=description,
                    instructions=instructions,
                    display_name=display_name,
                    short_description=short_description,
                    scope=scope,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            loader.refresh()
            return {
                "ok": True,
                "skill": skill.to_dict(include_instructions=True),
                "message": f"Skill '{skill.name}' was created and is now available.",
            }

        tools.append(
            ai.tool(
                create_skill,
                metadata=ai.ToolMetadata(
                    category="skills",
                    risk_level="medium",
                    requires_approval=True,
                    capabilities=["create_skill"],
                ),
            )
        )
    return tools
