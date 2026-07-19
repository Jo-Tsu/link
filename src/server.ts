import "./lib/error-capture";

import { consumeLastCapturedError } from "./lib/error-capture";
import { renderErrorPage } from "./lib/error-page";

type ServerEntry = {
  fetch: (request: Request, env: unknown, ctx: unknown) => Promise<Response> | Response;
};

let serverEntryPromise: Promise<ServerEntry> | undefined;

async function getServerEntry() {
  if (!serverEntryPromise) {
    serverEntryPromise = import("@tanstack/react-start/server-entry").then(
      (module) => (module.default ?? module) as ServerEntry,
    );
  }
  return serverEntryPromise;
}

async function normalizeCatastrophicSsrResponse(response: Response) {
  if (response.status < 500 || !response.headers.get("content-type")?.includes("application/json"))
    return response;
  const body = await response.clone().text();
  if (!body.includes('"unhandled":true') || !body.includes('"message":"HTTPError"'))
    return response;
  console.error(consumeLastCapturedError() ?? new Error(`SSR error: ${body}`));
  return new Response(renderErrorPage(), {
    status: 500,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

async function intakeApi(request: Request): Promise<Response | undefined> {
  const url = new URL(request.url);
  if (url.pathname === "/api/crawler" || url.pathname.startsWith("/api/crawler/")) {
    const crawlerBaseUrl = process.env.CRAWLER_API_URL || "http://127.0.0.1:18744/api";
    const crawlerPath = url.pathname.slice("/api/crawler".length).replace(/^\//, "");
    const upstream = new URL(`${crawlerBaseUrl.replace(/\/$/, "")}/${crawlerPath}${url.search}`);
    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);

    try {
      const response = await fetch(upstream, {
        method: request.method,
        headers,
        body:
          request.method === "GET" || request.method === "HEAD"
            ? undefined
            : await request.arrayBuffer(),
      });
      const responseHeaders = new Headers();
      for (const name of ["content-type", "content-disposition", "cache-control"]) {
        const value = response.headers.get(name);
        if (value) responseHeaders.set(name, value);
      }
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          error: error instanceof Error ? error.message : "Crawler service is unavailable",
        },
        { status: 502 },
      );
    }
  }
  const database = await import("./lib/server-db");
  const bearerToken = () => request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || "";
  const jsonBody = async () => (await request.json()) as Record<string, unknown>;
  if (url.pathname === "/api/health") {
    try {
      return Response.json({
        ok: true,
        service: "link",
        database: await database.getDatabaseStatus(),
      });
    } catch (error) {
      return Response.json({
        ok: true,
        service: "link",
        database: {
          connected: false,
          error: error instanceof Error ? error.message : "Database check failed",
        },
      });
    }
  }
  if (url.pathname === "/api/connectors/status") {
    if (request.method !== "GET")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      return Response.json({ ok: true, ...(await database.getConnectorStatus()) });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          connected: false,
          connectors: [],
          error: error instanceof Error ? error.message : "Failed to read connectors",
        },
        { status: 500 },
      );
    }
  }
  if (url.pathname === "/api/settings") {
    try {
      if (request.method === "GET") {
        return Response.json({ ok: true, ...(await database.getRuntimeConfigs()) });
      }
      if (request.method === "PUT") {
        const body = (await request.json()) as {
          id?: string;
          enabled?: boolean;
          status?: string;
          config?: Record<string, unknown>;
        };
        if (!body.id || typeof body.id !== "string") {
          return Response.json(
            { ok: false, error: "Configuration id is required" },
            { status: 400 },
          );
        }
        return Response.json({
          ok: true,
          config: await database.updateRuntimeConfig(body.id, {
            enabled: typeof body.enabled === "boolean" ? body.enabled : undefined,
            status: typeof body.status === "string" ? body.status.slice(0, 60) : undefined,
            config: body.config && typeof body.config === "object" ? body.config : undefined,
          }),
        });
      }
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    } catch (error) {
      return Response.json(
        { ok: false, error: error instanceof Error ? error.message : "Failed to update settings" },
        { status: 500 },
      );
    }
  }
  if (url.pathname === "/api/agents/pairing-codes") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      return Response.json({ ok: true, ...(await database.createAgentPairingCode()) });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          error: error instanceof Error ? error.message : "Failed to create pairing code",
        },
        { status: 500 },
      );
    }
  }
  if (url.pathname === "/api/agents") {
    if (request.method !== "GET")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      return Response.json({ ok: true, ...(await database.getAgents()) });
    } catch (error) {
      return Response.json(
        { ok: false, error: error instanceof Error ? error.message : "Failed to read agents" },
        { status: 500 },
      );
    }
  }
  if (url.pathname === "/api/agents/pair") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      const body = await jsonBody();
      if (typeof body.code !== "string" || typeof body.publicKey !== "string") {
        return Response.json(
          { ok: false, error: "Pairing code and public key are required" },
          { status: 400 },
        );
      }
      return Response.json({
        ok: true,
        ...(await database.pairAgent({
          code: body.code,
          publicKey: body.publicKey,
          displayName: typeof body.displayName === "string" ? body.displayName : "Link Agent",
          version: typeof body.version === "string" ? body.version : "",
          operatingSystem: typeof body.operatingSystem === "string" ? body.operatingSystem : "",
        })),
      });
    } catch (error) {
      return Response.json(
        { ok: false, error: error instanceof Error ? error.message : "Failed to pair agent" },
        { status: 400 },
      );
    }
  }
  if (url.pathname === "/api/agents/heartbeat") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      const body = await jsonBody();
      if (typeof body.agentId !== "string") {
        return Response.json({ ok: false, error: "Agent id is required" }, { status: 400 });
      }
      return Response.json({
        ok: true,
        ...(await database.heartbeatAgent({
          agentId: body.agentId,
          token: bearerToken(),
          version: typeof body.version === "string" ? body.version : "",
          operatingSystem: typeof body.operatingSystem === "string" ? body.operatingSystem : "",
          connectorStates: body.connectorStates,
          lastCommandId: typeof body.lastCommandId === "string" ? body.lastCommandId : "",
        })),
      });
    } catch (error) {
      return Response.json(
        { ok: false, error: error instanceof Error ? error.message : "Agent heartbeat failed" },
        { status: 401 },
      );
    }
  }
  if (url.pathname === "/api/agents/ingestion-batches") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      const body = await jsonBody();
      if (
        typeof body.agentId !== "string" ||
        typeof body.batchId !== "string" ||
        typeof body.connectorId !== "string"
      ) {
        return Response.json(
          { ok: false, error: "Agent, batch and connector are required" },
          { status: 400 },
        );
      }
      return Response.json({
        ok: true,
        ...(await database.ingestAgentBatch({
          agentId: body.agentId,
          token: bearerToken(),
          batchId: body.batchId,
          connectorId: body.connectorId,
          cursorBefore: body.cursorBefore as Record<string, unknown> | undefined,
          cursorAfter: body.cursorAfter as Record<string, unknown> | undefined,
          records: Array.isArray(body.records) ? (body.records as never[]) : [],
        })),
      });
    } catch (error) {
      return Response.json(
        { ok: false, error: error instanceof Error ? error.message : "Batch ingestion failed" },
        { status: 400 },
      );
    }
  }
  if (url.pathname === "/api/agents/commands") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      const body = await jsonBody();
      const allowed = new Set([
        "sync_connector",
        "validate_connector",
        "refresh_config",
        "pause_connector",
      ]);
      if (
        typeof body.agentId !== "string" ||
        typeof body.type !== "string" ||
        !allowed.has(body.type)
      ) {
        return Response.json({ ok: false, error: "Invalid agent command" }, { status: 400 });
      }
      return Response.json({
        ok: true,
        ...(await database.enqueueAgentCommand({
          agentId: body.agentId,
          type: body.type as
            "sync_connector" | "validate_connector" | "refresh_config" | "pause_connector",
          payload:
            body.payload && typeof body.payload === "object"
              ? (body.payload as Record<string, unknown>)
              : {},
        })),
      });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          error: error instanceof Error ? error.message : "Failed to queue agent command",
        },
        { status: 400 },
      );
    }
  }
  if (url.pathname === "/api/agents/commands/complete") {
    if (request.method !== "POST")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      const body = await jsonBody();
      if (typeof body.agentId !== "string" || typeof body.commandId !== "string") {
        return Response.json(
          { ok: false, error: "Agent and command id are required" },
          { status: 400 },
        );
      }
      return Response.json({
        ok: true,
        ...(await database.completeAgentCommand({
          agentId: body.agentId,
          token: bearerToken(),
          commandId: body.commandId,
          success: body.success === true,
          result:
            body.result && typeof body.result === "object"
              ? (body.result as Record<string, unknown>)
              : {},
        })),
      });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          error: error instanceof Error ? error.message : "Failed to complete agent command",
        },
        { status: 400 },
      );
    }
  }
  if (url.pathname === "/api/data-sources/origins") {
    if (request.method !== "GET")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      return Response.json({
        ok: true,
        ...(await database.getDataSourceOrigins({
          source: url.searchParams.get("source") || "all",
          query: url.searchParams.get("q") || "",
          limit: Number(url.searchParams.get("limit") || 30),
          offset: Number(url.searchParams.get("offset") || 0),
        })),
      });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          connected: false,
          origins: [],
          error: error instanceof Error ? error.message : "Failed to read data origins",
        },
        { status: 500 },
      );
    }
  }
  if (url.pathname === "/api/sensory-records") {
    if (request.method !== "GET")
      return Response.json({ ok: false, error: "Method not allowed" }, { status: 405 });
    try {
      return Response.json({
        ok: true,
        ...(await database.getSensoryRecords({
          source: url.searchParams.get("source") || "all",
          rawType: url.searchParams.get("rawType") || "all",
          threadIds: (url.searchParams.get("threadIds") || "").split(",").filter(Boolean),
          containerIds: (url.searchParams.get("containerIds") || "").split(",").filter(Boolean),
          originKeys: (url.searchParams.get("originKeys") || "").split(",").filter(Boolean),
          query: url.searchParams.get("q") || "",
          limit: Number(url.searchParams.get("limit") || 80),
          offset: Number(url.searchParams.get("offset") || 0),
        })),
      });
    } catch (error) {
      return Response.json(
        {
          ok: false,
          connected: false,
          records: [],
          error: error instanceof Error ? error.message : "Failed to read sensory records",
        },
        { status: 500 },
      );
    }
  }
  return undefined;
}

export default {
  async fetch(request: Request, env: unknown, ctx: unknown) {
    try {
      const apiResponse = await intakeApi(request);
      if (apiResponse) return apiResponse;
      return await normalizeCatastrophicSsrResponse(
        await (await getServerEntry()).fetch(request, env, ctx),
      );
    } catch (error) {
      console.error(error);
      return new Response(renderErrorPage(), {
        status: 500,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }
  },
};
