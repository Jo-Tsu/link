"""Validated, atomic writes for user and project Skills."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Optional

import yaml

from .base import Skill, SkillSource, _parse_skill


_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IGNORED_IMPORT_NAMES = {
    ".DS_Store",
    ".git",
    ".hg",
    ".svn",
    "Thumbs.db",
    "__MACOSX",
    "__pycache__",
    "node_modules",
}
_MAX_FILES = 200
_MAX_TOTAL_BYTES = 10 * 1024 * 1024
_MAX_DESCRIPTION_CHARS = 2_000
_MAX_INSTRUCTIONS_CHARS = 100_000


class SkillStoreError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


class SkillStore:
    """Create and import Skills through one policy-controlled storage boundary."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        workspace: Optional[str | Path] = None,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.workspace = (
            Path(workspace).expanduser().resolve() if workspace is not None else None
        )

    def create(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        display_name: str = "",
        short_description: str = "",
        scope: str = "user",
    ) -> Skill:
        name = self._validate_name(name)
        description = self._required_text(
            description, "description", _MAX_DESCRIPTION_CHARS
        )
        instructions = self._required_text(
            instructions, "instructions", _MAX_INSTRUCTIONS_CHARS
        )
        root, source = self._target(scope)
        destination = root / name
        self._ensure_available(destination)
        root.mkdir(parents=True, exist_ok=True)

        stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=root))
        try:
            frontmatter = yaml.safe_dump(
                {"name": name, "description": description},
                allow_unicode=True,
                sort_keys=False,
            ).strip()
            (stage / "SKILL.md").write_text(
                f"---\n{frontmatter}\n---\n\n{instructions.rstrip()}\n",
                encoding="utf-8",
            )
            self._write_interface(
                stage,
                display_name=display_name.strip() or name.replace("-", " ").title(),
                short_description=short_description.strip() or description,
                name=name,
            )
            stage.rename(destination)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        return self._read_written(destination, source)

    def import_path(self, source_path: str | Path, *, scope: str = "user") -> Skill:
        raw_source = Path(source_path).expanduser()
        if raw_source.is_symlink():
            raise SkillStoreError("Skill import source cannot be a symbolic link")
        if raw_source.is_file() and raw_source.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory(prefix="smallink-skill-archive-") as temp:
                source_dir = self._extract_archive(raw_source, Path(temp))
                return self._import_source_directory(source_dir, scope=scope)
        source_dir = raw_source.parent if raw_source.is_file() else raw_source
        return self._import_source_directory(source_dir, scope=scope)

    def import_directory(self, source_path: str | Path, *, scope: str = "user") -> Skill:
        """Compatibility entry point; accepts either a Skill directory or a .zip package."""
        return self.import_path(source_path, scope=scope)

    def _import_source_directory(self, source_dir: Path, *, scope: str) -> Skill:
        if not source_dir.is_dir() or not (source_dir / "SKILL.md").is_file():
            raise SkillStoreError(
                "Choose a Skill folder or .zip package containing SKILL.md"
            )

        imported = _parse_skill(
            source_dir / "SKILL.md",
            SkillSource(source_dir.parent, "import", "Imported Skill", "user"),
        )
        if not imported.valid:
            raise SkillStoreError("; ".join(imported.errors))
        name = self._validate_name(imported.name)
        root, source = self._target(scope)
        destination = root / name
        self._ensure_available(destination)
        files = self._import_files(source_dir)
        root.mkdir(parents=True, exist_ok=True)

        stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=root))
        try:
            for relative, item in files:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            if not (stage / "agents" / "openai.yaml").is_file():
                self._write_interface(
                    stage,
                    display_name=imported.display_name,
                    short_description=imported.short_description,
                    name=name,
                )
            stage.rename(destination)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        return self._read_written(destination, source)

    @staticmethod
    def _extract_archive(archive_path: Path, destination: Path) -> Path:
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SkillStoreError("The selected file is not a valid .zip package") from exc

        file_count = 0
        total_bytes = 0
        with archive:
            entries: list[tuple[zipfile.ZipInfo, Path]] = []
            seen_paths: set[tuple[str, ...]] = set()
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                relative = PurePosixPath(normalized)
                parts = relative.parts
                if (
                    relative.is_absolute()
                    or not parts
                    or any(part in {"", ".", ".."} for part in parts)
                    or ":" in parts[0]
                ):
                    raise SkillStoreError("Skill archive contains an unsafe path")
                if any(part in _IGNORED_IMPORT_NAMES for part in parts):
                    continue
                unix_mode = (info.external_attr >> 16) & 0o177777
                if stat.S_ISLNK(unix_mode):
                    raise SkillStoreError(
                        "Imported Skills cannot contain symbolic links"
                    )
                if info.flag_bits & 0x1:
                    raise SkillStoreError("Encrypted Skill archives are not supported")
                path_key = tuple(parts)
                if path_key in seen_paths:
                    raise SkillStoreError("Skill archive contains duplicate paths")
                seen_paths.add(path_key)
                file_type = stat.S_IFMT(unix_mode)
                if file_type and not info.is_dir() and file_type != stat.S_IFREG:
                    raise SkillStoreError(
                        "Skill archive contains an unsupported special file"
                    )
                target = destination.joinpath(*parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                file_count += 1
                total_bytes += info.file_size
                SkillStore._check_import_limits(file_count, total_bytes)
                entries.append((info, target))

            for info, target in entries:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                unix_mode = (info.external_attr >> 16) & 0o777
                target.chmod(0o755 if unix_mode & 0o111 else 0o644)

        candidates = [
            item
            for item in destination.rglob("SKILL.md")
            if item.is_file()
            and not any(part in _IGNORED_IMPORT_NAMES for part in item.parts)
        ]
        if not candidates:
            raise SkillStoreError("The Skill archive does not contain SKILL.md")
        if len(candidates) > 1:
            raise SkillStoreError(
                "The Skill archive contains multiple Skills; import one package at a time"
            )
        return candidates[0].parent

    def _target(self, scope: str) -> tuple[Path, SkillSource]:
        if scope == "user":
            root = self.state_root / "skills"
            return root, SkillSource(root, "smallink", "Smallink user skills", "user")
        if scope == "project":
            if self.workspace is None or not self.workspace.is_dir():
                raise SkillStoreError("Project Skills require an open workspace")
            root = self.workspace / ".smallink" / "skills"
            return root, SkillSource(root, "project", "Project skills", "project")
        raise SkillStoreError("scope must be 'user' or 'project'")

    @staticmethod
    def _required_text(value: str, field: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            raise SkillStoreError(f"{field} is required")
        if len(text) > limit:
            raise SkillStoreError(f"{field} exceeds {limit} characters")
        return text

    @staticmethod
    def _validate_name(value: str) -> str:
        name = str(value or "").strip().lower()
        if not name:
            raise SkillStoreError("name is required")
        if len(name) > 64 or not _NAME_RE.fullmatch(name):
            raise SkillStoreError(
                "name must use lowercase letters, numbers, and single hyphens only"
            )
        return name

    @staticmethod
    def _ensure_available(destination: Path) -> None:
        if destination.exists() or destination.is_symlink():
            raise SkillStoreError(
                f"Skill '{destination.name}' already exists in this scope",
                code="conflict",
            )

    @staticmethod
    def _write_interface(
        root: Path,
        *,
        display_name: str,
        short_description: str,
        name: str,
    ) -> None:
        agents = root / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        payload = {
            "interface": {
                "display_name": display_name[:80],
                "short_description": short_description[:240],
                "default_prompt": f"Use the {name} Skill for this task.",
            }
        }
        (agents / "openai.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def _import_files(source: Path) -> list[tuple[Path, Path]]:
        selected: list[tuple[Path, Path]] = []
        total_bytes = 0
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(source)
            if any(part in _IGNORED_IMPORT_NAMES for part in relative.parts):
                continue
            if item.is_symlink():
                raise SkillStoreError("Imported Skills cannot contain symbolic links")
            if item.is_dir():
                continue
            if not item.is_file():
                raise SkillStoreError(
                    f"Skill package contains an unsupported file: {relative}"
                )
            selected.append((relative, item))
            total_bytes += item.stat().st_size
            SkillStore._check_import_limits(len(selected), total_bytes)
        if not any(relative == Path("SKILL.md") for relative, _ in selected):
            raise SkillStoreError("Skill package must contain SKILL.md")
        return selected

    @staticmethod
    def _check_import_limits(file_count: int, total_bytes: int) -> None:
        if file_count > _MAX_FILES:
            raise SkillStoreError(f"Skill import exceeds {_MAX_FILES} files")
        if total_bytes > _MAX_TOTAL_BYTES:
            raise SkillStoreError("Skill import exceeds 10 MB")

    @staticmethod
    def _read_written(destination: Path, source: SkillSource) -> Skill:
        skill = _parse_skill(destination / "SKILL.md", source)
        if not skill.valid:
            shutil.rmtree(destination, ignore_errors=True)
            raise SkillStoreError("; ".join(skill.errors))
        return skill


def skill_result(skill: Skill) -> dict[str, Any]:
    return skill.to_dict(include_instructions=True)
