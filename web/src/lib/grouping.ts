// ABOUTME: Presentation helpers for the gap report: group rows by the support the API gave them.
// ABOUTME: Nothing here computes support or a score; those come from the API and are only shown.
import type { GapReport, ReportRow, Support } from "./types";

export const SUPPORT_ORDER: readonly Support[] = ["strong", "partial", "none"];

export const SUPPORT_TITLES: Record<Support, string> = {
  strong: "Strong support",
  partial: "Partial support",
  none: "No support",
};

export type Groups = Record<Support, ReportRow[]>;

export function groupBySupport(rows: readonly ReportRow[]): Groups {
  const groups: Groups = { strong: [], partial: [], none: [] };
  for (const row of rows) groups[row.support].push(row);
  return groups;
}

export function isIncomplete(report: GapReport): boolean {
  return report.status === "incomplete";
}

/** The score line, or null when the API gave no score. The incomplete case never shows one. */
export function scoreLine(report: GapReport): string | null {
  if (isIncomplete(report) || report.score === null || report.score.score === null) return null;
  return `${report.score.score.toFixed(1)} out of 100`;
}
