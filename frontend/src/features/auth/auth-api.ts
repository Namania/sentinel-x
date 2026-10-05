import { apiFetch } from "@/lib/api";

export type TokenPair = { access_token: string; refresh_token: string; token_type: string };
export type User = { id: string; email: string; created_at: string };

export function login(email: string, password: string): Promise<TokenPair> {
  return apiFetch<TokenPair>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function refresh(refreshToken: string): Promise<TokenPair> {
  return apiFetch<TokenPair>("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function me(accessToken: string): Promise<User> {
  return apiFetch<User>("/users/me", {}, accessToken);
}
