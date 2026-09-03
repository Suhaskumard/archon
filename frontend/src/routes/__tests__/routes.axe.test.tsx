import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import * as fx from "../../test/fixtures";
import { App } from "../../App";

beforeEach(() => {
  Object.assign(mockApi, makeApi());
  mockApi.listRuns = vi.fn().mockResolvedValue([
    fx.run({ id: "run-1" }),
    fx.run({ id: "run-0", last_completed_stage: "MODERNIZING" }),
  ]);
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe.each([
  ["/", /repositories/i, () => screen.findByText("acme/widgets")],
  ["/runs/run-1", /run run-1/i, () => screen.findByText("COMPLETED")],
  ["/runs/run-1/compare", /compare run run-1/i, () =>
    screen.findByRole("button", { name: /compare with this run/i })],
] as const)("route %s", (path, heading, settle) => {
  it("has no axe violations", async () => {
    const { container } = renderAt(path);
    await screen.findByRole("heading", { name: heading });
    await settle();
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

it("run view with a push-trigger badge has no axe violations", async () => {
  mockApi.getRun = vi.fn().mockResolvedValue(fx.runTriggeredByPush());
  const { container } = renderAt("/runs/run-1");
  await screen.findByText(/triggered by push/i);
  expect(await axe(container)).toHaveNoViolations();
});
