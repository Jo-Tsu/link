import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getArtifacts, readArtifact } from "../api";
import { OPEN_ARTIFACT_EVENT } from "./Markdown";
import { RightRail } from "./RightRail";

vi.mock("../api", () => ({
  getArtifacts: vi.fn(),
  readArtifact: vi.fn(),
  revealArtifact: vi.fn(),
}));

const artifact = {
  path: "VIP_Band/deliverables/老板专属-BD-驾驶舱.md",
  abs_path: "/workspace/VIP_Band/deliverables/老板专属-BD-驾驶舱.md",
  name: "老板专属-BD-驾驶舱.md",
  kind: "markdown",
  size: 128,
  modified_at: 1,
};

const props = {
  sessionId: "session-1",
  refreshKey: 0,
  toolNames: [],
  todo: [],
  running: false,
  showArtifacts: true,
};

beforeEach(() => {
  vi.mocked(getArtifacts).mockResolvedValue([artifact]);
  vi.mocked(readArtifact).mockResolvedValue({
    ok: true,
    path: artifact.path,
    kind: "markdown",
    content: "# 老板驾驶舱",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RightRail artifact deep links", () => {
  it("keeps an encoded artifact click while the rail is hidden and opens it when shown", async () => {
    const view = render(<RightRail {...props} active={false} />);

    fireEvent(
      window,
      new CustomEvent(OPEN_ARTIFACT_EVENT, {
        detail: {
          path: "VIP_Band/deliverables/%E8%80%81%E6%9D%BF%E4%B8%93%E5%B1%9E-BD-%E9%A9%BE%E9%A9%B6%E8%88%B1.md",
        },
      }),
    );

    await waitFor(() => expect(getArtifacts).toHaveBeenCalledWith("session-1"));
    view.rerender(<RightRail {...props} active />);

    await waitFor(() => {
      expect(readArtifact).toHaveBeenCalledWith("session-1", artifact.path);
      expect(screen.getByText("老板驾驶舱")).toBeTruthy();
    });
  });
});
