import { useMutation } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { AccountUpdateRequest, Account, AuthResponse, LoginRequest, SignupRequest } from "@/api/types";

export function useSignup() {
  return useMutation({
    mutationFn: (body: SignupRequest) => api.post<AuthResponse>("/api/auth/signup", body),
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: (body: LoginRequest) => api.post<AuthResponse>("/api/auth/login", body),
  });
}

export function useLogoutRequest() {
  return useMutation({
    mutationFn: () => api.post<void>("/api/auth/logout"),
  });
}

export function useUpdateAccount() {
  return useMutation({
    mutationFn: (body: AccountUpdateRequest) => api.patch<Account>("/api/auth/me", body),
  });
}
