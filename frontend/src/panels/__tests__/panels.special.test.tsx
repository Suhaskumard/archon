import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import * as fx from "../../test/fixtures";
import type { PanelProps } from "../types";
import { SourceIntelPanel } from "../source";
import { GitEvolutionPanel } from "../git-evolution";
import { UnderstandingPanel } from "../understanding";
import { ArchaeologyPanel } from "../archaeology";
import { ArchitecturePanel } from "../architecture";
import { ChangeImpactPanel } from "../change-impact";
import { RepositoryComparisonPanel } from "../repository-comparison";

beforeEach(() => Object.assign(mockApi, makeApi()));
const P: PanelProps = { runId: "run-1", snapshotId: "snap-1", repoId: "repo-1" };

describe("SourceIntelPanel", () => {
  it("shows summary counts and lazily loads components", async () => {
    render(<SourceIntelPanel {...P} />);
    expect(await screen.findByText(/test modules/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /load components/i }));
    expect(await screen.findByText(/acme\.pricing_engine/)).toBeInTheDocument();
    expect(mockApi.listComponents).toHaveBeenCalled();
  });

  it("renders empty state when source was not analyzed", async () => {
    mockApi.getRunSource = vi.fn().mockResolvedValue(fx.sourceSummary({ analyzed: false }));
    render(<SourceIntelPanel {...P} />);
    expect(await screen.findByText(/did not run/i)).toBeInTheDocument();
  });
});

describe("GitEvolutionPanel", () => {
  it("renders the sparkline and churn table", async () => {
    render(<GitEvolutionPanel {...P} />);
    expect(await screen.findByRole("img", { name: /commits per month/i })).toBeInTheDocument();
    expect(screen.getByText(/acme\.pricing_engine/)).toBeInTheDocument();
  });
});

describe("UnderstandingPanel", () => {
  it("renders the dimension chart", async () => {
    render(<UnderstandingPanel {...P} />);
    expect(await screen.findByText(/overall score/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /understanding score/i })).toBeInTheDocument();
  });
});

describe("ArchaeologyPanel", () => {
  it("shows the selected behavior and switches on select", async () => {
    mockApi.getBehavior = vi.fn().mockResolvedValue([
      fx.behavior(),
      fx.behavior({ id: "b2", component_qn: "acme.tax_rules", purpose: "tax lookup" }),
    ]);
    render(<ArchaeologyPanel {...P} />);
    expect(await screen.findByText(/compute a line price/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/component/i), "acme.tax_rules");
    expect(await screen.findByText(/tax lookup/i)).toBeInTheDocument();
  });
});

describe("ArchitecturePanel", () => {
  it("renders the module graph and table", async () => {
    render(<ArchitecturePanel {...P} />);
    expect(await screen.findByRole("img", { name: /module dependency graph/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset view/i })).toBeInTheDocument();
  });

  it("is empty when architecture was not reconstructed", async () => {
    mockApi.getArchitecture = vi.fn().mockResolvedValue(fx.architecture({ reconstructed: false }));
    render(<ArchitecturePanel {...P} />);
    expect(await screen.findByText(/not reconstructed/i)).toBeInTheDocument();
  });
});

describe("ChangeImpactPanel", () => {
  it("computes impact for the selected component", async () => {
    render(<ChangeImpactPanel {...P} />);
    const btn = await screen.findByRole("button", { name: /compute impact/i });
    await userEvent.click(btn);
    expect(await screen.findByText(/what could break/i)).toBeInTheDocument();
    expect(mockApi.postChangeImpact).toHaveBeenCalledWith("run-1", expect.any(String));
  });
});

describe("RepositoryComparisonPanel", () => {
  it("renders nothing without a comparable baseline run", async () => {
    mockApi.listRuns = vi.fn().mockResolvedValue([fx.run({ id: "run-1" })]); // only the current run
    const { container } = render(<RepositoryComparisonPanel {...P} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("runs a comparison against the chosen baseline", async () => {
    mockApi.listRuns = vi.fn().mockResolvedValue([
      fx.run({ id: "run-1" }),
      fx.run({ id: "run-0", last_completed_stage: "MODERNIZING" }),
    ]);
    render(<RepositoryComparisonPanel {...P} />);
    const btn = await screen.findByRole("button", { name: /compare with this run/i });
    await userEvent.click(btn);
    expect(await screen.findByText(/legacy risk movement/i)).toBeInTheDocument();
    expect(mockApi.createComparison).toHaveBeenCalledWith("repo-1", "run-0", "run-1");
  });
});
