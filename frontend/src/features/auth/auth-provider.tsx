import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import * as authApi from "./auth-api";
import { AuthContext, type AuthContextValue, type AuthStatus } from "./auth-context";
import { jwtExpiresAt } from "./jwt";
import { readRefreshToken, writeRefreshToken } from "./token-storage";

/** Refresh the access token this long before it expires. */
export const REFRESH_LEAD_MS = 60_000;

type Session = { accessToken: string; user: authApi.User };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    readRefreshToken() ? "restoring" : "anonymous",
  );
  const [session, setSession] = useState<Session | null>(null);
  // Mirrors session.accessToken so authFetch never sees a stale closure.
  const accessTokenRef = useRef<string | null>(null);
  const userRef = useRef<authApi.User | null>(null);
  const restoredRef = useRef(false);

  const clearSession = useCallback(() => {
    writeRefreshToken(null);
    accessTokenRef.current = null;
    userRef.current = null;
    setSession(null);
    setStatus("anonymous");
  }, []);

  const adopt = useCallback((pair: authApi.TokenPair, user: authApi.User) => {
    writeRefreshToken(pair.refresh_token);
    accessTokenRef.current = pair.access_token;
    userRef.current = user;
    setSession({ accessToken: pair.access_token, user });
    setStatus("authenticated");
  }, []);

  /** Exchange the stored refresh token for a new pair. Resolves to the new access token or null. */
  const refreshSession = useCallback(async (): Promise<string | null> => {
    const stored = readRefreshToken();
    if (!stored) {
      clearSession();
      return null;
    }
    try {
      const pair = await authApi.refresh(stored);
      // Already signed in: the user is known, so skip the redundant /users/me round trip.
      const user = userRef.current ?? (await authApi.me(pair.access_token));
      adopt(pair, user);
      return pair.access_token;
    } catch {
      clearSession();
      return null;
    }
  }, [adopt, clearSession]);

  // 1. Restore the session once on startup.
  useEffect(() => {
    if (restoredRef.current || !readRefreshToken()) return;
    restoredRef.current = true;
    void refreshSession();
  }, [refreshSession]);

  // 3. Refresh proactively before the access token expires.
  useEffect(() => {
    if (!session) return;
    const expiresAt = jwtExpiresAt(session.accessToken);
    if (expiresAt === null) return;
    const delay = Math.max(expiresAt - REFRESH_LEAD_MS - Date.now(), 0);
    const timer = setTimeout(() => void refreshSession(), delay);
    return () => clearTimeout(timer);
  }, [session, refreshSession]);

  // 2. Login.
  const login = useCallback(
    async (email: string, password: string) => {
      const pair = await authApi.login(email, password);
      const user = await authApi.me(pair.access_token);
      adopt(pair, user);
    },
    [adopt],
  );

  // 5. Logout.
  const logout = useCallback(() => clearSession(), [clearSession]);

  // 4. Authenticated fetch with one refresh-and-retry on 401.
  const authFetch = useCallback(
    async <T,>(path: string, init?: RequestInit): Promise<T> => {
      try {
        return await apiFetch<T>(path, init, accessTokenRef.current);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        const fresh = await refreshSession();
        if (fresh === null) throw error;
        return apiFetch<T>(path, init, fresh);
      }
    },
    [refreshSession],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user: session?.user ?? null,
      accessToken: session?.accessToken ?? null,
      login,
      logout,
      authFetch,
    }),
    [status, session, login, logout, authFetch],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
