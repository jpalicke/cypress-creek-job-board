// ABOUTME: Component tests for the gap report: grouping, the incomplete banner, the score line.
// ABOUTME: Hostile text must stay text: no script or image element may appear in the rendered DOM.
import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import GapReport from "./GapReport.svelte";
import { freshHost, makeReport, makeRow, makeScore } from "../test-support";
import type { GapReport as Report } from "../lib/types";

let mounted: ReturnType<typeof mount> | undefined;

function show(report: Report): HTMLElement {
  const host = freshHost();
  mounted = mount(GapReport, { target: host, props: { report } });
  return host;
}

afterEach(() => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  document.body.replaceChildren();
});

describe("GapReport", () => {
  it("groups requirements by support, strongest first, each with its facts and rationale", () => {
    const host = show(
      makeReport({
        rows: [
          makeRow({ requirement_id: "R-1", text: "Needs SQL.", support: "none", fact_ids: [] }),
          makeRow({
            requirement_id: "R-2",
            text: "Needs Python.",
            support: "strong",
            fact_ids: ["F-0001", "F-0002"],
            rationale: "F-0001 shows Python work.",
          }),
          makeRow({ requirement_id: "R-3", text: "Needs Docker.", support: "partial" }),
        ],
      }),
    );
    const headings = [...host.querySelectorAll("h3")].map((h) => h.textContent);
    expect(headings).toEqual(["Strong support (1)", "Partial support (1)", "No support (1)"]);
    const strong = host.querySelector('section[aria-label="Strong support"]');
    expect(strong?.textContent).toContain("Needs Python.");
    expect(strong?.textContent).toContain("F-0001, F-0002");
    expect(strong?.textContent).toContain("F-0001 shows Python work.");
    expect(host.querySelector('section[aria-label="No support"]')?.textContent).toContain(
      "no verified fact cited",
    );
  });

  it("shows the score with the API's own disclaimer, never without it", () => {
    const host = show(makeReport());
    const score = host.querySelector('[data-testid="score"]');
    expect(score?.textContent).toContain("62.5 out of 100");
    expect(score?.textContent).toContain("triage only, not a probability");
    expect(score?.textContent).toContain("Supported 1 of 2");
  });

  it("shows a banner and no score when the report is incomplete", () => {
    const host = show(
      makeReport({
        status: "incomplete",
        incomplete_reasons: ["extraction failed: provider_unavailable"],
        score: null,
      }),
    );
    const banner = host.querySelector('[role="alert"]');
    expect(banner?.textContent).toContain("Incomplete");
    expect(banner?.textContent).toContain("extraction failed: provider_unavailable");
    expect(host.querySelector('[data-testid="score"]')).toBeNull();
    expect(host.textContent).not.toContain("out of 100");
  });

  it("hides the score of an incomplete report even if the API sent one", () => {
    const host = show(makeReport({ status: "incomplete" }));
    expect(host.querySelector('[data-testid="score"]')).toBeNull();
  });

  it("says plainly when there is nothing to score", () => {
    const host = show(makeReport({ score: makeScore({ score: null, total: 0 }) }));
    expect(host.querySelector('[data-testid="score"]')?.textContent).toContain("No score");
  });

  it("lists warnings on top, the cue sentences not assessed, and dropped proposals", () => {
    const host = show(
      makeReport({
        warnings: [{ kind: "control_chars_stripped", count: 2 }],
        not_assessed_count: 1,
        not_assessed: [{ reason: "cue_sentence_uncovered", text: "Must know Rust.", span: [3, 18] }],
        dropped: [{ text: "Invented thing", reason: "text_not_in_posting" }],
      }),
    );
    expect(host.querySelector('[data-testid="warnings"]')?.textContent).toContain(
      "control_chars_stripped",
    );
    expect(host.querySelector('[data-testid="not-assessed"]')?.textContent).toContain(
      "Must know Rust.",
    );
    expect(host.querySelector('[data-testid="dropped"]')?.textContent).toContain("Invented thing");
  });

  it("marks rows that the model did not check, and rows whose second opinion failed", () => {
    const host = show(
      makeReport({
        rows: [makeRow({ not_model_checked: true, failure: "provider_unavailable" })],
      }),
    );
    expect(host.textContent).toContain("not model checked");
    expect(host.textContent).toContain("provider_unavailable");
  });

  it("says so when the report has no requirements", () => {
    expect(show(makeReport()).textContent).toContain("No requirements");
  });

  it("renders hostile text as text and adds no script, image or event handler", () => {
    const script = "<script>window.__x = 1</script>";
    const image = '<img src=x onerror="window.__x = 2">';
    const host = show(
      makeReport({
        rows: [makeRow({ text: script, fact_ids: [image], rationale: image })],
        gaps: [script],
        warnings: [],
        not_assessed_count: 1,
        not_assessed: [{ reason: "cue_sentence_uncovered", text: script, span: [0, 1] }],
        dropped: [{ text: image, reason: "invalid_field" }],
        incomplete_reasons: [script],
        provenance: {
          backend: script,
          model: image,
          run_id: "run-1",
          prompt_hashes: {},
          usage: { input_tokens: 0, output_tokens: 0 },
        },
      }),
    );
    expect(host.querySelector("script")).toBeNull();
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("[onerror]")).toBeNull();
    expect(host.textContent).toContain(script);
    expect(host.textContent).toContain(image);
    expect((window as unknown as { __x?: number }).__x).toBeUndefined();
  });
});
