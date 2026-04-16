import React from "react";
import ReactDOM from "react-dom/client";
import "@/app/globals.css";

function App() {
  return (
    <div className="flex items-center justify-center min-h-screen text-xl">
      SDPM Desktop — loading...
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
