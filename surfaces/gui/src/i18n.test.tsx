import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider, useI18n } from "./i18n";

function LanguageProbe() {
  const { language, setLanguage, t, tr } = useI18n();
  return (
    <div>
      <span>{language}</span>
      <strong>{t("nav.runs")}</strong>
      <span>{t("app.starting")}</span>
      <span>{tr("Welcome to Smallink")}</span>
      <button onClick={() => setLanguage("zh-CN")}>中文</button>
      <button onClick={() => setLanguage("en")}>English</button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("LanguageProvider", () => {
  it("switches the interface immediately and persists the Mac preference", () => {
    localStorage.setItem("link:language:v1", "en");
    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );

    expect(screen.getByText("Runs")).toBeTruthy();
    expect(screen.getByText("Starting Smallink…")).toBeTruthy();
    expect(screen.getByText("Welcome to Smallink")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByText("运行中心")).toBeTruthy();
    expect(screen.getByText("正在启动 Smallink…")).toBeTruthy();
    expect(screen.getByText("欢迎使用 Smallink")).toBeTruthy();
    expect(localStorage.getItem("link:language:v1")).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");

    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByText("Runs")).toBeTruthy();
    expect(localStorage.getItem("link:language:v1")).toBe("en");
  });
});
