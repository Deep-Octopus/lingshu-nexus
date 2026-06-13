import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget =
    env.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  console.info(`[vite] /api/v1 proxy target: ${apiProxyTarget}`);

  return {
    plugins: [vue()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api/v1": {
          target: apiProxyTarget,
          changeOrigin: true,
          configure(proxy) {
            proxy.on("proxyReq", (_proxyReq, request) => {
              console.info(`[vite] proxy request ${request.method} ${request.url}`);
            });
            proxy.on("proxyRes", (proxyResponse, request) => {
              console.info(
                `[vite] proxy response ${proxyResponse.statusCode} ${request.method} ${request.url}`,
              );
            });
            proxy.on("error", (error, request) => {
              console.error(`[vite] proxy error ${request.method} ${request.url}: ${error.message}`);
            });
          }
        }
      }
    }
  };
});
