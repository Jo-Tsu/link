import { afterEach, describe, expect, it, vi } from "vitest";
import { openExternal } from "./tauri";

afterEach(() => {
  delete (globalThis as any).__TAURI__;
  vi.restoreAllMocks();
});

describe("openExternal", () => {
  it("rejects unsafe and malformed protocols", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    expect(openExternal("javascript:alert(1)")).toBe(false);
    expect(openExternal("not a url")).toBe(false);
    expect(open).not.toHaveBeenCalled();
  });

  it("uses the native opener in desktop builds", () => {
    const openUrl = vi.fn().mockResolvedValue(undefined);
    (globalThis as any).__TAURI__ = { opener: { openUrl } };
    expect(openExternal("https://example.com/docs")).toBe(true);
    expect(openUrl).toHaveBeenCalledWith("https://example.com/docs");
  });
});
