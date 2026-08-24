import { expect, test as base } from "@playwright/test";

type State = {
  candidates: any[];
  memories: any[];
  connected: boolean;
  sourceTotal: number;
  projects: any[];
  sessions: any[];
  sessionMessages: Record<string, any[]>;
  sessionMessageDelay: Record<string, number>;
};

const connector = (connected: boolean) => ({
  name: "traex",
  title: "TRAE CLI",
  icon: "T",
  blurb: "Import local TRAE CLI conversations.",
  auth: "local_app",
  two_way: false,
  channels: false,
  available: true,
  fields: [],
  instructions: [],
  connected,
  account: connected ? "TRAE CLI local" : null,
  enabled: connected,
  brand_color: "#0052d9",
  logo: "traex",
  allowed_users: [],
  tools: [],
  managed: false,
  managed_profile: false,
});

async function mockApi(page, state: State) {
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/v1/health") {
      return route.fulfill({
        json: {
          status: "ok",
          app_version: "0.2.0",
          core_version: "0.2.0",
          schema_version: 2,
          default_workspace: null,
          model: "gpt-test",
        },
      });
    }
    if (path === "/v1/settings") {
      return route.fulfill({
        json: {
          provider: "openai",
          onboarded: true,
          model: "gpt-test",
          models: ["gpt-test"],
          has_key: true,
          model_ready: true,
          source: "store",
          surfaces: { link: true, chat: false, code: false },
          scratch_base: "/mock/Smallink",
          secrets_path: "/mock/secrets.json",
          model_labels: { "gpt-test": "Test model" },
        },
      });
    }
    if (path === "/v1/projects") {
      return route.fulfill({ json: { projects: state.projects } });
    }
    if (path === "/v1/apps") {
      const now = new Date().toISOString();
      return route.fulfill({
        json: {
          apps: [
            {
              schema_version: "smallink.app/v1",
              app_id: "minem",
              name: "MineM",
              description: "Search, create, and manage the local MineM material library.",
              icon: "minem",
              runtime_kind: "local_cli",
              connector_id: "minem",
              system_project_id: "system:minem",
              system_project_name: "MineM material library",
              default_agent: "link",
              capabilities: ["asset.list", "asset.search", "asset.get", "import.page"],
              memory_types: ["artifact_summary", "document_insight"],
              instance: {
                app_id: "minem",
                enabled: true,
                install_state: "installed",
                runtime_state: "available",
                app_version: "0.5.0-beta.9",
                protocol_version: 1,
                status: {},
              },
              runtime: {
                health: "running",
                cli_available: true,
                app_version: "0.5.0-beta.9",
              },
              project: {
                project_id: "system:minem",
                name: "MineM material library",
                icon: "M",
                workspace_path: "",
                description: "",
                status: "active",
                default_agent: "link",
                default_model: "gpt-test",
                pinned: true,
                sort_order: -100,
                project_type: "system_app",
                owner_app_id: "minem",
                system_key: "minem",
                session_count: 0,
                created_at: now,
                updated_at: now,
              },
            },
          ],
        },
      });
    }
    if (path === "/v1/apps/minem/assets") {
      return route.fulfill({
        json: {
          ok: true,
          project_id: "system:minem",
          items: [
            {
              id: "page-1",
              code: "CTRL-APPTEST-001",
              type: "page",
              title: "Smallink architecture",
            },
          ],
        },
      });
    }
    if (path === "/v1/sessions") {
      return route.fulfill({ json: { sessions: state.sessions } });
    }
    if (path === "/v1/workspaces/recent") {
      return route.fulfill({ json: { workspaces: [] } });
    }
    if (path === "/v1/personas") {
      return route.fulfill({
        json: {
          personas: [
            {
              id: "link",
              name: "Smallink",
              icon: "link",
              tagline: "General agent",
              family: "knowledge",
              enabled: true,
              surfaced: true,
              default: true,
              needs_workspace: false,
            },
          ],
        },
      });
    }
    if (path === "/v1/automations") {
      return route.fulfill({ json: { tasks: [] } });
    }
    if (path === "/v1/cloud/status") {
      return route.fulfill({
        json: { available: false, signed_in: false, account: "", user_id: "" },
      });
    }
    if (path === "/v1/connectors/slack/status") {
      return route.fulfill({
        json: {
          mode: "",
          relay: { state: "offline", reconnects: 0, last_event_at: null, last_error: "" },
          signed_in: false,
          teams: {},
        },
      });
    }
    if (path === "/v1/connectors") {
      return route.fulfill({
        json: {
          connectors: [
            {
              ...connector(false),
              name: "minem",
              title: "MineM",
              logo: "minem",
            },
            {
              ...connector(false),
              name: "codex",
              title: "Codex",
              logo: "codex",
            },
            connector(state.connected),
          ],
        },
      });
    }
    if (path === "/v1/connectors/traex/connect" && method === "POST") {
      state.connected = true;
      return route.fulfill({
        json: {
          ok: true,
          account: "TRAE CLI local",
          sessions_path: "/mock/.trae/cli/sessions",
          probe: { ok: true, valid_sessions_found: 2 },
        },
      });
    }
    if (path === "/v1/connectors/traex/sync" && method === "POST") {
      state.sourceTotal = 2;
      return route.fulfill({
        json: {
          job_id: "sync-1",
          sessions_read: 2,
          turns_seen: 2,
          records_ingested: 2,
          sync: {
            job_id: "sync-1",
            connector: "traex",
            status: "completed",
            root_path: "/mock/.trae/cli/sessions",
            files_scanned: 2,
            sessions_read: 2,
            records_seen: 2,
            records_ingested: 2,
            files_failed: 0,
            started_at: new Date().toISOString(),
            finished_at: new Date().toISOString(),
            error: null,
          },
        },
      });
    }
    if (path === "/v1/connectors/traex/sync-status") {
      return route.fulfill({ json: { sync: null } });
    }
    if (path === "/v1/memory") {
      return route.fulfill({ json: { memory: state.memories } });
    }
    if (path === "/v1/memory/candidates" && method === "GET") {
      return route.fulfill({ json: { candidates: state.candidates } });
    }
    if (path === "/v1/memory/candidates/confidence-summary") {
      return route.fulfill({
        json: {
          total_pending: state.candidates.length,
          tiers: {
            high: state.candidates.filter((item) => Number(item.confidence) >= 0.9).length,
            medium: 0,
            low: 0,
            unscored: 0,
          },
        },
      });
    }
    if (path === "/v1/memory/governance/tasks") {
      return route.fulfill({ json: { tasks: [] } });
    }
    if (path === "/v1/memory/governance/schedule") {
      return route.fulfill({
        json: {
          enabled: false,
          interval_minutes: 60,
          batch_limit: 50,
          last_run_at: null,
          next_run_at: null,
          last_result: null,
          running: false,
        },
      });
    }
    if (path === "/v1/memory/usage-history") {
      return route.fulfill({ json: { records: [] } });
    }
    if (path === "/v1/memory/pipeline/run" && method === "POST") {
      state.candidates = [
        {
          candidate_id: "candidate-1",
          task_id: "governance-1",
          content: "Prefers concise product reports.",
          memory_type: "user_preference",
          scope: "global",
          workspace: null,
          session_id: null,
          status: "pending",
          confidence: 0.9,
          model: "gpt-test",
          prompt_version: "v2",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          sources: ["source-1"],
        },
      ];
      return route.fulfill({
        json: {
          task_id: "governance-1",
          status: "completed",
          processed_records: 1,
          candidates_created: 1,
          skipped_records: 0,
          failed_records: 0,
        },
      });
    }
    if (path === "/v1/memory/candidates/candidate-1" && method === "GET") {
      return route.fulfill({
        json: { ...state.candidates[0], source_records: [] },
      });
    }
    if (
      path === "/v1/memory/candidates/candidate-1/decision" &&
      method === "POST"
    ) {
      state.memories.push({
        id: 1,
        scope: "global",
        content: state.candidates[0].content,
        key: "user_preference",
        workspace: null,
        session_id: null,
        created_at: new Date().toISOString(),
        status: "active",
      });
      state.candidates = [];
      return route.fulfill({ json: { ok: true, memory_id: 1 } });
    }
    if (path === "/v1/sensory-records/stats") {
      return route.fulfill({
        json: {
          total: state.sourceTotal,
          pending: state.sourceTotal,
          sources: state.sourceTotal ? { traex: state.sourceTotal } : {},
        },
      });
    }
    if (path === "/v1/sensory-records") {
      return route.fulfill({
        json: { records: [], total: state.sourceTotal, limit: 50, offset: 0 },
      });
    }
    if (path.startsWith("/v1/inbox")) {
      return route.fulfill({ json: path.endsWith("/routing") ? { bindings: [] } : { items: [] } });
    }
    if (path === "/v1/unrouted") return route.fulfill({ json: { items: [] } });
    if (path === "/v1/channels/recent") return route.fulfill({ json: { channels: [] } });
    if (path === "/v1/tasks") return route.fulfill({ json: { tasks: [] } });
    if (path === "/v1/agent-collaborations") {
      return route.fulfill({ json: { collaborations: [] } });
    }
    if (path === "/v1/audit") return route.fulfill({ json: { events: [] } });
    const sessionMessageMatch = path.match(/^\/v1\/sessions\/([^/]+)\/messages$/);
    if (sessionMessageMatch) {
      const sessionId = decodeURIComponent(sessionMessageMatch[1]);
      const delay = state.sessionMessageDelay[sessionId] || 0;
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      return route.fulfill({ json: { messages: state.sessionMessages[sessionId] || [] } });
    }
    if (path.includes("/artifacts")) return route.fulfill({ json: { artifacts: [] } });
    return route.fulfill({ json: {} });
  });

  await page.routeWebSocket("**/ws/session/**", async (webSocket) => {
    webSocket.onMessage((message) => {
      const payload = JSON.parse(String(message));
      if (payload.type !== "user_message") return;
      if (payload.client_message_id) {
        webSocket.send(
          JSON.stringify({
            type: "message_accepted",
            data: { client_message_id: payload.client_message_id },
          }),
        );
      }
      webSocket.send(JSON.stringify({ type: "turn_start", data: { input: payload.text } }));
      webSocket.send(JSON.stringify({ type: "assistant_delta", data: { text: "Echo: " } }));
      webSocket.send(
        JSON.stringify({ type: "assistant_message", data: { text: `Echo: ${payload.text}` } }),
      );
      webSocket.send(
        JSON.stringify({ type: "turn_end", data: { status: "completed", iterations: 1 } }),
      );
      webSocket.send(JSON.stringify({ type: "turn_done", data: {} }));
    });
    webSocket.send(
      JSON.stringify({
        type: "ready",
        data: {
          session_id: "e2e-session",
          agent: "link",
          model: "gpt-test",
          mode: "interactive",
          workspace: null,
          command_trust: {},
        },
      }),
    );
  });
  await page.routeWebSocket("**/ws/events", async () => {});
}

export const test = base.extend<{ productState: State }>({
  productState: [
    async ({ page }, use) => {
      const state: State = {
        candidates: [],
        memories: [],
        connected: false,
        sourceTotal: 1,
        projects: [],
        sessions: [],
        sessionMessages: {},
        sessionMessageDelay: {},
      };
      await page.addInitScript(() => {
        (window as any).__LINK_HTTP__ = ".";
        (window as any).__LINK_WS__ = "ws://localhost:5199";
      });
      await mockApi(page, state);
      await use(state);
    },
    { auto: true },
  ],
});

export { expect };
