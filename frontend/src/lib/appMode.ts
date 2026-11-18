import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

/**
 * Whether this deployment hosts only the mock draft simulator. Decided by the
 * *server's* APP_MODE (read from /api/health at load), so one runtime
 * variable controls both halves -- no build-time flag that can silently miss
 * a build. VITE_APP_MODE=mock still forces it on for local builds.
 */
const BUILD_MOCK = import.meta.env.VITE_APP_MODE === "mock";
const BASE_URL = import.meta.env.VITE_API_URL ?? "";

const AppModeContext = createContext<boolean>(BUILD_MOCK);

export function AppModeProvider({ children }: { children: ReactNode }) {
  const [mockOnly, setMockOnly] = useState<boolean | null>(BUILD_MOCK ? true : null);

  useEffect(() => {
    if (BUILD_MOCK) return;
    fetch(`${BASE_URL}/api/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { mode?: string } | null) => setMockOnly(body?.mode === "mock"))
      // Can't reach the server: fail closed to the smaller site.
      .catch(() => setMockOnly(true));
  }, []);

  // Render nothing until the mode is known, so the full app's pages never flash on a mock-only site.
  if (mockOnly === null) return createElement("div", { className: "min-h-screen bg-neutral-50 dark:bg-neutral-950" });
  return createElement(AppModeContext.Provider, { value: mockOnly }, children);
}

export function useMockOnly(): boolean {
  return useContext(AppModeContext);
}
