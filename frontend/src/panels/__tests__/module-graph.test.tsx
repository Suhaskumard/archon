import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModuleGraphSvg } from "../module-graph";
import { layoutModules } from "../graph-layout";
import * as fx from "../../test/fixtures";

describe("graph-layout", () => {
  it("is deterministic and positions every module", () => {
    const mods = fx.architecture().modules;
    const a = layoutModules(mods);
    const b = layoutModules(mods);
    expect([...a.keys()].sort()).toEqual(mods.map((m) => m.qualified_name).sort());
    expect(a.get(mods[0].qualified_name)).toEqual(b.get(mods[0].qualified_name));
  });
});

describe("ModuleGraphSvg", () => {
  it("renders a node per module and an edge per dependency", () => {
    const arch = fx.architecture();
    const { container } = render(<ModuleGraphSvg arch={arch} />);
    expect(container.querySelectorAll("circle").length).toBe(arch.modules.length);
    const deps = arch.modules.reduce((n, m) => n + m.dependencies.length, 0);
    expect(container.querySelectorAll("line").length).toBe(deps);
  });

  it("zooms on wheel and restores on reset", () => {
    const { container } = render(<ModuleGraphSvg arch={fx.architecture()} />);
    const svg = container.querySelector("svg")!;
    const before = svg.getAttribute("viewBox");
    fireEvent.wheel(svg, { deltaY: 100 });
    expect(svg.getAttribute("viewBox")).not.toBe(before);
    fireEvent.click(screen.getByRole("button", { name: /reset view/i }));
    expect(svg.getAttribute("viewBox")).toBe(before);
  });

  it("pans on pointer drag", () => {
    const { container } = render(<ModuleGraphSvg arch={fx.architecture()} />);
    const svg = container.querySelector("svg")!;
    const before = svg.getAttribute("viewBox");
    fireEvent.pointerDown(svg, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(svg, { clientX: 40, clientY: 25, pointerId: 1 });
    fireEvent.pointerUp(svg, { pointerId: 1 });
    expect(svg.getAttribute("viewBox")).not.toBe(before);
  });
});
