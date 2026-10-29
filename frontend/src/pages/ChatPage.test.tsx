import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatPage } from "./ChatPage";

const mutate = vi.fn();
vi.mock("@/hooks/useAgent", () => ({
  useAskAgent: () => ({ mutate, isPending: false }),
}));

describe("ChatPage", () => {
  it("shows example question chips before any message is sent", () => {
    render(<ChatPage />);
    expect(screen.getByText("Who should I keep this year?")).toBeInTheDocument();
  });

  it("sends a question and renders the answer behind a reasoning toggle", () => {
    mutate.mockImplementation((_body, { onSuccess }) => {
      onSuccess({
        answer: "Keep Bijan.",
        steps: [{ tool_name: "get_keeper_candidates", arguments: {}, output_preview: "{}", error: false }],
        usage: { input_tokens: 1, cached_tokens: 0, output_tokens: 1 },
      });
    });

    render(<ChatPage />);
    fireEvent.change(screen.getByPlaceholderText(/ask about/i), { target: { value: "who should I keep?" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getByText("Keep Bijan.")).toBeInTheDocument();
    expect(screen.queryByText(/get_keeper_candidates/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/show reasoning/i));
    expect(screen.getByText(/get_keeper_candidates/)).toBeInTheDocument();
  });
});
