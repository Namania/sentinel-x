import { createContext } from "react";

export type Theme = "light" | "dark" | "system";

export const THEMES: readonly Theme[] = ["light", "dark", "system"];
export const THEME_STORAGE_KEY = "sentinel-x-theme";
export const DEFAULT_THEME: Theme = "dark";

export type ThemeContextValue = { theme: Theme; setTheme: (theme: Theme) => void };

export const ThemeContext = createContext<ThemeContextValue | null>(null);
