import React from "react";
import ReactDOM from "react-dom/client";
import "@desktop/app.css";
import "@/app/globals.css";
import { ServiceProvider } from "@desktop/lib/serviceProvider";
import { Toaster } from "sonner";

/**
 * Desktop app entry point.
 * Wraps shared UI components with ServiceProvider (local services)
 * instead of AuthProvider (Cognito).
 */

// Lazy-load the decks page — it's the main UI
const DecksPage = React.lazy(() => import("@/app/(authenticated)/decks/page"));

function App() {
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
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
