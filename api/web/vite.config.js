import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into dist/ and served by FastAPI under /static (see api/Dockerfile).
// `npm run dev` proxies the API to a backend on :8000.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  server: { proxy: { "/api": "http://localhost:8000" } },
});
