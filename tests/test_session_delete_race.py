from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.runtime.scope import RuntimeScope
from smallink.server import create_app
from smallink.server.manager import SessionManager
from smallink.sessions import SessionRecord


class BlockingProvider(ProviderClient):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, *, model, messages, tools=None, **settings):
        self.started.set()
        self.release.wait(timeout=5)
        return AssistantTurn(text="done", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _scratch_for(mgr: SessionManager, session_id: str) -> Path:
    return Path(mgr._provision_scratch(session_id))


def test_delete_idle_session_cleans_scratch_and_is_idempotent(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=BlockingProvider())
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")

    scratch = _scratch_for(mgr, "idle-delete")
    mgr.session_store.save(
        SessionRecord(
            session_id="idle-delete",
            workspace=str(scratch),
            model="m",
            mode="interactive",
        )
    )

    first = mgr.delete_session("idle-delete")
    second = mgr.delete_session("idle-delete")

    assert first["ok"] is True
    assert second["ok"] is False
    assert not scratch.exists()
    assert mgr.session_store.load("idle-delete") is None
    assert mgr.is_session_deleted("idle-delete") is True


def test_delete_nonexistent_session_does_not_leave_tombstone(tmp_path):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())

    before = set(mgr._deleted_sessions)
    ids = [f"missing-{i}" for i in range(3)]
    results = [mgr.delete_session(session_id) for session_id in ids]

    assert all(result["ok"] is False for result in results)
    assert set(mgr._deleted_sessions) == before
    for session_id in ids:
        assert mgr.is_session_deleted(session_id) is False


def test_delete_running_ws_session_prevents_revival_and_defers_scratch_cleanup(tmp_path):
    provider = BlockingProvider()
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=provider)
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    client = TestClient(create_app(mgr))

    sid = "running-delete"
    scratch = _scratch_for(mgr, sid)
    with client.websocket_connect(f"/ws/session/{sid}?agent=link") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert provider.started.wait(timeout=5)
        time.sleep(0.05)

        deleted = client.delete(f"/v1/sessions/{sid}").json()
        assert deleted["ok"] is True
        assert mgr.session_store.load(sid) is None
        assert mgr.is_session_deleted(sid) is True

        provider.release.set()
        while ws.receive_json()["type"] != "turn_done":
            pass

    assert mgr.session_store.load(sid) is None
    assert not scratch.exists()
    assert mgr.is_session_deleted(sid) is True
    assert mgr._runtimes.engine(sid) is None


def test_delete_running_background_delivery_does_not_drop_scratch_early(tmp_path):
    provider = BlockingProvider()
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=provider)
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")

    sid = "delivery-delete"
    scratch = _scratch_for(mgr, sid)
    engine = mgr.get_engine(sid, agent="link")
    assert engine is not None

    result: dict[str, object] = {}

    def _deliver():
        result["delivered"] = asyncio.run(mgr.deliver_to_session(sid, "background work"))

    thread = threading.Thread(target=_deliver)
    thread.start()
    assert provider.started.wait(timeout=5)
    time.sleep(0.05)

    deleted = mgr.delete_session(sid)
    assert deleted["ok"] is True
    assert scratch.exists()
    assert mgr.session_store.load(sid) is None
    assert mgr.is_session_deleted(sid) is True

    provider.release.set()
    thread.join(timeout=5)
    # Deletion won before the final persistence boundary, so callers must treat the message as
    # undelivered (and inbound routes can dead-letter it) even though the provider had started.
    assert result["delivered"] is False
    assert mgr.session_store.load(sid) is None
    assert not scratch.exists()
    assert mgr.is_session_deleted(sid) is True
    assert mgr._runtimes.engine(sid) is None


def test_save_delete_interleaving_cannot_revive_session(tmp_path, monkeypatch):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    sid = "save-delete-race"
    engine = mgr.get_engine(sid, agent="link")
    assert engine is not None
    scratch = Path(engine.roots[0].path)
    engine.messages.append({"role": "user", "content": "hello"})

    entered_save = threading.Event()
    allow_save = threading.Event()
    original_save = mgr.session_store.save

    def blocking_store_save(record):
        entered_save.set()
        allow_save.wait(timeout=5)
        return original_save(record)

    monkeypatch.setattr(mgr.session_store, "save", blocking_store_save)

    save_thread = threading.Thread(target=mgr.save, args=(sid, engine))
    save_thread.start()
    assert entered_save.wait(timeout=5)
    delete_result: dict[str, object] = {}
    delete_done = threading.Event()

    def delete() -> None:
        delete_result.update(mgr.delete_session(sid))
        delete_done.set()

    delete_thread = threading.Thread(target=delete)
    delete_thread.start()
    assert not delete_done.wait(timeout=0.05)
    allow_save.set()
    save_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert delete_result["ok"] is True
    assert mgr.session_store.load(sid) is None
    assert not scratch.exists()
    assert mgr.is_session_deleted(sid) is True
    assert mgr._runtimes.engine(sid) is None


def test_deleted_idle_session_rejects_messages_from_its_stale_engine(tmp_path):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    sid = "stale-socket"
    engine = mgr.get_engine(sid, agent="link")
    assert engine is not None

    assert mgr.delete_session(sid)["ok"] is True
    assert mgr.try_mark_running(sid, engine=engine) is False
    mgr.save(sid, engine)

    assert mgr.session_store.load(sid) is None
    assert mgr._runtimes.engine(sid) is None
    assert mgr.get_engine(sid, agent="link") is None


def test_mark_running_cannot_recreate_a_deleted_runtime(tmp_path):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    sid = "deleted-mark-running"
    engine = mgr.get_engine(sid, agent="link")
    assert engine is not None
    assert mgr.delete_session(sid)["ok"] is True

    try:
        mgr.mark_running(sid, engine=engine)
    except RuntimeError:
        pass
    else:
        raise AssertionError("deleted session was marked running")

    assert mgr._runtimes.scope(sid) is None
    assert mgr.session_store.load(sid) is None


def test_engine_build_does_not_block_unrelated_session_save(tmp_path, monkeypatch):
    import smallink.server.manager as manager_module

    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    existing = mgr.get_engine("existing", agent="chat")
    assert existing is not None
    existing.messages.append({"role": "user", "content": "keep me"})

    build_started = threading.Event()
    release_build = threading.Event()
    original_build = manager_module.build_engine

    def blocking_build(*args, **kwargs):
        build_started.set()
        release_build.wait(timeout=5)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(manager_module, "build_engine", blocking_build)
    build_thread = threading.Thread(
        target=lambda: mgr.get_engine("building", agent="chat")
    )
    build_thread.start()
    assert build_started.wait(timeout=5)

    save_done = threading.Event()

    def save_existing() -> None:
        mgr.save("existing", existing)
        save_done.set()

    save_thread = threading.Thread(target=save_existing)
    save_thread.start()
    assert save_done.wait(timeout=1), "unrelated save waited for engine construction"

    release_build.set()
    build_thread.join(timeout=5)
    save_thread.join(timeout=5)
    assert mgr.session_store.load("existing") is not None


def test_concurrent_same_session_builds_publish_one_engine(tmp_path, monkeypatch):
    import smallink.server.manager as manager_module

    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    original_build = manager_module.build_engine
    build_count = 0
    count_lock = threading.Lock()

    def counted_build(*args, **kwargs):
        nonlocal build_count
        with count_lock:
            build_count += 1
        time.sleep(0.05)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(manager_module, "build_engine", counted_build)
    engines: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: engines.append(mgr.get_engine("same", agent="chat"))
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert build_count == 1
    assert len(engines) == 2
    assert engines[0] is engines[1] is mgr._runtimes.engine("same")


def test_add_root_cannot_revive_session_during_scratch_cleanup(tmp_path, monkeypatch):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    sid = "root-delete-race"
    engine = mgr.get_engine(sid, agent="link")
    assert engine is not None
    mgr.save(sid, engine)
    extra = tmp_path / "extra"
    extra.mkdir()

    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    original_cleanup = mgr._delete_scratch_dir

    def blocking_cleanup(workspace: str) -> None:
        cleanup_started.set()
        release_cleanup.wait(timeout=5)
        original_cleanup(workspace)

    monkeypatch.setattr(mgr, "_delete_scratch_dir", blocking_cleanup)
    delete_thread = threading.Thread(target=lambda: mgr.delete_session(sid))
    delete_thread.start()
    assert cleanup_started.wait(timeout=5)

    result = mgr.add_root(sid, str(extra), writable=True)
    assert result == {"ok": False, "error": "session is being deleted"}
    assert mgr.session_store.load(sid) is None

    release_cleanup.set()
    delete_thread.join(timeout=5)
    assert mgr.session_store.load(sid) is None
    assert mgr.is_session_deleted(sid) is True
    assert mgr.get_engine(sid, agent="link") is None


def test_deliver_returns_false_without_steering_when_runtime_replaced(tmp_path):
    mgr = SessionManager(workspace=None, data_dir=tmp_path, provider=BlockingProvider())
    sid = "replaced-runtime"
    original = mgr.get_engine(sid, agent="link")
    assert original is not None

    replacement_engine = mgr.get_engine("replacement-holder", agent="link")
    assert replacement_engine is not None
    replacement = RuntimeScope(sid, engine=replacement_engine)
    replacement.claim()
    mgr._runtimes._scopes[sid] = replacement
    original_get_engine = mgr.get_engine

    def stale_get_engine(session_id, **kwargs):
        if session_id == sid:
            return original
        return original_get_engine(session_id, **kwargs)

    mgr.get_engine = stale_get_engine  # type: ignore[method-assign]

    delivered = asyncio.run(mgr.deliver_to_session(sid, "background work"))

    assert delivered is False
    assert getattr(original, "_steering", []) == []
