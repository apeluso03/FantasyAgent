/**
 * Small typed fetch wrapper (CLAUDE.md section 6.4). Base URL comes from
 * VITE_API_URL in a deployed build; left empty in dev so requests go through
 * Vite's /api proxy (see vite.config.ts) to the backend on :8000.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? "";
const ACCESS_CODE_STORAGE_KEY = "fantasy-agent-access-code";
const AUTH_TOKEN_STORAGE_KEY = "fantasy-agent-auth-token";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getAccessCode(): string {
  return localStorage.getItem(ACCESS_CODE_STORAGE_KEY) ?? "";
}

export function setAccessCode(code: string): void {
  if (code) localStorage.setItem(ACCESS_CODE_STORAGE_KEY, code);
  else localStorage.removeItem(ACCESS_CODE_STORAGE_KEY);
}

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function setAuthToken(token: string | null): void {
  if (token) localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

// Lets AuthProvider react to a session going stale (expired/revoked token)
// without every call site having to check for it -- any 401 from a route
// that isn't the auth routes themselves means "the backend doesn't
// recognize this session," so drop back to the landing page. A 403 (wrong
// demo access code, see backend/app/deps.py) is deliberately NOT treated as
// a sign-out: that's a separate, narrower gate on /api/agent and /api/sync.
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function toQueryString(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const accessCode = getAccessCode();
  const token = getAuthToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessCode ? { "X-Access-Code": accessCode } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body?.detail ?? detail;
    } catch {
      // Non-JSON error body -- keep the statusText fallback above.
    }
    if (response.status === 401 && !path.startsWith("/api/auth") && onUnauthorized) {
      onUnauthorized();
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>(`${path}${toQueryString(params)}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
};
