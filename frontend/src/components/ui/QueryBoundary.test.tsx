import type { UseQueryResult } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";

import { QueryBoundary } from "./QueryBoundary";

function fakeQuery<T>(overrides: Partial<UseQueryResult<T, Error>>): UseQueryResult<T, Error> {
  return {
    isPending: false,
    isError: false,
    data: undefined,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as UseQueryResult<T, Error>;
}

describe("QueryBoundary", () => {
  it("renders the loading node while pending", () => {
    render(
      <QueryBoundary query={fakeQuery({ isPending: true })} loading={<p>Loading...</p>}>
        {() => <p>data</p>}
      </QueryBoundary>,
    );
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders an empty state (with a link to Settings) for a 409 error", () => {
    render(
      <MemoryRouter>
        <QueryBoundary
          query={fakeQuery({ isError: true, error: new ApiError(409, "No data yet. Run a sync first.") })}
          loading={null}
        >
          {() => <p>data</p>}
        </QueryBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText("No data yet. Run a sync first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument();
  });

  it("renders a retryable error state for any other error", () => {
    const refetch = vi.fn();
    render(
      <QueryBoundary query={fakeQuery({ isError: true, error: new Error("boom"), refetch })} loading={null}>
        {() => <p>data</p>}
      </QueryBoundary>,
    );
    expect(screen.getByText("boom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders children with the loaded data on success", () => {
    render(
      <QueryBoundary query={fakeQuery({ data: "hello" })} loading={null}>
        {(data) => <p>{data}</p>}
      </QueryBoundary>,
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
});
