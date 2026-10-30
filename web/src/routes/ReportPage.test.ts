// ABOUTME: Component tests for the stored report page: it loads one report by id from the API.
// ABOUTME: A missing report shows a typed error, never a blank page.
import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReportPage from "./ReportPage.svelte";
import { ApiClient } from "../lib/api";
import { freshHost, makeReport, makeRow, startServer, type TestServer } from "../test-support";

const PROVIDER = {
  provider: "ollama",
  model: "m",
  local: true,
  strict_schema: true,
  context_tokens: 4096,
  cost_per_mtok: { input: 0, output: 0 },
};

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
    const host = await open("rep-1", (seen) =>
      seen.url === "/api/providers"
        ? { body: { providers: [PROVIDER] } }
        : {
            body: {
              report_id: "rep-1",
              posting_id: "post-1",
              created_at: "2026-01-01T00:00:00Z",
              report: makeReport({ rows: [makeRow({ text: "Needs Python." })] }),
              validator_verdicts: [],
            },
          },
    );
    await vi.waitFor(() => {
      expect(host.textContent).toContain("Needs Python.");
    });
    expect(server?.seen.map((s) => s.url)).toContain("/api/reports/rep-1");
  });

  it("offers Draft help on a supported requirement only once the backend list has loaded", async () => {
    const host = await open("rep-1", (seen) =>
      seen.url === "/api/providers"
        ? { body: { providers: [PROVIDER] } }
        : {
            body: {
              report_id: "rep-1",
              posting_id: "post-1",
              created_at: "2026-01-01T00:00:00Z",
              report: makeReport({
                rows: [
                  makeRow({ requirement_id: "R-1", text: "Needs Python." }),
                  makeRow({ requirement_id: "R-2", text: "Needs Go.", support: "none", fact_ids: [] }),
                ],
              }),
              validator_verdicts: [],
            },
          },
    );
    await vi.waitFor(() => {
      expect([...host.querySelectorAll("button")].map((b) => b.textContent.trim())).toEqual(["Draft help"]);
    });
    expect(host.textContent).toContain("No verified fact supports this");
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

  it("still shows the report when the backend list cannot be loaded, and offers no draft", async () => {
    const host = await open("rep-1", (seen) =>
      seen.url === "/api/providers"
        ? { status: 500, body: {} }
        : {
            body: {
              report_id: "rep-1",
              posting_id: "post-1",
              created_at: "2026-01-01T00:00:00Z",
              report: makeReport({ rows: [makeRow({ text: "Needs Python." })] }),
              validator_verdicts: [],
            },
          },
    );
    await vi.waitFor(() => {
      expect(host.textContent).toContain("Needs Python.");
    });
    expect([...host.querySelectorAll("button")].find((b) => b.textContent.includes("Draft help"))?.disabled).toBe(true);
  });
});
