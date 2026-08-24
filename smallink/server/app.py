"""FastAPI app — OpenAI-compatible endpoint + WS session API + REST.

The control plane every surface (GUI/IDE/messaging) rides on. The WS carries the engine
event stream and the approval channel; `/v1/chat/completions` is the OpenAI-compatible
proxy so any OpenAI-format client can use the runtime as a backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import uuid
from collections import deque
from contextlib import asynccontextmanager, suppress
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Origins allowed to talk to the local sidecar. It binds to 127.0.0.1, but a page in the
# user's own browser can still reach loopback — so without an origin gate, any website they
# visit could read `GET /v1/sessions` (CORS was `*`) and drive a session over the WS (which
# CORS never covers) into shell/file tools. We pin to the desktop webview's own origins
# (`tauri://localhost`, Windows' `http(s)://tauri.localhost`) and localhost dev/browser
# builds. Requests with NO Origin header (curl, native clients, tests, server-to-server) are
# allowed — the gate targets browsers, which always attach an unforgeable Origin.
_ALLOWED_ORIGIN_RE = re.compile(
    r"^(tauri://localhost"
    r"|https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https?://tauri\.localhost)$"
)


def _origin_allowed(origin: str | None) -> bool:
    """True if a browser Origin may use the API. Missing Origin (non-browser) passes."""
    return origin is None or bool(_ALLOWED_ORIGIN_RE.match(origin))


# Caps on inbound WebSocket traffic. The loopback socket is unauthenticated (any local
# process can reach it), so bound frames, messages, and per-connection request rate before
# building model content or starting a turn.
_WS_MAX_FRAME_BYTES = 16 * 1024 * 1024
_WS_RATE_LIMIT_COUNT = 30
_WS_RATE_LIMIT_WINDOW_SECONDS = 10.0
_MAX_MESSAGE_TEXT_CHARS = 200_000
_MAX_ATTACHMENTS_BYTES = 15_000_000  # leaves JSON overhead below the 16 MiB frame cap


def _json_value_size(value: Any) -> int:
    """Conservative UTF-8 size of parsed JSON without allocating another giant string."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, dict):
        return sum(_json_value_size(k) + _json_value_size(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(_json_value_size(v) for v in value)
    return 8  # numbers, booleans, null, separators


from .. import __version__
from ..attachments import (
    MAX_ATTACHMENTS as _MAX_ATTACHMENTS,
    MAX_IMAGE_CHARS,
    MAX_PDF_CHARS,
    MAX_TEXT_CHARS,
    build_user_content,
)
from ..inbox import VIS_INBOX
from ..permissions import Mode
from ..providers import AssistantTurn
from .routers import (
    apps_router,
    automations_router,
    cloud_router,
    connectors_router,
    knowledge_router,
    mcp_router,
    memory_router,
    personas_router,
    projects_router,
    prompts_router,
    sessions_router,
    settings_router,
    skills_router,
    workspaces_router,
)
from .manager import SessionManager

logger = logging.getLogger("smallink.server.app")


def create_app(manager: SessionManager) -> FastAPI:
    turn_tasks: set[asyncio.Task[None]] = set()

    def _track_turn_task(coroutine, *, session_id: str) -> None:
        task = asyncio.create_task(
            coroutine, name=f"smallink-session-turn:{session_id}"
        )
        turn_tasks.add(task)

        def _finished(done: asyncio.Task[None]) -> None:
            turn_tasks.discard(done)
            if done.cancelled():
                return
            try:
                error = done.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                logger.error(
                    "session turn task failed after cleanup for %s: %s",
                    session_id,
                    error,
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(_finished)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def restore_background_services() -> None:
            try:
                live = await manager.start_gateway()
                if live:
                    print(f"[smallink] messaging gateway live: {', '.join(live)}")
            except Exception:  # never let a bad connector stop the server
                import traceback

                traceback.print_exc()

        # Core HTTP/WS must become available before network connectors finish reconnecting. A slow
        # Slack/relay/MCP-style listener previously held FastAPI in "Waiting for application
        # startup" for many seconds, making the whole desktop window look frozen.
        gateway_task = asyncio.create_task(restore_background_services())
        try:
            yield
        finally:
            manager.begin_shutdown()
            if not gateway_task.done():
                gateway_task.cancel()
                with suppress(asyncio.CancelledError):
                    await gateway_task
            pending_turns = tuple(turn_tasks)
            for task in pending_turns:
                task.cancel()
            if pending_turns:
                await asyncio.gather(*pending_turns, return_exceptions=True)
            await manager.aclose()  # stop gateway + close MCP connections on shutdown

    app = FastAPI(title="Smallink", version=__version__, lifespan=lifespan)
    api_token = os.environ.get("LINK_API_TOKEN", "")
    tokenless_paths = {
        "/v1/health",
        "/auth/callback",
        "/mcp/oauth/callback",
        "/oauth/callback",
    }

    def _request_authenticated(request: Request) -> bool:
        provided = request.headers.get("x-link-token", "")
        return bool(
            api_token
            and provided
            and secrets.compare_digest(provided, api_token)
        )

    def _websocket_authenticated(ws: WebSocket) -> bool:
        if not api_token:
            return True
        protocols = {
            part.strip()
            for part in ws.headers.get("sec-websocket-protocol", "").split(",")
            if part.strip()
        }
        return any(secrets.compare_digest(part, api_token) for part in protocols)

    @app.middleware("http")
    async def require_sidecar_token(request: Request, call_next):
        # Preflights carry the requested header name, not its value. CORS checks the
        # Origin; the actual state-changing request still must authenticate.
        if (
            not api_token
            or request.method == "OPTIONS"
            or request.url.path in tokenless_paths
            or _request_authenticated(request)
        ):
            return await call_next(request)
        return JSONResponse(
            {"error": "missing or invalid Smallink sidecar token"},
            status_code=401,
        )

    app.add_middleware(
        CORSMiddleware,
        # Pinned to the desktop webview + localhost (see _ALLOWED_ORIGIN_RE): stops a random
        # website the user visits from reading local API responses cross-origin.
        allow_origin_regex=_ALLOWED_ORIGIN_RE.pattern,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.manager = manager
    app.include_router(knowledge_router(manager))
    app.include_router(memory_router(manager))
    app.include_router(prompts_router(manager))
    app.include_router(sessions_router(manager))
    app.include_router(settings_router(manager.settings_service))
    app.include_router(connectors_router(manager))
    app.include_router(personas_router(manager))
    app.include_router(cloud_router(manager))
    app.include_router(workspaces_router(manager))
    app.include_router(projects_router(manager))
    app.include_router(skills_router(manager))
    app.include_router(mcp_router(manager))
    app.include_router(apps_router(manager))
    app.include_router(automations_router(manager))

    from ..connectors.bwf.router import mount_bwf_on_app
    mount_bwf_on_app(app)

    @app.get("/v1/health")
    def health(request: Request) -> dict[str, Any]:
        if api_token and not _request_authenticated(request):
            return {"status": "ok"}
        return {
            "status": "ok",
            "app_version": __version__,
            "core_version": __version__,
            "schema_version": 2,
            "git_sha": os.environ.get("SMALLINK_GIT_SHA", ""),
            "build_time": os.environ.get("SMALLINK_BUILD_TIME", ""),
            "default_workspace": manager.default_workspace,
            "model": manager.model,
        }

    @app.get("/v1/agents")
    def agents() -> dict[str, Any]:
        return {"agents": manager.list_agents()}

    @app.get("/v1/inbox")
    def inbox(session_id: str = "", state: str = "") -> dict[str, Any]:
        from dataclasses import asdict

        # The cross-session Inbox list shows only Unattended (inbox-visibility) items; a per-session
        # query returns inline ones too, so the answer-in-context card sees parked attended prompts.
        items = manager.inbox.list(
            session_id=session_id or None,
            state=state or None,
            visibility=None if session_id else VIS_INBOX,
        )
        # Enrich with the originating session's context so the Inbox is self-contained — the
        # "go to session" chip needs title/agent/workspace without depending on a (possibly stale)
        # client-side session list, and can link straight to it.
        out: list[dict[str, Any]] = []
        for i in items:
            d = asdict(i)
            rec = manager.session_store.load(i.session_id)
            if (
                rec is None
                and not session_id
                and i.state == "pending"
                and manager._runtimes.engine(i.session_id) is None
            ):
                # Lazy cleanup for legacy orphans (sessions deleted before delete_session
                # started closing their items): an orphaned prompt can never be answered.
                # A LIVE engine without a record yet (brand-new session, first turn still
                # running) is NOT an orphan — hence the engine guard.
                manager.inbox.resolve_session(i.session_id)
                continue
            d["session_title"] = (rec.title if rec else None) or i.session_id
            d["session_agent"] = rec.agent if rec else None
            d["session_workspace"] = rec.workspace if rec else None
            d["session_exists"] = rec is not None
            out.append(d)
        return {"items": out}

    @app.post("/v1/inbox/{item_id}/resolve")
    async def resolve_inbox_item(item_id: str, body: dict) -> dict[str, Any]:
        # Idempotent + first-responder-wins: ok=False means it was already resolved elsewhere.
        # Routes through resolve_inbox so a restart-orphaned prompt durably resumes its turn.
        ok = await manager.resolve_inbox(item_id, str(body.get("resolution", "deny")))
        return {"ok": ok}

    @app.get("/v1/subscriptions")
    def subscriptions() -> dict[str, Any]:
        # Global view-only list: each (session → channel) subscription, enriched with the session's
        # title/agent and the channel its Inbox routes OUT to (so an inbound/outbound collision on
        # the same channel is visible).
        out: list[dict[str, Any]] = []
        for sub in manager.subscriptions.all():
            rec = manager.session_store.load(sub.session_id)
            agent = rec.agent if rec else ""
            routing = manager._routing_targets(sub.session_id, agent or "link")
            out.append(
                {
                    "session_id": sub.session_id,
                    "session_title": (rec.title if rec else None) or sub.session_id,
                    "agent": agent,
                    "channel": sub.channel,
                    # Display name from the channel buffer ("#link-test"), when any inbound
                    # message has carried one — the address stays the identifier.
                    "channel_name": manager.channel_buffer.name_for(sub.channel),
                    "routing_target": routing[0] if routing else None,
                    "collision": bool(routing and sub.channel in routing),
                }
            )
        return {"subscriptions": out}

    @app.get("/v1/channels/recent")
    def recent_channels() -> dict[str, Any]:
        # The picker's "recently-seen" source: channels the bot has received messages from.
        return {"channels": manager.channel_buffer.channels()}

    @app.get("/v1/unrouted")
    def unrouted() -> dict[str, Any]:
        # Dead-letter view: inbound messages with no destination + background-turn failures.
        return {"items": manager.unrouted.list()}

    @app.post("/v1/subscriptions")
    def subscribe(body: dict) -> dict[str, Any]:
        from ..subscriptions import resolve_channel

        session_id = str(body.get("session_id", "")).strip()
        raw = str(body.get("channel", ""))
        addr = resolve_channel(raw)
        if not session_id or not addr or ":" not in addr:
            if raw.strip().startswith("#"):
                # A bare #name can't be looked up locally — storing it literally would create a
                # subscription that never matches real traffic (resolve_channel returns "").
                return {
                    "ok": False,
                    "error": "Channel names can't be looked up — paste the channel ID "
                    "(channel name ▸ About) or the channel's Copy-link URL.",
                }
            return {"ok": False, "error": "need a session_id and a channel"}
        manager.subscriptions.subscribe(session_id, addr)
        return {"ok": True, "channel": addr}

    @app.post("/v1/subscriptions/remove")
    def unsubscribe(body: dict) -> dict[str, Any]:
        from ..subscriptions import resolve_channel

        session_id = str(body.get("session_id", "")).strip()
        addr = resolve_channel(str(body.get("channel", "")))
        removed = manager.subscriptions.unsubscribe(session_id, addr)
        return {"ok": True, "removed": removed}

    @app.get("/v1/inbox/reconcile")
    def reconcile_inbox(session_id: str) -> dict[str, Any]:
        # Called when a session resumes attended control (surface pending + recap inline).
        return manager.inbox.reconcile_on_resume(session_id)

    @app.get("/v1/inbox/routing")
    def inbox_routing() -> dict[str, Any]:
        return {"bindings": manager.inbox_routing.bindings()}

    @app.post("/v1/inbox/routing/binding")
    def set_inbox_binding(body: dict) -> dict[str, Any]:
        name = str(body.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "binding needs a `name`"}
        return manager.set_inbox_binding(
            name,
            channel=body.get("channel") or None,
            target=str(body.get("target", "")),
        )

    @app.post("/v1/chat/completions")
    def chat_completions(body: dict) -> dict[str, Any]:
        model = body.get("model", manager.model)
        turn = manager.provider_complete(
            model, body.get("messages", []), body.get("tools")
        )
        return _openai_response(model, turn)

    @app.get("/v1/tasks")
    def runtime_tasks(limit: int = 100) -> dict[str, Any]:
        return {"tasks": manager.list_runtime_tasks(limit=limit)}

    @app.get("/v1/agent-collaborations")
    def agent_collaborations(limit: int = 100) -> dict[str, Any]:
        return {"collaborations": manager.list_agent_collaborations(limit=limit)}

    @app.get("/v1/tasks/{task_id}")
    def runtime_task(task_id: str) -> Any:
        task = manager.runtime_task(task_id)
        return (
            task
            if task is not None
            else JSONResponse(status_code=404, content={"error": "task not found"})
        )

    @app.get("/v1/task-runs/{task_run_id}")
    def runtime_task_run(task_run_id: str) -> Any:
        run = manager.runtime_task_run(task_run_id)
        return (
            run
            if run is not None
            else JSONResponse(
                status_code=404, content={"error": "task run not found"}
            )
        )

    @app.get("/v1/agent-runs/{agent_run_id}")
    def runtime_agent_run(agent_run_id: str) -> Any:
        run = manager.runtime_agent_run(agent_run_id)
        return (
            run
            if run is not None
            else JSONResponse(
                status_code=404, content={"error": "agent run not found"}
            )
        )

    @app.get("/v1/agent-runs/{agent_run_id}/events")
    def runtime_agent_events(agent_run_id: str) -> Any:
        events = manager.runtime_agent_events(agent_run_id)
        return (
            {"events": events}
            if events is not None
            else JSONResponse(
                status_code=404, content={"error": "agent run not found"}
            )
        )

    # -- audit / browser observability ------------------------------------------
    @app.get("/v1/audit")
    def audit_list(
        limit: int = 100,
        session_id: str | None = None,
        connector: str | None = None,
        tool: str | None = None,
    ) -> dict[str, Any]:
        return {
            "events": manager.list_audit(
                limit=limit, session_id=session_id, connector=connector, tool=tool
            )
        }

    @app.get("/v1/browser/state")
    def browser_state_get() -> dict[str, Any]:
        return manager.browser_state()

    @app.post("/v1/browser/screenshot")
    def browser_screenshot_post() -> dict[str, Any]:
        return manager.browser_screenshot()

    @app.post("/v1/browser/close")
    def browser_close_post() -> dict[str, Any]:
        return manager.browser_close()

    if os.environ.get("LINK_DEBUG_INJECT") == "1":
        # Dev-only (env-gated, localhost): feed a message through the real inbound path so the
        # messaging stack can be exercised without a live bot connection. Not registered otherwise.
        @app.post("/v1/_debug/inject_inbound")
        async def debug_inject_inbound(body: dict) -> dict[str, Any]:
            from ..connectors.base import MessageEvent, SessionSource

            event = MessageEvent(
                text=str((body or {}).get("text", "")),
                source=SessionSource(
                    platform=str(body.get("platform", "slack")),
                    chat_id=str(body.get("chat_id", "C0BD7KZ1AH5")),
                    user_id=str(body.get("user_id", "U07JK68S4BH")),
                    user_name=str(body.get("user_name", "tester")),
                    chat_type=str(body.get("chat_type", "channel")),
                    chat_name=str(body.get("chat_name", "")) or None,
                    thread_id=str(body.get("thread_ts", "")) or None,
                    team_id=str(body.get("team_id", "")) or None,
                ),
                message_id=str(body.get("ts", "")) or None,
                mentions_me=bool(body.get("mentions_me")),
            )
            await manager._dispatch_inbound(event)
            return {"ok": True}

    @app.websocket("/ws/session/{session_id}")
    async def ws_session(ws: WebSocket, session_id: str) -> None:
        if not _websocket_authenticated(ws):
            await ws.close(code=1008)
            return
        # CORS never gates WebSockets, so a cross-site page could otherwise open this socket
        # and drive the session into tool calls. Reject a disallowed browser Origin before
        # accepting the handshake (1008 = policy violation).
        if not _origin_allowed(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="link" if api_token else None)
        agent = ws.query_params.get("agent") or "code"
        route_agent = manager.session_persona(session_id, fallback=agent)

        # Prompt callbacks are session-owned and broadcast to every viewer. They deliberately do
        # not capture this socket, so opening or closing a second view cannot steal the shared
        # engine's approval/question transport.
        approver = manager.inbox_approver(session_id, route_agent)
        question_asker = manager.inbox_question_asker(session_id, route_agent)
        directory_requester = manager.inbox_directory_requester(session_id, route_agent)
        plan_approver = manager.inbox_plan_approver(session_id, route_agent)

        async def _apply_model(model: Optional[str]) -> None:
            # Mid-session rebind is allowed (roadmap item 3, supersedes the 2026-07-04
            # lock): history is canonical and providers convert per call. A real switch
            # appends a persisted notice; broadcast it so live views render the marker
            # and update their header. Never rebind mid-turn — the running loop reads
            # `engine.model` per iteration and a mixed turn is exactly the breakage the
            # old lock existed to prevent.
            if not model or manager.is_running(session_id):
                return
            notice = engine.switch_model(model)
            if notice is None:  # same model, or first bind on a fresh session
                return
            manager.persist_session(session_id)
            await manager.broadcast_session(
                session_id,
                {"type": "model_changed", "data": {"model": model, "text": notice}},
            )

        _PROMPT_MESSAGE_TYPES = {
            "approval": "approval",
            "question_response": "question",
            "directory_response": "directory",
            "plan_response": "plan",
        }

        async def _resolve_pending(kind: str, prompt_id: Any, resolution: str) -> bool:
            # Live WS responses must echo the exact prompt id they are answering. Missing,
            # stale, wrong-session, wrong-kind, or already-resolved ids fail closed.
            expected_kind = _PROMPT_MESSAGE_TYPES.get(kind)
            if expected_kind is None or not isinstance(prompt_id, str) or not prompt_id:
                return False
            item = manager.inbox.get(prompt_id)
            if (
                item is None
                or item.session_id != session_id
                or item.kind != expected_kind
                or item.state != "pending"
            ):
                return False
            return await manager.resolve_inbox(item.id, resolution)

        workspace = ws.query_params.get("workspace")
        mcp_tools = await manager.prepare_mcp_tools(
            session_id, workspace=workspace, agent=route_agent
        )
        engine = manager.get_engine(
            session_id,
            workspace=workspace,
            agent=route_agent,
            approver=approver,
            extra_tools=mcp_tools,
            directory_requester=directory_requester,
            plan_approver=plan_approver,
            question_asker=question_asker,
        )
        if engine is None:
            await ws.send_json(
                {
                    "type": "error",
                    "data": {
                        "error": "no valid workspace — choose a project folder first"
                    },
                }
            )
            await ws.close()
            return
        await ws.send_json(
            {
                "type": "ready",
                "data": {
                    "session_id": session_id,
                    "agent": getattr(engine, "agent_name", "code"),
                    "model": engine.model,
                    "phase": manager.get_phase(session_id).value,
                    "busy": manager.is_running(session_id),
                    "mode": engine.permissions.mode.value,
                    "workspace": (
                        str(getattr(engine, "executor").cwd)
                        if getattr(engine, "executor", None)
                        else None
                    ),
                    "command_trust": manager.workspace_command_trust(
                        str(getattr(engine, "audit_context", {}).get("workspace", ""))
                    ),
                },
            }
        )

        # Checkpoint events: persist mid-turn so a crash/quit can't eat the conversation.
        # turn_start = the user message just landed (a brand-new session gets its row here,
        # not at connect — empty never-used sessions shouldn't appear in Recents);
        # permission_required/directory_requested = parked indefinitely on the user;
        # iteration_end = a model response + its tool results completed.
        _CHECKPOINTS = {
            "turn_start",
            "permission_required",
            "directory_requested",
            "plan_proposed",
            "iteration_end",
        }

        async def run_turn(
            content,
            *,
            retry: bool = False,
            client_message_id: str | None = None,
        ) -> None:
            # The receive loop atomically claims this session before scheduling the task.
            # Keeping the claim outside prevents two back-to-back frames from both starting.
            saw_error_event = False
            try:
                events = manager.tracked_engine_events(
                    session_id,
                    engine,
                    content=content,
                    trigger="retry" if retry else "user",
                    retry=retry,
                    client_message_id=client_message_id,
                )
                async for event in events:
                    if event.type.value == "error":
                        saw_error_event = True
                    if event.type.value in _CHECKPOINTS:
                        await asyncio.to_thread(manager.save, session_id, engine)
                    if event.type.value in {
                        "permission_required",
                        "directory_requested",
                        "plan_proposed",
                    }:
                        continue
                    # Broadcast to every socket viewing this session (this socket included — it's a
                    # registered client), so a second view of the same session stays in sync too.
                    await manager.broadcast_session(
                        session_id, {"type": event.type.value, "data": event.data}
                    )
            except Exception as exc:
                logger.exception("interactive turn crashed for %s", session_id)
                if not saw_error_event:
                    with suppress(Exception):
                        await manager.broadcast_session(
                            session_id, {"type": "error", "data": {"error": str(exc)}}
                        )
            finally:
                saved = False
                try:
                    saved = await asyncio.to_thread(manager.save, session_id, engine)
                except Exception:
                    logger.exception("interactive turn save failed for %s", session_id)
                    with suppress(Exception):
                        await manager.broadcast_session(
                            session_id,
                            {
                                "type": "error",
                                "data": {"error": "Failed to save session state."},
                            },
                        )
                # Manual automation completion reads its result from the durable transcript, so it
                # must run after the final save. A failed/deleted save deliberately leaves the run
                # active for recovery instead of recording a false successful result.
                if saved:
                    try:
                        await asyncio.to_thread(
                            manager.finalize_manual_run_session, session_id
                        )
                    except Exception:
                        logger.exception(
                            "manual automation finalization failed for %s", session_id
                        )
                manager.mark_idle(session_id)
                with suppress(Exception):
                    await manager.broadcast_session(
                        session_id, {"type": "turn_done", "data": {}}
                    )

        # This socket is now a live view of the session; background turns (channel delivery,
        # self-wake, durable resume) broadcast here too, not just locally driven run_turns.
        manager.register_session_client(session_id, ws.send_json)
        inbound_times: deque[float] = deque()

        async def reject_input(reason: str) -> None:
            # Input validation failures are not provider failures and must not offer "Retry"
            # or flush an in-progress assistant stream in the GUI.
            await ws.send_json({"type": "input_rejected", "data": {"error": reason}})

        async def claim_turn(
            *,
            retry: bool = False,
            content=None,
            client_message_id: str | None = None,
        ) -> None:
            if not manager.try_mark_running(session_id, engine=engine):
                await reject_input(
                    "This session is already running a turn. Wait for it to finish or stop it."
                )
                return
            if client_message_id:
                await ws.send_json(
                    {
                        "type": "message_accepted",
                        "data": {"client_message_id": client_message_id},
                    }
                )
            _track_turn_task(
                run_turn(
                    content,
                    retry=retry,
                    client_message_id=client_message_id,
                ),
                session_id=session_id,
            )

        try:
            while True:
                try:
                    message = await ws.receive_json()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await reject_input("Invalid WebSocket message: expected JSON.")
                    continue

                now = asyncio.get_running_loop().time()
                while (
                    inbound_times
                    and now - inbound_times[0] > _WS_RATE_LIMIT_WINDOW_SECONDS
                ):
                    inbound_times.popleft()
                if len(inbound_times) >= _WS_RATE_LIMIT_COUNT:
                    await reject_input("Too many WebSocket messages; reconnect and try again.")
                    await ws.close(code=1008)
                    return
                inbound_times.append(now)

                if not isinstance(message, dict):
                    await reject_input("Invalid WebSocket message: expected an object.")
                    continue
                kind = message.get("type")
                if not isinstance(kind, str):
                    await reject_input("Invalid WebSocket message: missing string type.")
                    continue
                if kind == "approval":
                    if not await _resolve_pending(
                        "approval",
                        message.get("prompt_id"),
                        message.get("decision", "deny"),
                    ):
                        await reject_input(
                            "No pending approval request for this session."
                        )
                elif kind == "directory_response":
                    if not await _resolve_pending(
                        "directory_response",
                        message.get("prompt_id"),
                        json.dumps(
                            {
                                "granted": bool(message.get("granted")),
                                "path": message.get("path", ""),
                                "writable": bool(message.get("writable", False)),
                            }
                        )
                    ):
                        await reject_input(
                            "No pending directory request for this session."
                        )
                elif kind == "plan_response":
                    if not await _resolve_pending(
                        "plan_response",
                        message.get("prompt_id"),
                        json.dumps(
                            {
                                "approved": bool(message.get("approved")),
                                "mode": message.get("mode", "interactive"),
                                "feedback": message.get("feedback", ""),
                            }
                        )
                    ):
                        await reject_input("No pending plan request for this session.")
                elif kind == "question_response":
                    if not await _resolve_pending(
                        "question_response",
                        message.get("prompt_id"),
                        str(message.get("answer", "")),
                    ):
                        await reject_input("No pending question for this session.")
                elif kind == "interrupt":
                    engine.request_interrupt()
                elif kind == "retry":
                    # Re-run after a provider error (engine guards on the error-notice
                    # tail, so a stray frame is a no-op that still ends with turn_done).
                    await claim_turn(retry=True)
                elif kind == "set_mode":
                    try:
                        engine.permissions.mode = Mode(message.get("mode"))
                    except (TypeError, ValueError):
                        pass
                elif kind == "set_model":
                    model = message.get("model")
                    if model is not None and not isinstance(model, str):
                        await reject_input("Invalid model: expected a string.")
                    else:
                        await _apply_model(model)
                elif kind == "user_message":
                    client_message_id = message.get("client_message_id")
                    if client_message_id is not None and (
                        not isinstance(client_message_id, str)
                        or not client_message_id
                        or len(client_message_id) > 128
                    ):
                        await reject_input("Invalid client message id.")
                        continue
                    if client_message_id and any(
                        existing.get("role") == "user"
                        and existing.get("client_message_id") == client_message_id
                        for existing in engine.messages
                    ):
                        await ws.send_json(
                            {
                                "type": "message_accepted",
                                "data": {
                                    "client_message_id": client_message_id,
                                    "duplicate": True,
                                },
                            }
                        )
                        continue
                    raw_text = message.get("text")
                    if raw_text is None:
                        raw_text = ""
                    if not isinstance(raw_text, str):
                        await reject_input("Invalid message text: expected a string.")
                        continue
                    text = raw_text.strip()
                    raw_attachments = message.get("attachments")
                    attachments = [] if raw_attachments is None else raw_attachments
                    # Reject an oversized frame instead of buffering it into a turn. Send a
                    # visible error so the surface can tell the user, and drop the message.
                    if not isinstance(attachments, list):
                        await reject_input("Invalid attachments: expected a list.")
                        continue
                    reject = None
                    if len(text) > _MAX_MESSAGE_TEXT_CHARS:
                        reject = (
                            f"Message too long ({len(text)} chars; "
                            f"limit {_MAX_MESSAGE_TEXT_CHARS})."
                        )
                    elif len(attachments) > _MAX_ATTACHMENTS:
                        reject = (
                            f"Too many attachments ({len(attachments)}; "
                            f"limit {_MAX_ATTACHMENTS})."
                        )
                    elif any(not isinstance(a, dict) for a in attachments):
                        reject = "Invalid attachment: expected an object."
                    elif _json_value_size(attachments) > _MAX_ATTACHMENTS_BYTES:
                        reject = "Attachments too large (limit 15 MB per message)."
                    else:
                        for attachment in attachments:
                            attachment_kind = attachment.get("kind")
                            name = attachment.get("name")
                            mime = attachment.get("mime")
                            if attachment_kind not in {"image", "pdf", "text"}:
                                reject = "Invalid attachment kind."
                            elif name is not None and (
                                not isinstance(name, str) or len(name) > 1024
                            ):
                                reject = "Invalid attachment name."
                            elif mime is not None and (
                                not isinstance(mime, str) or len(mime) > 255
                            ):
                                reject = "Invalid attachment MIME type."
                            elif attachment_kind == "image":
                                data = attachment.get("data_url")
                                if (
                                    not isinstance(data, str)
                                    or not data.startswith("data:image/")
                                    or ";base64," not in data
                                    or len(data) > MAX_IMAGE_CHARS
                                ):
                                    reject = "Invalid or oversized image attachment."
                            elif attachment_kind == "pdf":
                                data = attachment.get("data_url")
                                if (
                                    not isinstance(data, str)
                                    or not data.startswith(
                                        "data:application/pdf;base64,"
                                    )
                                    or len(data) > MAX_PDF_CHARS
                                ):
                                    reject = "Invalid or oversized PDF attachment."
                            else:
                                body = attachment.get("text")
                                if (
                                    not isinstance(body, str)
                                    or len(body) > MAX_TEXT_CHARS
                                ):
                                    reject = "Invalid or oversized text attachment."
                            if reject is not None:
                                break
                    if reject is not None:
                        await reject_input(reject)
                        continue
                    # The composer sends its visible model with every message — the FIRST
                    # one binds the session (race-proof across reconnects; see api.ts
                    # Session.userMessage), later ones may switch it (notice persisted).
                    model = message.get("model")
                    if model is not None and not isinstance(model, str):
                        await reject_input("Invalid model: expected a string.")
                        continue
                    await _apply_model(model)
                    if text or attachments:
                        content = build_user_content(text, attachments)
                        await claim_turn(
                            content=content,
                            client_message_id=client_message_id,
                        )
                else:
                    await reject_input(f"Unknown WebSocket message type: {kind}.")
        except WebSocketDisconnect:
            pass
        finally:
            manager.unregister_session_client(session_id, ws.send_json)

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        """App-wide event stream (session-independent): the GUI keeps one open for
        pushes like automation_run_started (the UX-026 toast). Read-only — inbound
        frames are ignored; the receive loop just detects disconnect."""
        if not _websocket_authenticated(ws):
            await ws.close(code=1008)
            return
        if not _origin_allowed(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="link" if api_token else None)
        manager.register_event_client(ws.send_json)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            manager.unregister_event_client(ws.send_json)

    return app


def _parse_json(s: str) -> dict[str, Any]:
    """Parse a structured Inbox resolution (directory/plan carry their reply as a JSON string)."""
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _openai_response(model: str, turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in turn.tool_calls
        ]
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": turn.finish_reason or "stop",
            }
        ],
    }
