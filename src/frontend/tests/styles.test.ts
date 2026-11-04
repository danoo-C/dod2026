// Layout rules the tests can't see otherwise: jsdom does no layout, so these
// read the stylesheets themselves.
import { describe, expect, it } from "vitest";

import components from "../src/styles/components.css?raw";
import main from "../src/styles/main.css?raw";

/** The declarations of the first rule with exactly this selector. */
function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, "\\$&");
  const m = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  if (m === null) throw new Error(`no rule for ${selector}`);
  return m[1] ?? "";
}

describe("the terminal's layout", () => {
  it("lines never shrink: with more than fit, the oldest leave at the top", () => {
    // flex items shrink by default; that squeezed every line thinner (found on the real screen)
    expect(rule(components, ".term-body > *")).toMatch(/flex:\s*none/);
    const body = rule(components, ".term-body");
    expect(body).toMatch(/justify-content:\s*flex-end/);
    expect(body).toMatch(/overflow:\s*hidden/);
  });

  it("the main screen's row is the window's height, so the terminal can't grow past it", () => {
    expect(rule(main, ".nb")).toMatch(/grid-template-rows:\s*minmax\(0,\s*1fr\)/);
  });
});
