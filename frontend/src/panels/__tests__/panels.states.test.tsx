import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import * as fx from "../../test/fixtures";
import type { PanelProps } from "../types";
import { GitEvolutionPanel } from "../git-evolution";
import { UnderstandingPanel } from "../understanding";
import { LegacyDnaPanel } from "../legacy-dna";
import { ChangeImpactPanel } from "../change-impact";

beforeEach(() => Object.assign(mockApi, makeApi()));
const P: PanelProps = { runId: "run-1", snapshotId: "snap-1", repoId: "repo-1" };

it("GitEvolution shows an empty state with no analysed commits", async () => {
  mockApi.getEvolution = vi.fn().mockResolvedValue(
    fx.evolution({ analyzed_commits: 0, timeline: [], top_churn: [], top_co_change: [] }),
  );
  render(<GitEvolutionPanel {...P} />);
  expect(await screen.findByText(/no commit history/i)).toBeInTheDocument();
});

it("Understanding shows an empty state with no dimensions", async () => {
  mockApi.getUnderstanding = vi.fn().mockResolvedValue(fx.understanding({ dimensions: [] }));
  render(<UnderstandingPanel {...P} />);
  expect(await screen.findByText(/no understanding score/i)).toBeInTheDocument();
});

it("LegacyDna renders the proxy marker and null metric dashes", async () => {
  mockApi.getLegacyDna = vi.fn().mockResolvedValue([
    fx.legacyDna({
      coverage_is_proxy: true,
      coverage: 0.5,
      complexity: null,
      churn: null,
      coupling: null,
      debt_score: null,
    }),
  ]);
  render(<LegacyDnaPanel {...P} />);
  expect(await screen.findByText("0.50*")).toBeInTheDocument();
  expect(screen.getByText(/is a proxy/i)).toBeInTheDocument();
});

it("ChangeImpact surfaces a compute error", async () => {
  mockApi.postChangeImpact = vi.fn().mockRejectedValue(new Error("VALIDATION: bad component"));
  render(<ChangeImpactPanel {...P} />);
  await userEvent.click(await screen.findByRole("button", { name: /compute impact/i }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/VALIDATION/));
});
