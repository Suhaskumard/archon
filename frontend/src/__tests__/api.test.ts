import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";

function jsonRes(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob(["x"])),
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => vi.unstubAllGlobals());

const fetchMock = () => vi.mocked(fetch);

describe("req", () => {
  it("returns the parsed body on success and sends JSON headers", async () => {
    fetchMock().mockResolvedValue(jsonRes([{ id: "r1" }]));
    const repos = await api.listRepositories();
    expect(repos).toEqual([{ id: "r1" }]);
    expect(fetchMock()).toHaveBeenCalledWith("/repositories", expect.objectContaining({
      headers: expect.objectContaining({ "Content-Type": "application/json" }),
    }));
  });

  it("throws `CODE: message` from an error envelope", async () => {
    fetchMock().mockResolvedValue(
      jsonRes({ error: { code: "NOT_FOUND", message: "no such run" } }, false, 404),
    );
    await expect(api.getRun("x")).rejects.toThrow("NOT_FOUND: no such run");
  });

  it("falls back to `HTTP <status>` without an envelope", async () => {
    fetchMock().mockResolvedValue(jsonRes({}, false, 500));
    await expect(api.getRun("x")).rejects.toThrow("HTTP 500");
  });

  it("builds POST bodies", async () => {
    fetchMock().mockResolvedValue(jsonRes({ id: "run-1" }));
    await api.createRun("repo-1", "ANALYSIS_ONLY");
    expect(fetchMock()).toHaveBeenCalledWith(
      "/repositories/repo-1/runs",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ ref: null, mode: "ANALYSIS_ONLY" }) }),
    );
  });

  it("passes the component query string through", async () => {
    fetchMock().mockResolvedValue(jsonRes([]));
    await api.listComponents("snap-1", "&kind=MODULE");
    expect(fetchMock()).toHaveBeenCalledWith(
      "/snapshots/snap-1/components?limit=1000&kind=MODULE",
      expect.anything(),
    );
  });
});

describe("downloadReport", () => {
  it("fetches the xlsx and triggers a download", async () => {
    fetchMock().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(new Blob(["xlsx"])),
      json: () => Promise.resolve({}),
    } as unknown as Response);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await api.downloadReport("run-1");
    expect(fetchMock()).toHaveBeenCalledWith("/runs/run-1/report.xlsx");
    expect(click).toHaveBeenCalled();
  });

  it("throws the error envelope on a bad response", async () => {
    fetchMock().mockResolvedValue(
      jsonRes({ error: { code: "CONFLICT", message: "not ready" } }, false, 409),
    );
    await expect(api.downloadReport("run-1")).rejects.toThrow("CONFLICT: not ready");
  });
});
