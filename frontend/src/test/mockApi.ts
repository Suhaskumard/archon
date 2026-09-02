import { vi } from "vitest";
import type { api as realApi } from "../api";
import * as fx from "./fixtures";

type Api = typeof realApi;

/**
 * A full fake `api` — every method a vi.fn() resolving to a fixture. Tests
 * override individual methods, e.g. `mockApi.getHotspots = vi.fn().mockResolvedValue([])`.
 */
export function makeApi(overrides: Partial<Api> = {}): Api {
  const base: Api = {
    listRepositories: vi.fn().mockResolvedValue([fx.repository()]),
    createRepository: vi.fn().mockResolvedValue(fx.repository()),
    listRuns: vi.fn().mockResolvedValue([fx.run()]),
    createRun: vi.fn().mockResolvedValue(fx.run({ state: "QUEUED", id: "run-new" })),
    getRun: vi.fn().mockResolvedValue(fx.run()),
    getRunSource: vi.fn().mockResolvedValue(fx.sourceSummary()),
    listComponents: vi.fn().mockResolvedValue([fx.component()]),
    getArchitecture: vi.fn().mockResolvedValue(fx.architecture()),
    getEvolution: vi.fn().mockResolvedValue(fx.evolution()),
    getAssumptions: vi.fn().mockResolvedValue([fx.assumption()]),
    getBehavior: vi.fn().mockResolvedValue([fx.behavior()]),
    getLegacyDna: vi.fn().mockResolvedValue([fx.legacyDna()]),
    getHotspots: vi.fn().mockResolvedValue([fx.hotspot()]),
    getTechnicalDebt: vi.fn().mockResolvedValue([fx.technicalDebt()]),
    getUnderstanding: vi.fn().mockResolvedValue(fx.understanding()),
    getChangeSafety: vi.fn().mockResolvedValue([fx.changeAssessment()]),
    postChangeImpact: vi.fn().mockResolvedValue(fx.changeImpact()),
    getTests: vi.fn().mockResolvedValue([fx.testCase()]),
    getExecutions: vi.fn().mockResolvedValue([fx.execution()]),
    getCharacterization: vi.fn().mockResolvedValue([fx.characterization()]),
    getTestGaps: vi.fn().mockResolvedValue([fx.testGap()]),
    getFailures: vi.fn().mockResolvedValue([fx.failure()]),
    getInvestigations: vi.fn().mockResolvedValue([fx.investigation()]),
    getPatches: vi.fn().mockResolvedValue([fx.patch()]),
    getVerifications: vi.fn().mockResolvedValue([fx.patchVerification()]),
    getIncidents: vi.fn().mockResolvedValue([fx.incident()]),
    getRepositoryIncidents: vi.fn().mockResolvedValue([fx.incident()]),
    listComparisons: vi.fn().mockResolvedValue([]),
    createComparison: vi.fn().mockResolvedValue(fx.comparison()),
    getComparison: vi.fn().mockResolvedValue(fx.comparison()),
    getModernization: vi.fn().mockResolvedValue([fx.modernization()]),
    downloadReport: vi.fn().mockResolvedValue(undefined),
  };
  return Object.assign(base, overrides);
}
