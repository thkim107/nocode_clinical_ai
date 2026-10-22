import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 서브패스 배포용 base. 빌드 시 BASE_PATH=/apps/research-agent 처럼 주면 asset/API 경로가 그 아래로 잡힌다.
// 미지정이면 "/" (docker-compose / 로컬 개발).
const base = (process.env.BASE_PATH || "/").replace(/\/?$/, "/");

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
