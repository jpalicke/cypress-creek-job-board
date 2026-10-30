// ABOUTME: Tests the presentation helpers: rows are grouped by the API's support, nothing recomputed.
// ABOUTME: An incomplete report never gets a score line, whatever the score field holds.
import { describe, expect, it } from "vitest";
import { groupBySupport, isIncomplete, scoreLine, SUPPORT_ORDER } from "./grouping";
import { makeReport, makeRow, makeScore } from "../test-support";

describe("groupBySupport", () => {
  it("groups rows by the support the API gave them, keeping their order", () => {
    const rows = [
      makeRow({ requirement_id: "R-1", support: "none" }),
      makeRow({ requirement_id: "R-2", support: "strong" }),
      makeRow({ requirement_id: "R-3", support: "none" }),
      makeRow({ requirement_id: "R-4", support: "partial" }),
    ];
    const groups = groupBySupport(rows);
    expect(groups.strong.map((r) => r.requirement_id)).toEqual(["R-2"]);
    expect(groups.partial.map((r) => r.requirement_id)).toEqual(["R-4"]);
    expect(groups.none.map((r) => r.requirement_id)).toEqual(["R-1", "R-3"]);
  });

  it("returns three empty groups for no rows", () => {
    expect(groupBySupport([])).toEqual({ strong: [], partial: [], none: [] });
  });

  it("lists the groups strongest first", () => {
    expect(SUPPORT_ORDER).toEqual(["strong", "partial", "none"]);
  });
});

describe("scoreLine", () => {
  it("shows the score the API computed", () => {
    expect(scoreLine(makeReport())).toBe("62.5 out of 100");
  });

  it("shows no score when the report is incomplete, even if a score is present", () => {
    expect(scoreLine(makeReport({ status: "incomplete" }))).toBeNull();
    expect(isIncomplete(makeReport({ status: "incomplete" }))).toBe(true);
  });

  it("shows no score when the API had none to give", () => {
    expect(scoreLine(makeReport({ score: null }))).toBeNull();
    expect(scoreLine(makeReport({ score: makeScore({ score: null }) }))).toBeNull();
  });
});
