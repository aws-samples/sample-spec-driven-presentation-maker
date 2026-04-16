import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Service overrides — local implementations replace AWS ones
      "@/services/deckService": path.resolve(__dirname, "src/services/localDeckService.ts"),
      "@/services/agentCoreService": path.resolve(__dirname, "src/services/acpAgentService.ts"),
      "@/services/uploadService": path.resolve(__dirname, "src/services/localUploadService.ts"),
      // Auth overrides — shims replace Cognito OIDC
      "react-oidc-context": path.resolve(__dirname, "src/lib/authShim.ts"),
      "@/hooks/useAuth": path.resolve(__dirname, "src/lib/useAuthShim.ts"),
      "@/lib/auth": path.resolve(__dirname, "src/lib/useAuthShim.ts"),
      // Desktop-specific modules
      "@desktop": path.resolve(__dirname, "src"),
      // Shared web-ui components (must be last — less specific)
      "@": path.resolve(__dirname, "../web-ui/src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
  },
});
