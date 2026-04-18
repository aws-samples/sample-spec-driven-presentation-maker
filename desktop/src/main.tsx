import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import "@desktop/app.css";
import { ServiceProvider } from "@desktop/lib/serviceProvider";
import { Toaster, toast } from "sonner";

/**
 * Desktop app entry point.
 * Wraps shared UI components with ServiceProvider (local services)
 * instead of AuthProvider (Cognito).
 */

// Lazy-load the decks page — it's the main UI
const DecksPage = React.lazy(() => import("@/app/(authenticated)/decks/page"));

function App() {
  useEffect(() => {
    (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const { ask } = await import("@tauri-apps/plugin-dialog");
        const ok = await invoke<boolean>("check_libreoffice_cmd");
        if (ok) return;
        const install = await ask(
          "LibreOffice 25.8.6+ is required for PPTX/SVG preview generation.\n\nInstall now? (requires sudo password)",
          { title: "SDPM — Missing Dependency", kind: "warning", okLabel: "Install", cancelLabel: "Skip" }
        );
        if (!install) return;
        toast.info("Installing LibreOffice... Check terminal for sudo prompt.");
        const result = await invoke<string>("install_libreoffice");
        toast.success(result);
      } catch (e) {
        console.error("[libreoffice check]", e);
        toast.error(`LibreOffice install failed: ${e}`);
      }
    })();
  }, []);

  return (
    <ServiceProvider>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center min-h-screen text-xl">
            Loading...
          </div>
        }
      >
        <DecksPage />
      </React.Suspense>
      <Toaster />
    </ServiceProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <App />
);
