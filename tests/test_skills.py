"""Agents (Code/Chat) + SKILL.md loader (catalog + load_skill)."""

from __future__ import annotations

import threading
import zipfile
from pathlib import Path

from smallink.agent import build_engine
from smallink.agents import AgentContext, chat_agent, code_agent, get_agent
from smallink.providers import ModelCapabilities
from smallink.skills import (
    SkillLoader,
    SkillSource,
    SkillStore,
    SkillStoreError,
    skill_catalog_text,
    skill_tools,
)
from smallink.tools import ToolRegistry
from smallink.tools.shell import LocalExecutor
from smallink.tools.todo import TodoList


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()


# -- agents ---------------------------------------------------------------------


def test_code_agent_tools(tmp_path):
    ex = LocalExecutor(cwd=tmp_path, default_timeout=5)
    try:
        ctx = AgentContext(workspace=tmp_path, executor=ex, todo=TodoList())
        names = {getattr(t, "__name__", "?") for t in code_agent().build_tools(ctx)}
        assert {
            "read_file",
            "write_file",
            "git_status",
            "run_shell",
            "todo_write",
        } <= names
    finally:
        ex.close()


def test_chat_agent_has_no_workspace_tools():
    assert chat_agent().build_tools(AgentContext()) == []
    assert chat_agent().needs_workspace is False
    assert code_agent().needs_workspace is True


def test_get_agent_fallback():
    assert get_agent("chat").name == "chat"
    # Unknown ids fall back to the default persona (Link), per the persona registry.
    assert get_agent("nope").name == "link"


# -- SKILL.md loader ------------------------------------------------------------


def _make_skill(skills_dir, name, desc, body):
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}", encoding="utf-8"
    )


def test_skill_loader_catalog_and_load(tmp_path):
    skills_dir = tmp_path / "skills"
    _make_skill(
        skills_dir, "pdf", "extract text from PDFs", "Use pdfplumber to extract text."
    )
    loader = SkillLoader([skills_dir])

    assert loader.catalog() == [
        {"name": "pdf", "description": "extract text from PDFs"}
    ]
    assert "pdf: extract text from PDFs" in skill_catalog_text(loader)

    reg = ToolRegistry()
    reg.register_all(skill_tools(loader))
    loaded = reg.execute("load_skill", {"name": "pdf"})
    assert "pdfplumber" in loaded["instructions"]
    assert reg.execute("load_skill", {"name": "missing"})["error"]


def test_skill_inventory_keeps_sources_and_marks_effective_override(tmp_path):
    shared = tmp_path / "shared"
    project = tmp_path / "project"
    _make_skill(shared, "review-code", "Review changes", "Use the shared checklist.")
    _make_skill(project, "review-code", "Review this project", "Use project rules.")
    skill_root = project / "review-code"
    (skill_root / "scripts").mkdir()
    (skill_root / "scripts" / "check.sh").write_text("true\n")
    (skill_root / "agents").mkdir()
    (skill_root / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Project Reviewer\n"
        "  short_description: Review with project conventions\n"
    )

    loader = SkillLoader(
        [
            SkillSource(shared, "agents", "Shared agent skills", "user"),
            SkillSource(project, "project", "Project skills", "project"),
        ]
    )

    items = loader.inventory()
    assert len(items) == 2
    assert items[0]["active"] is False
    assert items[0]["shadowed_by"] == items[1]["id"]
    assert items[1]["active"] is True
    assert items[1]["display_name"] == "Project Reviewer"
    assert items[1]["resources"]["scripts"] == 1
    assert loader.catalog() == [
        {"name": "review-code", "description": "Review this project"}
    ]
    assert loader.detail(items[1]["id"])["instructions"] == "Use project rules."
    assert loader.summary() == {"total": 2, "active": 1, "issues": 0, "sources": 2}


def test_invalid_skill_is_visible_but_not_loaded(tmp_path):
    skills_dir = tmp_path / "skills"
    broken = skills_dir / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text("---\nname: broken\n---\nMissing a description.")

    loader = SkillLoader([skills_dir])

    [item] = loader.inventory()
    assert item["valid"] is False
    assert item["active"] is False
    assert "description is required" in item["errors"]
    assert loader.catalog() == []
    assert loader.summary()["issues"] == 1


def test_skill_store_creates_and_refreshes_loader(tmp_path):
    state = tmp_path / "state"
    store = SkillStore(state)
    loader = SkillLoader([state / "skills"])
    reg = ToolRegistry()
    reg.register_all(skill_tools(loader, store))

    result = reg.execute(
        "create_skill",
        {
            "name": "weekly-review",
            "description": "Turn weekly activity into a concise review.",
            "instructions": "Collect outcomes, decisions, and open questions.",
            "display_name": "Weekly Review",
        },
    )

    assert result["ok"] is True
    assert loader.get("weekly-review") is not None
    skill_md = state / "skills" / "weekly-review" / "SKILL.md"
    assert skill_md.is_file()
    assert "name: weekly-review" in skill_md.read_text()
    assert "display_name: Weekly Review" in (
        state / "skills" / "weekly-review" / "agents" / "openai.yaml"
    ).read_text()


def test_skill_store_imports_complete_package_and_rejects_conflict(tmp_path):
    source = tmp_path / "source" / "document-digest"
    _make_skill(
        source.parent,
        "document-digest",
        "Summarize a long document with evidence.",
        "Read the document, then cite the supporting sections.",
    )
    (source / "references").mkdir()
    (source / "references" / "format.md").write_text("# Output format\n")
    (source / "prompts").mkdir()
    (source / "prompts" / "summary.md").write_text("# Summary prompt\n")
    (source / "defaults.json").write_text('{"format": "brief"}\n')
    (source / "node_modules").mkdir()
    (source / "node_modules" / "dependency.js").write_text("not imported")
    store = SkillStore(tmp_path / "state")

    imported = store.import_directory(source)

    target = tmp_path / "state" / "skills" / "document-digest"
    assert imported.name == "document-digest"
    assert (target / "references" / "format.md").is_file()
    assert (target / "prompts" / "summary.md").is_file()
    assert (target / "defaults.json").is_file()
    assert not (target / "node_modules").exists()
    try:
        store.import_directory(source)
        assert False, "duplicate imports must fail"
    except SkillStoreError as exc:
        assert exc.code == "conflict"


def test_skill_store_imports_zip_with_wrapper_directory(tmp_path):
    source = tmp_path / "follow-builders-main"
    _make_skill(
        tmp_path,
        "follow-builders-main",
        "Build a digest from configured sources.",
        "Read prompts and run the packaged scripts.",
    )
    (source / "config").mkdir()
    (source / "config" / "sources.json").write_text('{"sources": []}\n')
    (source / "prompts").mkdir()
    (source / "prompts" / "digest.md").write_text("# Digest\n")
    (source / "scripts").mkdir()
    (source / "scripts" / "generate.js").write_text("console.log('ok')\n")
    archive_path = tmp_path / "follow-builders.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for item in source.rglob("*"):
            if item.is_file():
                archive.write(item, Path("follow-builders-main") / item.relative_to(source))

    imported = SkillStore(tmp_path / "state").import_path(archive_path)

    target = tmp_path / "state" / "skills" / "follow-builders-main"
    assert imported.name == "follow-builders-main"
    assert (target / "config" / "sources.json").is_file()
    assert (target / "prompts" / "digest.md").is_file()
    assert (target / "scripts" / "generate.js").is_file()


def test_skill_store_rejects_zip_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "escape")
        archive.writestr(
            "safe/SKILL.md",
            "---\nname: safe\ndescription: Safe workflow\n---\nRun it.\n",
        )

    try:
        SkillStore(tmp_path / "state").import_path(archive_path)
        assert False, "archive traversal must fail"
    except SkillStoreError as exc:
        assert "unsafe path" in str(exc)


def test_skill_store_rejects_symlink_in_import(tmp_path):
    source = tmp_path / "source" / "unsafe-skill"
    _make_skill(source.parent, "unsafe-skill", "Unsafe import", "Do a task.")
    (source / "assets").mkdir()
    (source / "assets" / "outside").symlink_to(tmp_path)

    try:
        SkillStore(tmp_path / "state").import_directory(source)
        assert False, "symlink imports must fail"
    except SkillStoreError as exc:
        assert "symbolic links" in str(exc)


# -- engine assembly per agent --------------------------------------------------


def test_build_engine_chat(tmp_path):
    engine = build_engine(
        agent=chat_agent(), provider=_Stub(), skill_state_root=tmp_path / "state"
    )
    assert "load_skill" in engine.registry.names()
    assert "create_skill" in engine.registry.names()
    assert "read_file" not in engine.registry.names()
    assert engine.executor is None
    assert engine.agent_name == "chat"


def test_build_engine_code_has_agents_md_and_skills(tmp_path):
    (tmp_path / "AGENTS.md").write_text("PROJECT RULE: prefer pathlib.")
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        assert "prefer pathlib" in engine.messages[0]["content"]
        assert "todo_write" in engine.registry.names()
        assert "load_skill" in engine.registry.names()
        assert engine.agent_name == "code"
    finally:
        engine.executor.close()


def test_skill_runtime_invalidation_does_not_discard_a_concurrent_claim(tmp_path):
    from smallink.server.manager import SessionManager

    manager = SessionManager(workspace=None, data_dir=tmp_path / "data", provider=_Stub())
    engine = manager.get_engine("skill-race", agent="chat")
    assert engine is not None
    entered = threading.Event()
    release = threading.Event()
    original_scope = manager._runtimes.scope
    first_lookup = True

    def blocking_scope(session_id):
        nonlocal first_lookup
        scope = original_scope(session_id)
        if session_id == "skill-race" and first_lookup:
            first_lookup = False
            entered.set()
            release.wait(timeout=5)
        return scope

    manager._runtimes.scope = blocking_scope
    invalidated = threading.Event()
    worker = threading.Thread(
        target=lambda: (manager._invalidate_idle_skill_runtimes(), invalidated.set())
    )
    worker.start()
    assert entered.wait(timeout=5)

    claimed: list[bool] = []
    claimant = threading.Thread(
        target=lambda: claimed.append(
            manager.try_mark_running("skill-race", engine=engine)
        )
    )
    claimant.start()
    assert not invalidated.wait(timeout=0.05)
    release.set()
    worker.join(timeout=5)
    claimant.join(timeout=5)

    # Whichever operation wins the shared lock is safe: invalidation may detach the idle
    # engine first (claim then fails), or claim may win (runtime remains published).
    if claimed == [True]:
        assert manager._runtimes.engine("skill-race") is engine
        manager.mark_idle("skill-race")
    else:
        assert claimed == [False]
        assert manager._runtimes.engine("skill-race") is None


def test_skill_runtime_invalidation_preserves_an_already_claimed_runtime(tmp_path):
    from smallink.server.manager import SessionManager

    manager = SessionManager(workspace=None, data_dir=tmp_path / "data", provider=_Stub())
    engine = manager.get_engine("active-skill-session", agent="chat")
    assert engine is not None
    assert manager.try_mark_running("active-skill-session", engine=engine) is True

    manager._invalidate_idle_skill_runtimes()

    assert manager._runtimes.engine("active-skill-session") is engine
    assert manager.is_running("active-skill-session") is True
    manager.mark_idle("active-skill-session")
