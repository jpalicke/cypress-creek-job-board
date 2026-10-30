// ABOUTME: Component tests for the Analyze screen against a real local server with hand written answers.
// ABOUTME: Nothing is sent until the person presses the button, and every control has a label.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Analyze from "./Analyze.svelte";
import { ApiClient } from "../lib/api";
import { freshHost, makeReport, startServer, type Handler, type TestServer } from "../test-support";

let server: TestServer | undefined;
let mounted: ReturnType<typeof mount> | undefined;

const provider = (name: string, local: boolean) => ({
  provider: name,
  model: "m",
  local,
  strict_schema: true,
  context_tokens: 4096,
  cost_per_mtok: { input: 0, output: 0 },
});

const posting = {
  id: "post-1",
  source: "paste",
  text: "Needs Python.",
  text_hash: "h",
  origin_url: null,
  warnings: [],
  extraction_warnings: [],
  fetch_warnings: [],
  created_at: "2026-01-01T00:00:00Z",
};

function standardHandler(local = true): Handler {
  return (seen) => {
    if (seen.url === "/api/session") return { body: { csrf_token: "t" } };
    if (seen.url === "/api/providers") {
      return { body: { providers: [provider("ollama", local)] } };
    }
    if (seen.url === "/api/postings") return { status: 201, body: posting };
    if (seen.url.endsWith("/analyze")) {
      return { body: { report_id: "rep-1", report: makeReport({ posting_id: "post-1" }) } };
    }
    return { status: 404, body: { error: { code: "not_found", message: "Not found." } } };
  };
}

async function open(handler: Handler): Promise<HTMLElement> {
  server = await startServer(handler);
  const host = freshHost();
  mounted = mount(Analyze, { target: host, props: { client: new ApiClient(server.url) } });
  await vi.waitFor(() => {
    expect(host.querySelectorAll("select option").length).toBeGreaterThan(0);
  });
  return host;
}

function type(host: HTMLElement, label: string, value: string): void {
  const field = host.querySelector<HTMLTextAreaElement | HTMLInputElement>(
    `[aria-label="${label}"]`,
  );
  if (!field) throw new Error(`no field ${label}`);
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

function press(host: HTMLElement, name: string): void {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent.trim() === name);
  if (!button) throw new Error(`no button ${name}`);
  button.click();
  flushSync();
}

afterEach(async () => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  await server?.close();
  server = undefined;
  document.body.replaceChildren();
});

describe("Analyze", () => {
  it("sends nothing on load except the read of the configured backends", async () => {
    await open(standardHandler());
    expect(server?.seen.map((s) => `${s.method} ${s.url}`)).toEqual(["GET /api/providers"]);
  });

  it("labels every control and lists the configured backend", async () => {
    const host = await open(standardHandler());
    expect(host.querySelector('[aria-label="Posting text"]')).not.toBeNull();
    expect(host.querySelector('[aria-label="Backend"]')).not.toBeNull();
    for (const [value, label] of [["link", "Posting link"], ["pdf", "Posting PDF"]] as const) {
      host.querySelector<HTMLInputElement>(`input[type="radio"][value="${value}"]`)?.click();
      flushSync();
      expect(host.querySelector(`[aria-label="${label}"]`), label).not.toBeNull();
    }
    for (const label of host.querySelectorAll("label")) {
      expect(label.textContent.trim().length).toBeGreaterThan(0);
    }
    expect(host.querySelector("select option")?.textContent).toContain("ollama");
    expect(host.querySelector("select option")?.textContent).toContain("m");
  });

  it("adds the posting then analyzes it when the button is pressed, and shows the report", async () => {
    const host = await open(standardHandler());
    type(host, "Posting text", "Needs Python.");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(host.querySelector('[data-testid="score"]')).not.toBeNull();
    });
    const urls = server?.seen.map((s) => `${s.method} ${s.url}`);
    expect(urls).toEqual([
      "GET /api/providers",
      "GET /api/session",
      "POST /api/postings",
      "POST /api/postings/post-1/analyze",
    ]);
    const analyze = server?.seen.find((s) => s.url.endsWith("/analyze"));
    expect(JSON.parse(analyze?.body ?? "")).toEqual({ backend: "ollama", confirm_hosted: false });
    expect(host.querySelector('a[href="#/report/rep-1"]')).not.toBeNull();
  });

  it("shows posting warnings above the report", async () => {
    const handler = standardHandler();
    const host = await open((seen) =>
      seen.url === "/api/postings"
        ? {
            status: 201,
            body: {
              ...posting,
              warnings: [{ kind: "control_chars_stripped", count: 3 }],
              fetch_warnings: ["cross_host_redirect"],
              extraction_warnings: [{ kind: "hidden_elements_removed", count: 1 }],
            },
          }
        : handler(seen),
    );
    type(host, "Posting text", "Needs Python.");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(host.querySelector('[data-testid="posting-warnings"]')).not.toBeNull();
    });
    const text = host.querySelector('[data-testid="posting-warnings"]')?.textContent ?? "";
    expect(text).toContain("control_chars_stripped");
    expect(text).toContain("cross_host_redirect");
    expect(text).toContain("hidden_elements_removed");
  });

  it("shows the posting text it received as text only", async () => {
    const handler = standardHandler();
    const host = await open((seen) =>
      seen.url === "/api/postings"
        ? { status: 201, body: { ...posting, text: '<img src=x onerror="alert(1)">' } }
        : handler(seen),
    );
    type(host, "Posting text", "anything");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(host.querySelector('[data-testid="posting-preview"]')).not.toBeNull();
    });
    expect(host.querySelector("img")).toBeNull();
    expect(host.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("adds a link posting when the link tab is used", async () => {
    const host = await open(standardHandler());
    const link = host.querySelector<HTMLInputElement>('input[type="radio"][value="link"]');
    link?.click();
    flushSync();
    type(host, "Posting link", "https://example.com/job");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(server?.seen.some((s) => s.url.endsWith("/analyze"))).toBe(true);
    });
    const post = server?.seen.find((s) => s.url === "/api/postings");
    expect(JSON.parse(post?.body ?? "")).toEqual({ source: "link", url: "https://example.com/job" });
  });

  it("sends a chosen PDF as application/pdf", async () => {
    const host = await open(standardHandler());
    host.querySelector<HTMLInputElement>('input[type="radio"][value="pdf"]')?.click();
    flushSync();
    const input = host.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["%PDF-1.4 x"], "job.pdf", { type: "application/pdf" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    flushSync();
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(server?.seen.some((s) => s.url === "/api/postings")).toBe(true);
    });
    const post = server?.seen.find((s) => s.url === "/api/postings");
    expect(post?.headers["content-type"]).toBe("application/pdf");
  });

  it("shows a typed error from the API and keeps the form usable", async () => {
    const handler = standardHandler();
    const host = await open((seen) =>
      seen.url === "/api/postings"
        ? {
            status: 422,
            body: { error: { code: "empty_posting", message: "Paste the posting text." } },
          }
        : handler(seen),
    );
    type(host, "Posting text", "   ");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')).not.toBeNull();
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("empty_posting");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Paste the posting text.");
    expect(host.querySelector("button[disabled]")).toBeNull();
  });

  it("explains when no backend is configured", async () => {
    server = await startServer((seen) =>
      seen.url === "/api/providers" ? { body: { providers: [] } } : { body: {} },
    );
    const host = freshHost();
    mounted = mount(Analyze, { target: host, props: { client: new ApiClient(server.url) } });
    await vi.waitFor(() => {
      expect(host.textContent).toContain("No backend is configured");
    });
    expect(host.querySelector("button[type=submit]")?.hasAttribute("disabled")).toBe(true);
  });

  it("shows the API being down as an error and nothing else", async () => {
    const host = freshHost();
    mounted = mount(Analyze, { target: host, props: { client: new ApiClient("http://127.0.0.1:9") } });
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("unreachable");
    });
  });

  it("makes a hosted backend need an explicit confirmation before it can run", async () => {
    const host = await open(standardHandler(false));
    const run = host.querySelector<HTMLButtonElement>("button[type=submit]");
    expect(run?.disabled).toBe(true);
    const confirm = host.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(confirm).not.toBeNull();
    confirm?.click();
    flushSync();
    expect(run?.disabled).toBe(false);
    type(host, "Posting text", "Needs Python.");
    press(host, "Analyze");
    await vi.waitFor(() => {
      expect(server?.seen.some((s) => s.url.endsWith("/analyze"))).toBe(true);
    });
    const analyze = server?.seen.find((s) => s.url.endsWith("/analyze"));
    expect(JSON.parse(analyze?.body ?? "")).toEqual({ backend: "ollama", confirm_hosted: true });
  });
});
