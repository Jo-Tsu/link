# Smallink Desktop UI

A thin client of Smallink Core (model-provider API + WebSocket event/approval stream).
The same codebase runs in a browser during development and inside Smallink Desktop.

## First time: bootstrap the Python backend

A fresh checkout has no server to run — create the venv both flows below expect:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[messaging,dev]"
```

## Run it (browser, two terminals)

1. **Start the server** (needs a model key, e.g. `OPENAI_API_KEY`, in the environment —
   or add one later in the app's Settings):
   ```bash
   cd /path/to/Smallink
   ./.venv/bin/smallink-server --cwd /path/to/your/project --port 42871
   ```
2. **Start the UI:**
   ```bash
   cd surfaces/gui
   npm install      # first time
   npm run dev      # → http://127.0.0.1:41737
   ```

Open http://127.0.0.1:41737. The UI talks to `http://127.0.0.1:42871` (override with
`VITE_LINK_HTTP` / `VITE_LINK_WS`). Start the server before Vite so the
UI can read its per-launch token from `<state-dir>/sidecar-42871.token`; restart
Vite if the server is restarted.

## Run the desktop app from source

The Tauri shell wraps the same UI and supervises the Python server itself — no separate
terminal. It needs the Rust toolchain (`rustup`) plus the venv from the bootstrap step;
in dev it finds the server at `.venv/bin/smallink-server` automatically (a
packaged sidecar binary is only produced by the release scripts in `packaging/`).

```bash
cd surfaces/gui
npm install        # first time
npm run tauri dev  # builds the shell, launches the window, starts the server
```

## Tests

```bash
npx tsc --noEmit && npx vitest run   # typecheck + unit
npx playwright test                  # hermetic e2e (mocked /v1 + WS, no Python needed)
```
