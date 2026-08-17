import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Markdown, OPEN_ARTIFACT_EVENT } from "./Markdown";
import { openExternal } from "../tauri";

vi.mock("../tauri", () => ({ openExternal: vi.fn() }));

afterEach(cleanup);

// §34 (UX-016): [Title](artifact:path) renders as a chip that opens the artifact viewer via
// a window event; ordinary links keep the open-externally treatment.
describe("Markdown artifact links", () => {
  it("renders an artifact: link as a chip and dispatches the open event with the path", () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail.path);
    window.addEventListener(OPEN_ARTIFACT_EVENT, listener);

    render(<Markdown text="Done — [Semiconductor dashboard](artifact:reports/semi.html)" />);
    const chip = screen.getByTestId("artifact-chip");
    expect(chip.textContent).toContain("Semiconductor dashboard");
    expect(chip.textContent).toContain("semi.html"); // filename shown under the title
    fireEvent.click(chip);
    expect(seen).toEqual(["reports/semi.html"]);

    window.removeEventListener(OPEN_ARTIFACT_EVENT, listener);
  });

  it("ordinary links stay external and never become chips", () => {
    const { container } = render(<Markdown text="see [the docs](https://example.com)" />);
    expect(screen.queryByTestId("artifact-chip")).toBeNull();
    const a = container.querySelector("a")!;
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("href")).toBe("https://example.com");
    fireEvent.click(a);
    expect(openExternal).toHaveBeenCalledWith("https://example.com");
  });

  it("chip title falls back to the filename when the link text is empty", () => {
    vi.spyOn(window, "dispatchEvent");
    render(<Markdown text="[](artifact:out/report.pdf)" />);
    expect(screen.getByTestId("artifact-chip").textContent).toContain("report.pdf");
  });

  it("decodes Chinese artifact paths before displaying and opening them", () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail.path);
    window.addEventListener(OPEN_ARTIFACT_EVENT, listener);

    render(<Markdown text="[老板方案](artifact:交付/老板专属-BD-驾驶舱.md)" />);
    const chip = screen.getByTestId("artifact-chip");
    expect(chip.getAttribute("title")).toBe("交付/老板专属-BD-驾驶舱.md");
    expect(chip.textContent).toContain("老板专属-BD-驾驶舱.md");
    fireEvent.click(chip);
    expect(seen).toEqual(["交付/老板专属-BD-驾驶舱.md"]);

    window.removeEventListener(OPEN_ARTIFACT_EVENT, listener);
  });

  it("treats a relative deliverable link without artifact: as an artifact chip", () => {
    render(<Markdown text="[老板看板](VIP_Band/deliverables/老板看板方案.md)" />);
    expect(screen.getByTestId("artifact-chip").getAttribute("title")).toBe(
      "VIP_Band/deliverables/老板看板方案.md",
    );
  });
});
