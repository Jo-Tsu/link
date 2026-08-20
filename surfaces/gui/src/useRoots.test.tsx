import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { addRoot, getRoots, removeRoot } from "./api";
import { useRoots } from "./useRoots";

vi.mock("./api", () => ({
  addRoot: vi.fn(),
  getRoots: vi.fn(),
  removeRoot: vi.fn(),
}));

function Harness({ action }: { action: "add" | "toggle" | "remove" }) {
  const roots = useRoots("session-1");
  const run = () => {
    if (action === "add") return roots.addRoot("/tmp/source", false);
    if (action === "toggle") {
      return roots.toggleAccess({
        path: "/tmp/source",
        label: "source",
        writable: false,
        primary: false,
        exists: true,
      });
    }
    return roots.removeRoot("/tmp/source");
  };
  return (
    <div>
      <button onClick={() => void run()}>run</button>
      <span data-testid="busy">{String(roots.busy)}</span>
      <span data-testid="error">{roots.error}</span>
    </div>
  );
}

describe("useRoots mutations", () => {
  beforeEach(() => {
    vi.mocked(getRoots).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it.each(["add", "toggle"] as const)("recovers when %s fails", async (action) => {
    vi.mocked(addRoot).mockRejectedValue(new Error("directory service unavailable"));
    render(<Harness action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "run" }));
    await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("false"));
    expect(screen.getByTestId("error").textContent).toBe("directory service unavailable");
  });

  it("recovers when remove fails", async () => {
    vi.mocked(removeRoot).mockRejectedValue(new Error("remove failed"));
    render(<Harness action="remove" />);

    fireEvent.click(screen.getByRole("button", { name: "run" }));
    await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("false"));
    expect(screen.getByTestId("error").textContent).toBe("remove failed");
  });
});
