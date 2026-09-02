import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import * as fx from "../../test/fixtures";
import { RepositoriesRoute } from "../RepositoriesRoute";
import { RunRoute } from "../RunRoute";
import { CompareRoute } from "../CompareRoute";

beforeEach(() => Object.assign(mockApi, makeApi()));
afterEach(() => vi.useRealTimers());

function App({ path }: { path: string }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<RepositoriesRoute />} />
        <Route path="/runs/:id" element={<RunRoute />} />
        <Route path="/runs/:id/compare" element={<CompareRoute />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RepositoriesRoute", () => {
  it("lists repositories and adds one", async () => {
    render(<App path="/" />);
    expect(await screen.findByText("acme/widgets")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/repository url/i), "acme/new");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(mockApi.createRepository).toHaveBeenCalledWith("acme/new");
  });

  it("navigates to the run view when Analyze is clicked", async () => {
    mockApi.createRun = vi.fn().mockResolvedValue(fx.run({ id: "run-42", state: "QUEUED" }));
    render(<App path="/" />);
    await userEvent.click(await screen.findByRole("button", { name: "Analyze" }));
    expect(await screen.findByRole("heading", { name: /run run-42/i })).toBeInTheDocument();
  });
});

describe("RunRoute", () => {
  it("shows the completed run with its panels and evidence", async () => {
    render(<App path="/runs/run-1" />);
    expect(await screen.findByText("COMPLETED")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /legacy dna/i })).toBeInTheDocument();
    expect(screen.getByText(/evidence record\(s\)/i)).toBeInTheDocument();
  });

  it("stops polling once the run is terminal", async () => {
    vi.useFakeTimers();
    mockApi.getRun = vi.fn().mockResolvedValue(fx.run({ state: "COMPLETED" }));
    render(<App path="/runs/run-1" />);
    await vi.advanceTimersByTimeAsync(50);
    const calls = mockApi.getRun.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(mockApi.getRun.mock.calls.length).toBe(calls);
  });

  it("keeps polling while the run is running", async () => {
    vi.useFakeTimers();
    mockApi.getRun = vi.fn().mockResolvedValue(fx.run({ state: "RUNNING", progress_pct: 40 }));
    render(<App path="/runs/run-1" />);
    await vi.advanceTimersByTimeAsync(50);
    const calls = mockApi.getRun.mock.calls.length;
    await vi.advanceTimersByTimeAsync(2000);
    expect(mockApi.getRun.mock.calls.length).toBeGreaterThan(calls);
  });
});

describe("CompareRoute", () => {
  it("renders the comparison panel for a run with a snapshot", async () => {
    mockApi.listRuns = vi.fn().mockResolvedValue([
      fx.run({ id: "run-1" }),
      fx.run({ id: "run-0", last_completed_stage: "MODERNIZING" }),
    ]);
    render(<App path="/runs/run-1/compare" />);
    expect(await screen.findByRole("heading", { name: /compare run run-1/i })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /compare with this run/i })).toBeInTheDocument(),
    );
  });
});
