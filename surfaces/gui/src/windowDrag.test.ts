import { describe, expect, it } from "vitest";
import { shouldStartWindowDrag } from "./windowDrag";

describe("shouldStartWindowDrag", () => {
  it("allows a primary-button drag from a non-interactive top-strip element", () => {
    const title = document.createElement("span");
    expect(shouldStartWindowDrag({ button: 0, clientY: 24, target: title })).toBe(true);
  });

  it("does not turn controls in the top strip into drag handles", () => {
    const button = document.createElement("button");
    const icon = document.createElement("span");
    button.appendChild(icon);

    expect(shouldStartWindowDrag({ button: 0, clientY: 24, target: icon })).toBe(false);
  });

  it("ignores content below the title strip and non-primary pointer buttons", () => {
    const content = document.createElement("div");
    expect(shouldStartWindowDrag({ button: 0, clientY: 49, target: content })).toBe(false);
    expect(shouldStartWindowDrag({ button: 2, clientY: 24, target: content })).toBe(false);
  });
});
