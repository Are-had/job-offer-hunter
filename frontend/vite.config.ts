import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev`: the pages on :5173, the API (uvicorn on :8600) behind the same address
const api = { target: "http://127.0.0.1:8600", changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api, "/fonts": api, "/brand": api } },
  build: { outDir: "dist", emptyOutDir: true },
});
