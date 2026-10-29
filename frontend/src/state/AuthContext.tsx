import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api, getAuthToken, setAuthToken, setUnauthorizedHandler } from "@/api/client";
import type { Account } from "@/api/types";

interface AuthContextValue {
  account: Account | null;
  /** True only while validating a stored token on first load -- lets App
   * avoid flashing the landing page for an already-signed-in visitor. */
  isLoading: boolean;
  setSession: (token: string, account: Account) => void;
  updateAccount: (account: Account) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Any 401 from an authenticated route (expired/revoked session) drops
    // the user back to the landing page, not just the one request that hit it.
    setUnauthorizedHandler(() => {
      setAuthToken(null);
      setAccount(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      setIsLoading(false);
      return;
    }
    api
      .get<Account>("/api/auth/me")
      .then(setAccount)
      .catch(() => setAuthToken(null))
      .finally(() => setIsLoading(false));
  }, []);

  const value: AuthContextValue = {
    account,
    isLoading,
    setSession: (token, acc) => {
      setAuthToken(token);
      setAccount(acc);
    },
    updateAccount: setAccount,
    logout: () => {
      setAuthToken(null);
      setAccount(null);
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
