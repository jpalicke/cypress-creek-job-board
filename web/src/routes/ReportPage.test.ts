// ABOUTME: Component tests for the stored report page: it loads one report by id from the API.
// ABOUTME: A missing report shows a typed error, never a blank page.
import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReportPage from "./ReportPage.svelte";
import { ApiClient } from "../lib/api";
import { freshHost, makeReport, makeRow, startServer, type TestServer } from "../test-support";

let server: TestServer | undefined;
let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  await server?.close();
  server = undefined;
  document.body.replaceChildren();
});

async function open(reportId: string, handler: Parameters<typeof startServer>[0]): Promise<HTMLElement> {
  server = await startServer(handler);
  const host = freshHost();
  mounted = mount(ReportPage, { target: host, props: { reportId, client: new ApiClient(server.url) } });
  return host;
}

describe("ReportPage", () => {
  it("loads a stored report and shows it", async () => {
    const host = await open("rep-1", () => ({
      body: {
        report_id: "rep-1",
        posting_id: "post-1",
        created_at: "2026-01-01T00:00:00Z",
        report: makeReport({ rows: [makeRow({ text: "Needs Python." })] }),
        validator_verdicts: [],
      },
    }));
    await vi.waitFor(() => {
      expect(host.textContent).toContain("Needs Python.");
    });
    expect(server?.seen[0]?.url).toBe("/api/reports/rep-1");
  });

  it("shows the typed error for a report that does not exist", async () => {
    const host = await open("rep-x", () => ({
      status: 404,
      body: { error: { code: "not_found", message: "Not found." } },
    }));
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("not_found");
    });
  });
});
