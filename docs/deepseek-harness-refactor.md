# Smallink Harness-Style Runtime Refactor

Updated: 2026-08-23

## Decision

Smallink will adopt the structural lessons of DeepSeek Harness without importing Cordis or turning the desktop product into a general plugin platform. The target is a small, explicit Python runtime with four properties:

1. Every live session has one lifecycle owner.
2. Capabilities are supplied through narrow protocols at the composition root.
3. Durable facts, live runtime signals, and UI projections have different owners.
4. Registrations that allocate behavior or resources expose an idempotent disposer.

The public FastAPI, WebSocket, React, Tauri, data-directory, and memory-governance contracts remain stable throughout the migration.

## What We Adopt From DeepSeek Harness

| Harness principle | Smallink translation |
| --- | --- |
| Service Definition / Provider / Consumer | Python Protocols in `capabilities.py`; concrete providers are assembled outside `TurnEngine`. |
| Fiber-owned effects | `RuntimeScope` owns one session engine and releases callbacks/resources in reverse order. |
| One runtime inventory | `RuntimeRegistry` owns engine, execution claim, lifecycle tracker, and teardown for each session. |
| Scoped registration | Tool and prompt contributions are registered into a session runtime instead of being assembled by one monolithic function. |
| Durable session events | Model-visible facts must be reconstructable; live deltas remain transport events. |
| Explicit plugin manifests | Ordered Python tuples of trusted built-in capability factories; no directory scanning or dynamic third-party imports. |
| Runtime invariants | Tests assert event transitions, ownership, route contracts, and composition parity. |

## What We Deliberately Do Not Adopt

- No Cordis dependency or second JavaScript runtime in the Python sidecar.
- No YAML composition, multi-layer patch language, arbitrary module loading, or HMR.
- No service locator available throughout business code. Dependencies remain constructor arguments.
- No attempt to make projects, memories, UI components, or ordinary domain records into plugins.
- No default waterfall event bus. Interception remains explicit and limited to model/tool policy pipelines.

## Target Layers

```text
FastAPI / WebSocket / Tauri compatibility shell
                       |
              application services
                       |
        RuntimeRegistry + RuntimeScope
                       |
       capability composition / manifests
                       |
 TurnEngine + domain protocols + session events
                       |
 providers / connectors / stores / host adapters
```

Transport code depends on narrow application services. The engine depends on protocols. Concrete SQLite, connector, subprocess, and model implementations are created only at the composition root.

## State Ownership

| State class | Authority | Examples |
| --- | --- | --- |
| Durable facts | append-only session/runtime storage | user messages, assistant messages, tool calls/results, approvals, terminal outcomes |
| Live runtime state | `RuntimeScope` | execution claim, phase, engine, process resources |
| UI projection | `useAgentLifecycle` + transcript reducer | busy/connected, stream buffer, visible transcript |

No second map or boolean may independently claim to be authoritative for the same state.

## Implemented Shape

### Runtime ownership and truthful lifecycle

- Introduce `RuntimeScope` and `RuntimeRegistry`.
- Replace parallel engine/running/tracker maps with one runtime inventory.
- Make lifecycle projection handle streaming, non-streaming, approval, resume, error, and interruption event sequences.
- Make `useAgentLifecycle` own connected, busy, stream, and reasoning state.
- Pass capabilities from `SessionManager` into `build_engine`; make `TurnEngine` depend on protocols.
- Add lifecycle, ownership, capability-container, and frontend reducer tests.

### Explicit capability contributions

- Connector tools use explicit, ordered Python factory tuples; there is no dynamic discovery.
- Prompt sections use named, ordered contributions with source and scope metadata.
- `CapabilityContainer` is a small typed input to `build_engine()`, not a general service locator.
- Duplicate connector tool names and prompt contribution ids are rejected during assembly.

### Connector tools

- Connector tool factories are grouped by domain under `connectors/tools_domain/`.
- `integration_tools.py` remains a deliberately small compatibility entry point, including its request-injection test seam.
- Tool names, order, schemas, metadata, signatures, and docstrings are covered by parity tests.

### Prompt and event projections

- Turn the existing prompt layers into named, ordered, source-attributed contributions.
- `/v1/prompts` derives its layer metadata from the same registries used by runtime assembly.
- Separate durable session facts from live `agent/*` signals and capability policy events.
- Make WebSocket frames a stable projection rather than the internal event vocabulary itself.

### Control-plane services

- Session runtime, app/project, memory/knowledge/governance, and settings/provider behavior live in explicit services.
- Their routers call the services directly; `SessionManager` keeps only explicit one-line compatibility facades where existing Python callers still depend on them.
- Automation, gateway, Inbox, and the WebSocket orchestration remain in `SessionManager`/`app.py` because splitting them now would increase coordination risk without removing duplicate state.
- Loopback callback-page rendering lives in `server/loopback_pages.py`, so routers no longer import the application composition root.

## Compatibility And Rollback

- Existing REST paths, request bodies, storage paths, and persisted schemas remain compatible. WebSocket `ready` gained additive `phase` and `busy` fields so reconnecting views can restore live state.
- No model call, tool execution, or user-data write is duplicated for shadow comparison.
- Permission plugins may narrow access but cannot bypass `PermissionEngine`.
- A failed session assembly is never published into the runtime registry.
- Runtime teardown is idempotent and happens in reverse registration order.
- No database migration is required. Runtime rollback is a source-version rollback; there is no hidden legacy composition switch or duplicate implementation.
- Scheduled memory governance creates review candidates only. A memory becomes active only through an explicit user decision.

## Acceptance Gates

- All backend and frontend tests pass.
- Production GUI build succeeds.
- OpenAPI and WebSocket public contracts remain stable.
- Streaming, non-streaming, tool, approval, durable-resume, error, and interrupt sequences end in the expected lifecycle state.
- Each live session appears exactly once in the runtime registry.
- Session deletion, skill invalidation, and server shutdown release owned resources exactly once.
- Composition tests verify tool names, schemas, risk metadata, provider selection, prompt layers, and permission mode.
