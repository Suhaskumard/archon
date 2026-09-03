import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import { OpsRoute } from "../OpsRoute";

beforeEach(() => Object.assign(mockApi, makeApi()));

function renderOps() {
  return render(
    <MemoryRouter initialEntries={["/ops"]}>
      <Routes>
        <Route path="/ops" element={<OpsRoute />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OpsRoute", () => {
  it("lists operational run rows with duration and links to /metrics", async () => {
    renderOps();
    expect(await screen.findByRole("heading", { name: /operations/i })).toBeInTheDocument();
    expect(await screen.findByText(/run-1/)).toBeInTheDocument();
    expect(screen.getByText("2m 0s")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "/metrics" })).toHaveAttribute("href", "/metrics");
  });

  it("re-queries when the state filter changes", async () => {
    renderOps();
    await screen.findByText(/run-1/);
    await userEvent.selectOptions(screen.getByLabelText(/run state filter/i), "FAILED");
    expect(mockApi.getAdminRuns).toHaveBeenLastCalledWith("FAILED");
  });

  it("has no axe violations", async () => {
    const { container } = renderOps();
    await screen.findByText(/run-1/);
    expect(await axe(container)).toHaveNoViolations();
  });
});
