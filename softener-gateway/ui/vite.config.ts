import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backendTarget = process.env.VITE_BACKEND_TARGET ?? "http://127.0.0.1:8080";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    fs: {
      allow: [".."],
    },
    proxy: {
      "/control": backendTarget,
      "/device": backendTarget,
      "/health": backendTarget,
      "/openapi.json": backendTarget,
      "/settings": backendTarget,
      "/state": backendTarget,
    },
  },
});
