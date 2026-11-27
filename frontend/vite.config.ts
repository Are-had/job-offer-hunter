import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev`: the pages on :5173, the API (uvicorn on :8600) behind the same address
const api = { target: "http://127.0.0.1:8600", changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api, "/fonts": api, "/brand": api } },
  // '.v2': new names for every file, so a browser that kept the old script (served as text/plain on some Windows
  // computers, 28 Nov 2026) downloads it again instead of using its cached copy
  build: {
    outDir: "dist", emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: "assets/[name]-[hash].v2.js", chunkFileNames: "assets/[name]-[hash].v2.js",
                               assetFileNames: "assets/[name]-[hash].v2[extname]" } },
  },
});
