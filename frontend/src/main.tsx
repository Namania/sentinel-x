import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <p className="p-4 text-sm font-bold tracking-[0.18em]">SENTINEL-X</p>
  </StrictMode>,
);
