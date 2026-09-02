import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FC } from "react";

const { mockApi } = vi.hoisted(() => ({ mockApi: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../../api", () => ({ api: mockApi }));

import { makeApi } from "../../test/mockApi";
import type { PanelProps } from "../types";
import { AssumptionsPanel } from "../assumptions";
import { ChangeSafetyPanel } from "../change-safety";
import { CharacterizationPanel } from "../characterization";
import { FailuresPanel } from "../failures";
import { HotspotsPanel } from "../hotspots";
import { IncidentMemoryPanel } from "../incident-memory";
import { LegacyDnaPanel } from "../legacy-dna";
import { ModernizationPanel } from "../modernization";
import { PatchVerificationPanel } from "../patch-verification";
import { RootCauseAnalysisPanel } from "../root-cause";
import { SelfHealingPanel } from "../self-healing";
import { TechnicalDebtPanel } from "../technical-debt";
import { TestIntelligencePanel } from "../test-intelligence";

beforeEach(() => Object.assign(mockApi, makeApi()));

const P: PanelProps = { runId: "run-1", snapshotId: "snap-1", repoId: "repo-1" };

interface Case {
  name: string;
  Comp: FC<PanelProps>;
  method: string;
  title: RegExp;
  cell: RegExp;
  alwaysPresent: boolean;
}

const cases: Case[] = [
  { name: "Hotspots", Comp: HotspotsPanel, method: "getHotspots", title: /hotspots/i, cell: /pricing_engine/, alwaysPresent: true },
  { name: "Legacy DNA", Comp: LegacyDnaPanel, method: "getLegacyDna", title: /legacy dna/i, cell: /pricing_engine/, alwaysPresent: true },
  { name: "Change Safety", Comp: ChangeSafetyPanel, method: "getChangeSafety", title: /change safety/i, cell: /RISKY/, alwaysPresent: true },
  { name: "Technical Debt", Comp: TechnicalDebtPanel, method: "getTechnicalDebt", title: /technical debt/i, cell: /long_function/, alwaysPresent: true },
  { name: "Assumptions", Comp: AssumptionsPanel, method: "getAssumptions", title: /hidden assumptions/i, cell: /positive quantity/, alwaysPresent: true },
  { name: "Test Intelligence", Comp: TestIntelligencePanel, method: "getTestGaps", title: /test intelligence/i, cell: /pricing_engine/, alwaysPresent: false },
  { name: "Failures", Comp: FailuresPanel, method: "getFailures", title: /failures/i, cell: /ZeroDivisionError/, alwaysPresent: false },
  { name: "Root Cause", Comp: RootCauseAnalysisPanel, method: "getInvestigations", title: /root cause/i, cell: /zero guard/, alwaysPresent: false },
  { name: "Self-Healing", Comp: SelfHealingPanel, method: "getPatches", title: /self-healing/i, cell: /GUARD_CLAUSE/, alwaysPresent: false },
  { name: "Patch Verification", Comp: PatchVerificationPanel, method: "getVerifications", title: /patch verification/i, cell: /VERIFIED/, alwaysPresent: false },
  { name: "Incident Memory", Comp: IncidentMemoryPanel, method: "getIncidents", title: /incident memory/i, cell: /zero guard/, alwaysPresent: false },
  { name: "Modernization", Comp: ModernizationPanel, method: "getModernization", title: /modernization/i, cell: /ADD_TESTS/, alwaysPresent: false },
  { name: "Characterization", Comp: CharacterizationPanel, method: "getCharacterization", title: /characterization/i, cell: /deadbeef/, alwaysPresent: false },
];

describe.each(cases)("$name panel", ({ Comp, method, title, cell, alwaysPresent }) => {
  it("renders rows from the API", async () => {
    render(<Comp {...P} />);
    expect(await screen.findByText(cell)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("handles an empty result", async () => {
    mockApi[method] = vi.fn().mockResolvedValue([]);
    const { container } = render(<Comp {...P} />);
    if (alwaysPresent) {
      expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
      expect(screen.queryByText(cell)).not.toBeInTheDocument();
    } else {
      await waitFor(() => expect(container).toBeEmptyDOMElement());
    }
  });

  it("does not throw when the API rejects", async () => {
    mockApi[method] = vi.fn().mockRejectedValue(new Error("NOT_FOUND: nope"));
    const { container } = render(<Comp {...P} />);
    if (alwaysPresent) {
      expect(await screen.findByRole("alert")).toHaveTextContent(/NOT_FOUND/);
    } else {
      await waitFor(() => expect(container).toBeEmptyDOMElement());
    }
  });
});
