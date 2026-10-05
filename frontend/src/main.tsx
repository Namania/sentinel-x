import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import "./index.css";
import { createAppRouter } from "./app/router";
import { AuthProvider } from "./features/auth/auth-provider";
import { ThemeProvider } from "./features/theme/theme-provider";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <RouterProvider router={createAppRouter()} />
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
