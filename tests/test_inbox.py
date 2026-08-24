"""Phase 2 gate — the Inbox: 3 item kinds, the resolve state machine, reconciliation, approver."""

from __future__ import annotations

import asyncio
import threading

from smallink.inbox import (
    KIND_APPROVAL,
    KIND_NOTIFICATION,
    STATE_RESOLVED,
    InboxStore,
    inbox_approver,
)


def test_add_and_filter(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    store.add_approval("s1", "Run shell?")
    store.add_question("s1", "Which env?")
    store.add_notification("s2", "Report ready")
    assert len(store.list(session_id="s1")) == 2
    assert len(store.pending("s1")) == 2
    assert store.list(session_id="s2")[0].kind == KIND_NOTIFICATION


def test_resolve_is_idempotent_first_responder_wins(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Run shell?")
    assert store.resolve(item.id, "allow") is True
    # A second resolution from any surface is a no-op; the first answer stands.
    assert store.resolve(item.id, "deny") is False
    got = store.get(item.id)
    assert got.state == STATE_RESOLVED and got.resolution == "allow"


def test_resolve_unknown_item(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    assert store.resolve("nope", "allow") is False


def test_resolve_wakes_waiter_from_another_thread_under_asyncio_debug(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Run shell?")
    resolved = threading.Event()
    errors: list[BaseException] = []

    async def scenario() -> str:
        def resolve_from_worker() -> None:
            try:
                assert store.resolve(item.id, "allow") is True
            except BaseException as exc:
                errors.append(exc)
            finally:
                resolved.set()

        worker = threading.Thread(target=resolve_from_worker)
        waiter = asyncio.create_task(store.wait(item.id))
        await asyncio.sleep(0)
        worker.start()
        try:
            return await asyncio.wait_for(waiter, timeout=2)
        finally:
            worker.join(timeout=2)

    assert asyncio.run(scenario(), debug=True) == "allow"
    assert resolved.is_set()
    assert errors == []


def test_resolve_wakes_same_item_waiters_on_two_event_loops(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "Which environment?")
    ready = threading.Barrier(3)
    results: list[str] = []
    errors: list[BaseException] = []

    def wait_in_thread() -> None:
        async def scenario() -> None:
            waiter = asyncio.create_task(store.wait(item.id))
            await asyncio.sleep(0)
            ready.wait(timeout=5)
            results.append(await asyncio.wait_for(waiter, timeout=2))

        try:
            asyncio.run(scenario(), debug=True)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=wait_in_thread) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.wait(timeout=5)
    assert store.resolve(item.id, "production") is True
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert results == ["production", "production"]


def test_resolve_skips_and_cleans_waiter_on_closed_loop(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "Which environment?")
    started = threading.Event()
    finished = threading.Event()

    def wait_then_close_loop() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def scenario() -> None:
            waiter = asyncio.create_task(store.wait(item.id))
            await asyncio.sleep(0)
            started.set()
            waiter.cancel()
            try:
                await waiter
            except asyncio.CancelledError:
                pass

        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
            asyncio.set_event_loop(None)
            finished.set()

    thread = threading.Thread(target=wait_then_close_loop)
    thread.start()
    assert started.wait(timeout=5)
    assert finished.wait(timeout=5)
    thread.join(timeout=5)

    assert store.resolve(item.id, "production") is True
    assert store.get(item.id).resolution == "production"
    assert store._waiters.get(item.id) in (None, [])


def test_add_is_atomic_for_the_same_tool_call(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    ready = threading.Barrier(3)
    items = []

    def add_from_thread() -> None:
        ready.wait(timeout=5)
        items.append(
            store.add_question(
                "s1", "Which environment?", tool_call_id="tool-call-1"
            )
        )

    threads = [threading.Thread(target=add_from_thread) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)

    assert len(items) == 2
    assert items[0].id == items[1].id
    assert len(store.pending("s1")) == 1


def test_persistence(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Run shell?")
    store.resolve(item.id, "allow")
    reloaded = InboxStore(tmp_path / "inbox.json")
    assert reloaded.get(item.id).resolution == "allow"


def test_reconcile_on_resume(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    answered = store.add_approval("s1", "Deploy?")
    store.resolve(answered.id, "allow")
    store.add_question("s1", "Still pending?")
    store.add_approval("other", "Not mine")
    out = store.reconcile_on_resume("s1")
    assert [i["title"] for i in out["pending"]] == ["Still pending?"]
    assert [i["title"] for i in out["recap"]] == ["Deploy?"]


def test_inbox_approver_allow(tmp_path):
    async def run():
        store = InboxStore(tmp_path / "inbox.json")
        from smallink.engine import ApprovalOutcome, PermissionRequest

        approver = inbox_approver(store, "s1")
        req = PermissionRequest("run_shell", {}, None, "needs approval")

        async def resolve_soon():
            for _ in range(200):
                pend = store.pending("s1")
                if pend:
                    store.resolve(pend[0].id, "allow")
                    return
                await asyncio.sleep(0.001)

        outcome, _ = await asyncio.gather(approver(req), resolve_soon())
        assert outcome is ApprovalOutcome.ONCE
        # The approval came in as an Inbox item.
        assert store.list(session_id="s1")[0].kind == KIND_APPROVAL

    asyncio.run(run())


def test_inbox_approver_deny(tmp_path):
    async def run():
        store = InboxStore(tmp_path / "inbox.json")
        from smallink.engine import ApprovalOutcome, PermissionRequest

        approver = inbox_approver(store, "s1")
        req = PermissionRequest("rm", {}, None, "danger")

        async def resolve_soon():
            for _ in range(200):
                pend = store.pending("s1")
                if pend:
                    store.resolve(pend[0].id, "deny")
                    return
                await asyncio.sleep(0.001)

        outcome, _ = await asyncio.gather(approver(req), resolve_soon())
        assert outcome is ApprovalOutcome.DENY

    asyncio.run(run())


def test_args_preview():
    from smallink.inbox import args_preview

    assert (
        args_preview({"path": "g.txt", "content": "buy milk"})
        == "path: g.txt · content: buy milk"
    )
    assert args_preview(None) == "" and args_preview({}) == ""
    assert "\n" not in args_preview({"x": "a\nb\nc"})  # newlines collapsed
    assert args_preview({"content": "z" * 300}).endswith("…")  # long values truncated


def test_approval_body_includes_tool_args():
    from smallink.engine import PermissionRequest
    from smallink.server.manager import _approval_body

    req = PermissionRequest(
        "write_file", {"path": "groceries.txt", "content": "buy milk"}, None, ""
    )
    body = _approval_body(req)
    assert "groceries.txt" in body and "buy milk" in body  # the card now shows *what*

    req2 = PermissionRequest("rm", {"path": "/x"}, None, "destructive")
    assert _approval_body(req2).startswith("destructive")  # reason leads when present
