const BASE = "/api/backend/auth";

export interface AuthStatus {
  authRequired: boolean;
  authenticated: boolean;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const res = await fetch(`${BASE}/status`, { cache: "no-store" });
  if (!res.ok) return { authRequired: false, authenticated: true };
  return res.json();
}

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Incorrect username or password");
  }
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/logout`, { method: "POST" });
}
