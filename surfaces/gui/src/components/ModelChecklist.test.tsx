import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addModel,
  getSettings,
  removeModel,
  setDefaultModel,
  setModelPurposes,
} from "../api";
import { LanguageProvider } from "../i18n";
import { ModelChecklist } from "./ModelChecklist";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    addModel: vi.fn(),
    getSettings: vi.fn(),
    removeModel: vi.fn(),
    setDefaultModel: vi.fn(),
    setModelPurposes: vi.fn(),
  };
});

const settings = {
  provider: "openai",
  model: "gpt-main",
  models: ["gpt-main", "gpt-memory"],
  model_labels: {},
  model_purposes: { "gpt-memory": ["memory"] },
  purposes: ["chat", "memory", "title"],
  has_key: true,
  model_ready: true,
  source: "store" as const,
  onboarded: true,
  experimental_connectors: false,
  surfaces: { link: true, chat: false, code: false },
  scratch_base: "~/Smallink",
  secrets_path: "/tmp/secrets.json",
};

function renderChecklist() {
  render(
    <LanguageProvider>
      <ModelChecklist
        provider="openai"
        knownProviders={["openai"]}
        suggested={["gpt-main", "gpt-memory"]}
        curated={settings.models}
        defaultModel={settings.model}
        purposes={settings.purposes}
        modelPurposes={settings.model_purposes}
        onChanged={vi.fn()}
      />
    </LanguageProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModelChecklist interaction states", () => {
  it("only exposes the runtime-wired memory purpose", () => {
    renderChecklist();

    expect(screen.getAllByRole("button", { name: /For memory/ })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /For chat/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /For titles/ })).toBeNull();
  });

  it("rolls back an optimistic purpose update when saving fails", async () => {
    vi.mocked(setModelPurposes).mockResolvedValue({
      ...settings,
      ok: false,
      error: "save failed",
    });
    renderChecklist();

    const memory = screen.getByRole("button", { name: "gpt-memory · For memory" });
    expect(memory.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(memory);

    expect(await screen.findByText("save failed")).toBeTruthy();
    expect(screen.getByRole("button", { name: "gpt-memory · For memory" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("clears a model purpose before removing the model", async () => {
    vi.mocked(removeModel).mockResolvedValue({ ...settings, ok: true, models: ["gpt-main"] });
    vi.mocked(setModelPurposes).mockResolvedValue({
      ...settings,
      ok: true,
      model_purposes: {},
    });
    vi.mocked(getSettings).mockResolvedValue(settings);
    vi.mocked(addModel).mockResolvedValue({ ...settings, ok: true });
    vi.mocked(setDefaultModel).mockResolvedValue({ ok: true, model: "gpt-main" });
    renderChecklist();

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);

    await waitFor(() => expect(setModelPurposes).toHaveBeenCalledWith("gpt-memory", []));
    expect(removeModel).toHaveBeenCalledWith("gpt-memory");
  });
});
