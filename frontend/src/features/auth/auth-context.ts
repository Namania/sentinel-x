import { createContext } from "react";
import type { User } from "./auth-api";

export type AuthStatus = "restoring" | "anonymous" | "authenticated";

export type AuthContextValue = {
  status: AuthStatus;
  user: User | null;
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** apiFetch with the current access token; refreshes once on 401, logs out if that fails. */
  authFetch: <T>(path: string, init?: RequestInit) => Promise<T>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
