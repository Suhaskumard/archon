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

export const RUN_PANELS: ReadonlyArray<{ key: string; Comp: FC<PanelProps> }> = [
  { key: "source", Comp: SourceIntelPanel },
  { key: "git-evolution", Comp: GitEvolutionPanel },
  { key: "architecture", Comp: ArchitecturePanel },
  { key: "archaeology", Comp: ArchaeologyPanel },
  { key: "assumptions", Comp: AssumptionsPanel },
  { key: "understanding", Comp: UnderstandingPanel },
  { key: "legacy-dna", Comp: LegacyDnaPanel },
  { key: "technical-debt", Comp: TechnicalDebtPanel },
  { key: "hotspots", Comp: HotspotsPanel },
  { key: "change-safety", Comp: ChangeSafetyPanel },
  { key: "change-impact", Comp: ChangeImpactPanel },
  { key: "test-execution", Comp: TestExecutionPanel },
  { key: "characterization", Comp: CharacterizationPanel },
  { key: "test-intelligence", Comp: TestIntelligencePanel },
  { key: "failures", Comp: FailuresPanel },
  { key: "root-cause", Comp: RootCauseAnalysisPanel },
  { key: "self-healing", Comp: SelfHealingPanel },
  { key: "patch-verification", Comp: PatchVerificationPanel },
  { key: "incident-memory", Comp: IncidentMemoryPanel },
  { key: "modernization", Comp: ModernizationPanel },
  { key: "repository-comparison", Comp: RepositoryComparisonPanel },
];

export { RepositoryComparisonPanel };
