import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react")) {
            return "react";
          }
          if (id.includes("node_modules/lucide-react")) {
            return "icons";
          }
          if (id.includes("node_modules")) {
            return "vendor";
          }
          return undefined;
        }
      }
    }
  },
  server: {
    port: 5174,
    allowedHosts: ["ai-control.home.local"],
    proxy: {
      "/api": "http://127.0.0.1:8010"
    }
  },
  preview: {
    allowedHosts: ["ai-control.home.local"]
  }
});
