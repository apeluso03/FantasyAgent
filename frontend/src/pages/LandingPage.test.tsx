import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LandingPage } from "./LandingPage";

const setSession = vi.fn();
const loginMutate = vi.fn();
const signupMutate = vi.fn();

vi.mock("@/state/AuthContext", () => ({
  useAuth: () => ({ setSession, account: null, isLoading: false, updateAccount: vi.fn(), logout: vi.fn() }),
}));

vi.mock("@/hooks/useAuthApi", () => ({
  useLogin: () => ({ mutate: loginMutate, isPending: false, error: null }),
  useSignup: () => ({ mutate: signupMutate, isPending: false, error: null }),
}));

function submitButton(): HTMLElement {
  return within(document.querySelector("form")!).getByRole("button", { name: /sign in|create account/i });
}

describe("LandingPage", () => {
  it("defaults to the sign-in form", () => {
    render(<LandingPage />);
    expect(submitButton()).toHaveTextContent("Sign in");
    expect(screen.queryByText(/name \(optional\)/i)).not.toBeInTheDocument();
  });

  it("switches to the create-account form and shows the display name field", () => {
    render(<LandingPage />);
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText(/name \(optional\)/i)).toBeInTheDocument();
    expect(submitButton()).toHaveTextContent("Create account");
  });

  it("submits sign-in credentials and hands the session to AuthContext on success", () => {
    loginMutate.mockImplementation((_body, { onSuccess }) => {
      onSuccess({ token: "tok", account: { id: 1, email: "a@b.com", display_name: null, default_league_id: null, default_owner_user_id: null } });
    });

    render(<LandingPage />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correcthorse" } });
    fireEvent.click(submitButton());

    expect(loginMutate).toHaveBeenCalledWith(
      { email: "a@b.com", password: "correcthorse" },
      expect.anything(),
    );
    expect(setSession).toHaveBeenCalledWith("tok", expect.objectContaining({ email: "a@b.com" }));
  });
});
