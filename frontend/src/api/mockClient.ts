/**
 * Requests inside a mock draft authenticate with a per-draft participant
 * token (X-Mock-Token), not the app's account session -- invited friends
 * don't need an account. Kept apart from api/client.ts on purpose: a 401
 * here means "not in this draft", and must never trigger the app-wide
 * sign-out that client.ts does on a 401.
 */
import { ApiError } from "./client";
import type { DraftCredentials, MockAction, MockState, PoolPlayer } from "./mockTypes";

const BASE_URL = import.meta.env.VITE_API_URL ?? "";
const KEY = (draftId: string) => `mock-draft-token:${draftId}`;

export function saveCredentials(creds: DraftCredentials): void {
  try {
    localStorage.setItem(KEY(creds.draft_id), JSON.stringify(creds));
  } catch {
    // Private mode etc. -- the session still works until the tab closes.
  }
}

export function loadCredentials(draftId: string): DraftCredentials | null {
  try {
    const raw = localStorage.getItem(KEY(draftId));
    return raw ? (JSON.parse(raw) as DraftCredentials) : null;
  } catch {
    return null;
  }
}

export function clearCredentials(draftId: string): void {
  try {
    localStorage.removeItem(KEY(draftId));
  } catch {
    // ignore
  }
}

async function mockRequest<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Mock-Token": token } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const mockApi = {
  inviteInfo: (code: string) => mockRequest<import("./mockTypes").DraftSummary>(`/api/mock/invite/${code}`, null),
  join: (code: string, name: string) =>
    mockRequest<DraftCredentials>(`/api/mock/invite/${code}/join`, null, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  state: (draftId: string, token: string) => mockRequest<MockState>(`/api/mock/drafts/${draftId}`, token),
  pool: (draftId: string, token: string) => mockRequest<PoolPlayer[]>(`/api/mock/drafts/${draftId}/pool`, token),
  act: (draftId: string, token: string, action: MockAction) =>
    mockRequest<MockState>(`/api/mock/drafts/${draftId}/actions`, token, {
      method: "POST",
      body: JSON.stringify(action),
    }),
  remove: (draftId: string, token: string) =>
    mockRequest<void>(`/api/mock/drafts/${draftId}`, token, { method: "DELETE" }),
  async exportCsv(draftId: string, token: string): Promise<Blob> {
    const response = await fetch(`${BASE_URL}/api/mock/drafts/${draftId}/export.csv`, {
      headers: { "X-Mock-Token": token },
    });
    if (!response.ok) throw new ApiError(response.status, "Export failed");
    return response.blob();
  },
};

export function socketUrl(draftId: string, token: string): string {
  const base = BASE_URL || window.location.origin;
  const url = new URL(`/api/mock/drafts/${draftId}/ws`, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", token);
  return url.toString();
}
