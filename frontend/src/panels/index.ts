// Ordered registry of run-view panels. RunRoute maps over this instead of
// hard-coding the JSX list. Each panel is self-guarding: it renders nothing when
// its resource is absent for the run's mode.

import type { FC } from "react";
import type { PanelProps } from "./types";

import { SourceIntelPanel } from "./source";
import { GitEvolutionPanel } from "./git-evolution";
import { ArchitecturePanel } from "./architecture";
import { ArchaeologyPanel } from "./archaeology";
import { AssumptionsPanel } from "./assumptions";
import { UnderstandingPanel } from "./understanding";
import { LegacyDnaPanel } from "./legacy-dna";
import { TechnicalDebtPanel } from "./technical-debt";
import { HotspotsPanel } from "./hotspots";
import { ChangeSafetyPanel } from "./change-safety";
import { ChangeImpactPanel } from "./change-impact";
import { TestExecutionPanel } from "./test-execution";
import { CharacterizationPanel } from "./characterization";
import { TestIntelligencePanel } from "./test-intelligence";
import { FailuresPanel } from "./failures";
import { RootCauseAnalysisPanel } from "./root-cause";
import { SelfHealingPanel } from "./self-healing";
import { PatchVerificationPanel } from "./patch-verification";
import { IncidentMemoryPanel } from "./incident-memory";
import { ModernizationPanel } from "./modernization";
import { RepositoryComparisonPanel } from "./repository-comparison";

export type { PanelProps } from "./types";

// `alwaysPresent`: the resource exists for every completed run (any mode), so the
// panel shows loading / empty / error states. The rest are populated only by a
// FULL run's post-EXECUTING stages and stay hidden when their endpoint 404s.
export interface PanelEntry {
  key: string;
  Comp: FC<PanelProps>;
  alwaysPresent: boolean;
}

export const RUN_PANELS: ReadonlyArray<PanelEntry> = [
  { key: "source", Comp: SourceIntelPanel, alwaysPresent: true },
  { key: "git-evolution", Comp: GitEvolutionPanel, alwaysPresent: true },
  { key: "architecture", Comp: ArchitecturePanel, alwaysPresent: true },
  { key: "archaeology", Comp: ArchaeologyPanel, alwaysPresent: true },
  { key: "assumptions", Comp: AssumptionsPanel, alwaysPresent: true },
  { key: "understanding", Comp: UnderstandingPanel, alwaysPresent: true },
  { key: "legacy-dna", Comp: LegacyDnaPanel, alwaysPresent: true },
  { key: "technical-debt", Comp: TechnicalDebtPanel, alwaysPresent: true },
  { key: "hotspots", Comp: HotspotsPanel, alwaysPresent: true },
  { key: "change-safety", Comp: ChangeSafetyPanel, alwaysPresent: true },
  { key: "change-impact", Comp: ChangeImpactPanel, alwaysPresent: true },
  { key: "test-execution", Comp: TestExecutionPanel, alwaysPresent: false },
  { key: "characterization", Comp: CharacterizationPanel, alwaysPresent: false },
  { key: "test-intelligence", Comp: TestIntelligencePanel, alwaysPresent: false },
  { key: "failures", Comp: FailuresPanel, alwaysPresent: false },
  { key: "root-cause", Comp: RootCauseAnalysisPanel, alwaysPresent: false },
  { key: "self-healing", Comp: SelfHealingPanel, alwaysPresent: false },
  { key: "patch-verification", Comp: PatchVerificationPanel, alwaysPresent: false },
  { key: "incident-memory", Comp: IncidentMemoryPanel, alwaysPresent: false },
  { key: "modernization", Comp: ModernizationPanel, alwaysPresent: false },
  { key: "repository-comparison", Comp: RepositoryComparisonPanel, alwaysPresent: false },
];

export { RepositoryComparisonPanel };
