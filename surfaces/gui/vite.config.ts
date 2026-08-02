import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// `base: "./"` makes built asset URLs relative, so the bundle loads from the `tauri://`
// origin in the desktop shell (absolute `/assets` 404s there); a server-hosted build is
// unaffected. Dev runs on a fixed port (41737) with strictPort so the Tauri webview always
// loads the vite instance Tauri itself spawns (a drifting port would make the window load a
// stale/other server). `tauri.conf.json` devUrl must match this.
export default defineConfig(({ command }) => {
  let devToken = "";
  if (command === "serve") {
    const state =
      process.env.LINK_STATE_DIR ||
      (process.platform === "win32"
        ? path.join(process.env.APPDATA || os.homedir(), "link")
        : path.join(os.homedir(), ".config", "link"));
    try {
      devToken = fs.readFileSync(path.join(state, "sidecar-42871.token"), "utf8").trim();
    } catch {
      // The Tauri dev shell injects its in-memory token at runtime. Plain browser dev
      // shows the normal startup retry until the standalone server/token file exists.
    }
  }
  return {
    base: "./",
    plugins: [react()],
    server: { port: 41737, strictPort: true },
    define: { __LINK_DEV_TOKEN__: JSON.stringify(devToken) },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (!id.includes("node_modules")) return undefined;
            if (
              id.includes("react-markdown") ||
              id.includes("remark-") ||
              id.includes("/unified/") ||
              id.includes("/micromark") ||
              id.includes("/mdast") ||
              id.includes("/hast")
            ) {
              return "markdown";
            }
            if (id.includes("simple-icons")) return "connector-icons";
            if (
              id.includes("/react/") ||
              id.includes("/react-dom/") ||
              id.includes("/scheduler/")
            ) {
              return "react";
            }
            return undefined;
          },
        },
      },
    },
    // Tauri CLI looks for these; harmless for the browser build.
    clearScreen: false,
    envPrefix: ["VITE_", "TAURI_"],
  };
});
