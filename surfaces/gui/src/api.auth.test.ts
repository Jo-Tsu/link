import { afterEach, expect, it, vi } from "vitest";
import { getHealth, Session } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("authenticates REST and session WebSocket calls with the launch token", async () => {
  vi.stubGlobal("__LINK_API_TOKEN__", "launch-token");
  const request = vi.fn(async (_url: string, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("X-Link-Token")).toBe("launch-token");
    return { json: async () => ({ status: "ok" }) } as Response;
  });
  vi.stubGlobal("fetch", request);

  class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    readyState = FakeWebSocket.CONNECTING;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    send = vi.fn();

    constructor(
      public readonly url: string,
      public readonly protocols?: string | string[],
    ) {}
  }
  vi.stubGlobal("WebSocket", FakeWebSocket);

  await getHealth();
  expect(request).toHaveBeenCalledOnce();

  const session = new Session("s1", "/workspace", "code", { onEvent: vi.fn() });
  const socket = (session as unknown as { ws: FakeWebSocket }).ws;
  expect(socket.protocols).toEqual(["link", "launch-token"]);
});

it("reconnects and replays only unacknowledged user messages", () => {
  vi.useFakeTimers();
  vi.stubGlobal("__LINK_API_TOKEN__", "launch-token");
  const sockets: FakeWebSocket[] = [];

  class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    readyState = FakeWebSocket.CONNECTING;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    send = vi.fn();
    close = vi.fn();

    constructor(
      public readonly url: string,
      public readonly protocols?: string | string[],
    ) {
      sockets.push(this);
    }

    open() {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.();
    }

    disconnect() {
      this.readyState = 3;
      this.onclose?.();
    }
  }
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("crypto", { randomUUID: () => "client-message-1" });

  const onReconnect = vi.fn();
  const session = new Session("s1", "/workspace", "code", {
    onEvent: vi.fn(),
    onReconnect,
  });
  sockets[0].open();
  session.userMessage("hello");
  expect(sockets[0].send).toHaveBeenCalledOnce();

  sockets[0].disconnect();
  vi.advanceTimersByTime(500);
  expect(sockets).toHaveLength(2);
  sockets[1].open();
  expect(onReconnect).toHaveBeenCalledOnce();
  expect(sockets[1].send).toHaveBeenCalledOnce();

  sockets[1].onmessage?.({
    data: JSON.stringify({
      type: "message_accepted",
      data: { client_message_id: "client-message-1" },
    }),
  } as MessageEvent);
  sockets[1].disconnect();
  vi.advanceTimersByTime(500);
  sockets[2].open();
  expect(sockets[2].send).not.toHaveBeenCalled();

  session.close();
});
