from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from smallink.connectors.base import MessageEvent, SessionSource
from smallink.providers import ModelCapabilities, ProviderClient
from smallink.server.manager import SessionManager


class QuietProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(data_dir=tmp_path / "data", provider=QuietProvider())


def _dm_event(*, user_id: str, user_name: str, chat_id: str = "D1") -> MessageEvent:
    return MessageEvent(
        text="ping",
        source=SessionSource(
            platform="slack",
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            chat_name=user_name,
            chat_type="dm",
        ),
        message_id=f"{user_id}.000001",
    )


async def test_dispatch_inbound_offloads_people_persistence_and_keeps_loop_running(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    manager.secrets.put(
        "slack:default",
        {
            "bot_token": "xoxb-test",
            "app_token": "xapp-test",
            "enabled": True,
            "allowed_users": ["U1"],
        },
    )
    manager.set_dm_session("session-1")

    note_started = asyncio.Event()
    release_note = threading.Event()
    delivered = asyncio.Event()
    heartbeat = asyncio.Event()
    loop = asyncio.get_running_loop()

    original_note_person = manager._note_person

    def slow_note_person(platform: str, user_id: str | None, name: str | None) -> None:
        loop.call_soon_threadsafe(note_started.set)
        release_note.wait()
        original_note_person(platform, user_id, name)

    async def fake_deliver(target_session_id, message, *, source=None):
        delivered.set()
        return True

    async def beat() -> None:
        await asyncio.sleep(0)
        heartbeat.set()

    monkeypatch.setattr(manager, "_note_person", slow_note_person)
    monkeypatch.setattr(manager, "deliver_to_session", fake_deliver)

    dispatch_task = asyncio.create_task(
        manager._dispatch_inbound(_dm_event(user_id="U1", user_name="Alice"))
    )
    await asyncio.wait_for(note_started.wait(), timeout=0.2)

    heartbeat_task = asyncio.create_task(beat())
    await asyncio.wait_for(heartbeat.wait(), timeout=0.2)
    assert not delivered.is_set()
    assert not dispatch_task.done()

    release_note.set()
    await asyncio.wait_for(heartbeat_task, timeout=0.2)
    await asyncio.wait_for(dispatch_task, timeout=0.2)
    assert delivered.is_set()


async def test_note_person_concurrent_updates_preserve_all_people(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    write_started = threading.Event()
    release_write = threading.Event()
    real_people_path = manager._people_path

    class SlowPeoplePath:
        def __init__(self, real_path: Path) -> None:
            self._real_path = real_path

        def write_text(self, data: str, *args, **kwargs):
            write_started.set()
            release_write.wait()
            return self._real_path.write_text(data, *args, **kwargs)

        def read_text(self, *args, **kwargs):
            return self._real_path.read_text(*args, **kwargs)

    manager._people_path = SlowPeoplePath(real_people_path)

    async def note(user_id: str, name: str) -> None:
        await asyncio.to_thread(manager._note_person, "slack", user_id, name)

    first = asyncio.create_task(note("U1", "Alice"))
    await asyncio.to_thread(write_started.wait)
    others = asyncio.gather(
        note("U2", "Bob"),
        note("U3", "Cara"),
    )
    await asyncio.sleep(0)
    assert not others.done()
    release_write.set()
    await asyncio.wait_for(first, timeout=0.2)
    await asyncio.wait_for(others, timeout=0.2)

    assert manager._people == {
        "slack:U1": "Alice",
        "slack:U2": "Bob",
        "slack:U3": "Cara",
    }
    persisted = json.loads(real_people_path.read_text())
    assert persisted == manager._people
