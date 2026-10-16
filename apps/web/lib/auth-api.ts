const BASE = "/api/backend/auth";

export interface AuthStatus {
  authRequired: boolean;
  authenticated: boolean;
}

export interface CandidateAuthResponse {
  success: boolean;
  token: string;
  userId: string;
  email: string;
  needsOnboarding: boolean;
}

export interface CurrentUser {
  userId: string;
  email: string;
  fullName: string;
  profileCompleteness: number;
  readyForAutopilot: boolean;
  missingRequired: string[];
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

export async function candidateSignUp(
  email: string,
  password: string,
  fullName?: string,
): Promise<CandidateAuthResponse> {
  const res = await fetch(`${BASE}/candidate/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, fullName }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Signup failed");
  }
  return res.json();
}

export async function candidateLogin(
  email: string,
  password: string,
): Promise<CandidateAuthResponse> {
  const res = await fetch(`${BASE}/candidate/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Invalid email or password");
  }
  return res.json();
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${BASE}/me`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/logout`, { method: "POST" });
}
