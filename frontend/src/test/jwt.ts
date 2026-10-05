function base64url(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** An unsigned JWT-shaped token: the front only ever reads the payload. */
export function makeJwt(claims: Record<string, unknown>): string {
  return `${base64url({ alg: "HS256", typ: "JWT" })}.${base64url(claims)}.signature`;
}

export function accessTokenExpiringIn(seconds: number): string {
  return makeJwt({ sub: "user", type: "access", exp: Math.floor(Date.now() / 1000) + seconds });
}
