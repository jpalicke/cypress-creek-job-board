// ABOUTME: Component tests for the resume import screen: nothing sent early, one decision at a time.
// ABOUTME: The API is a real local HTTP server with hand written answers; candidate text stays text.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResumeImport from "./ResumeImport.svelte";
import { ApiClient } from "../lib/api";
import { freshHost, startServer, type Seen, type TestServer } from "../test-support";
import type { CandidateOut, ImportResponse, ProviderInfo } from "../lib/types";

const LOCAL: ProviderInfo = {
  provider: "ollama",
  model: "m",
  local: true,
  strict_schema: true,
  context_tokens: 4096,
  cost_per_mtok: { input: 0, output: 0 },
};
const HOSTED: ProviderInfo = { ...LOCAL, provider: "openai_compatible", local: false };

function candidate(overrides: Partial<CandidateOut> = {}): CandidateOut {
  return {
    id: "C-aaaaaaaaaaaaaaaa",
    claim: "Built Python services.",
    kind: "employment",
    tags: ["python"],
    source: "Built Python services and cut the batch",
    state: "pending",
    ...overrides,
  };
}

function imported(overrides: Partial<ImportResponse> = {}): ImportResponse {
  return {
    resume_hash: "h",
    status: "done",
    failure: null,
    backend: "ollama",
    hosted: false,
    candidates: [candidate()],
    dropped: { number_not_in_source: 2 },
    extraction_warnings: [],
    ...overrides,
  };
}

let server: TestServer | undefined;
let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  await server?.close();
  server = undefined;
  document.body.replaceChildren();
});

async function open(
  options: { provider?: ProviderInfo; response?: ImportResponse; pending?: CandidateOut[]; refuse?: (seen: Seen) => unknown } = {},
): Promise<HTMLElement> {
  let pending = options.pending ?? [];
  server = await startServer((seen) => {
    const refusal = options.refuse?.(seen);
    if (refusal) return refusal as { status: number; body: unknown };
    if (seen.url === "/api/session") return { body: { csrf_token: "t" } };
    if (seen.url === "/api/providers") return { body: { providers: [options.provider ?? LOCAL] } };
    if (seen.url === "/api/import/candidates") return { body: { candidates: pending } };
    if (seen.url.startsWith("/api/import/resume")) {
      const response = options.response ?? imported();
      pending = response.candidates;
      return { body: response };
    }
    const id = /candidates\/(C-[0-9a-f]+)\//.exec(seen.url)?.[1] ?? "";
    if (seen.url.endsWith("/approve")) {
      return { body: { candidate: candidate({ id, state: "approved" }), fact: { id: "F-0007" } } };
    }
    return { body: candidate({ id, state: "rejected" }) };
  });
  const host = freshHost();
  mounted = mount(ResumeImport, { target: host, props: { client: new ApiClient(server.url) } });
  await vi.waitFor(() => {
    expect(host.textContent).toContain("Backend:");
  });
  return host;
}

function type(host: HTMLElement, value: string): void {
  const field = host.querySelector<HTMLTextAreaElement>("textarea");
  if (!field) throw new Error("no text box");
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

function press(host: HTMLElement, name: RegExp, within: ParentNode = host): void {
  const found = [...within.querySelectorAll("button")].find((b) => name.test(b.textContent));
  if (!found) throw new Error(`no button ${String(name)}`);
  found.click();
  flushSync();
}

function writes(): Seen[] {
  return (server?.seen ?? []).filter((s) => s.method === "POST" && s.url !== "/api/session");
}

async function run(host: HTMLElement): Promise<void> {
  type(host, "Built Python services and cut the batch.");
  press(host, /find facts/i);
  await vi.waitFor(() => {
    expect(host.querySelector("li.candidate")).not.toBeNull();
  });
}

describe("ResumeImport", () => {
  it("sends nothing until the button is pressed, and the button needs some text", async () => {
    const host = await open();
    const button = [...host.querySelectorAll("button")].find((b) => /find facts/i.test(b.textContent));
    expect(button?.disabled).toBe(true);
    type(host, "Built Python services.");
    expect(button?.disabled).toBe(false);
    expect(writes()).toEqual([]);
  });

  it("shows each candidate with its source words, the dropped counts with reasons, and no approve all", async () => {
    const host = await open();
    await run(host);
    const row = host.querySelector("li.candidate");
    expect(row?.textContent).toContain("Built Python services.");
    expect(row?.textContent).toContain("From the resume: Built Python services and cut the batch");
    expect(row?.textContent).toContain("python");
    expect(host.querySelector("[data-testid=dropped]")?.textContent).toContain("number_not_in_source (2)");
    expect([...host.querySelectorAll("button")].some((b) => /all/i.test(b.textContent))).toBe(false);
  });

  it("approves or rejects one candidate at a time and says what happened", async () => {
    const host = await open({
      response: imported({ candidates: [candidate(), candidate({ id: "C-bbbbbbbbbbbbbbbb", claim: "Second claim." })] }),
    });
    await run(host);
    const rows = host.querySelectorAll("li.candidate");
    press(host, /approve/i, rows[0]);
    await vi.waitFor(() => {
      expect(rows[0]?.textContent).toContain("Approved as F-0007");
    });
    expect(rows[0]?.textContent).toContain("unverified and local only");
    expect(rows[1]?.querySelector("button")).not.toBeNull();
    press(host, /reject/i, rows[1]);
    await vi.waitFor(() => {
      expect(rows[1]?.textContent).toContain("Rejected");
    });
    expect(writes().map((w) => w.url).filter((u) => u.includes("candidates"))).toEqual([
      "/api/import/candidates/C-aaaaaaaaaaaaaaaa/approve",
      "/api/import/candidates/C-bbbbbbbbbbbbbbbb/reject",
    ]);
  });

  it("renders hostile claim and source as text", async () => {
    const hostile = '<img src=x onerror="window.__x = 1"><script>window.__x = 2</script>';
    const host = await open({ response: imported({ candidates: [candidate({ claim: hostile, source: hostile })] }) });
    await run(host);
    expect(host.querySelector("img, script")).toBeNull();
    expect(host.textContent).toContain(hostile);
  });

  it("needs a tick before a resume goes to a hosted backend, and says what is sent", async () => {
    const host = await open({ provider: HOSTED });
    type(host, "Built Python services.");
    const button = [...host.querySelectorAll("button")].find((b) => /find facts/i.test(b.textContent));
    const shown = host.textContent.replace(/\s+/g, " ");
    expect(shown).toContain("hosted: not on this computer");
    expect(shown).toContain("What is sent: the text of the resume (22 characters) and nothing else");
    expect(button?.disabled).toBe(true);
    host.querySelector<HTMLInputElement>("input[type=checkbox]")?.click();
    flushSync();
    expect(button?.disabled).toBe(false);
    button?.click();
    await vi.waitFor(() => {
      expect(writes().some((w) => w.url === "/api/import/resume")).toBe(true);
    });
    expect(JSON.parse(writes().find((w) => w.url === "/api/import/resume")?.body ?? "{}")).toMatchObject({
      backend: "openai_compatible",
      confirm_hosted: true,
    });
  });

  it("shows PDF extractor warnings, a not run import and the API's typed error", async () => {
    const warned = await open({
      response: imported({ status: "not_run", failure: "provider_unavailable", candidates: [], dropped: {}, extraction_warnings: [{ kind: "hidden_white_text", count: 1 }] }),
    });
    type(warned, "Built Python services.");
    press(warned, /find facts/i);
    await vi.waitFor(() => {
      expect(warned.textContent).toContain("hidden_white_text (1)");
    });
    expect(warned.textContent).toContain("did not run: provider_unavailable");
    await unmount(mounted as ReturnType<typeof mount>);
    await server?.close();

    const refused = await open({
      refuse: (seen) =>
        seen.url === "/api/import/resume"
          ? { status: 422, body: { error: { code: "hosted_backend_not_confirmed", message: "A hosted backend must be confirmed in the request." } } }
          : undefined,
    });
    type(refused, "Built Python services.");
    press(refused, /find facts/i);
    await vi.waitFor(() => {
      expect(refused.querySelector('[role="alert"]')?.textContent).toContain("hosted_backend_not_confirmed");
    });
  });

  it("lists candidates that are still pending from an earlier import", async () => {
    const host = await open({ pending: [candidate()] });
    await vi.waitFor(() => {
      expect(host.querySelector("li.candidate")?.textContent).toContain("Built Python services.");
    });
  });

  it("sends a chosen PDF as the raw body with the backend in the query string", async () => {
    const host = await open();
    host.querySelector<HTMLInputElement>("input[value=pdf]")?.click();
    flushSync();
    const button = [...host.querySelectorAll("button")].find((b) => /find facts/i.test(b.textContent));
    expect(button?.disabled).toBe(true);
    const input = host.querySelector<HTMLInputElement>("input[type=file]");
    if (!input) throw new Error("no file input");
    const file = new File(["%PDF-1.4 x"], "resume.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "arrayBuffer", { value: () => Promise.resolve(new TextEncoder().encode("%PDF-1.4 x").buffer) });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    flushSync();
    expect(button?.disabled).toBe(false);
    button?.click();
    await vi.waitFor(() => {
      expect(writes().some((w) => w.url.startsWith("/api/import/resume?"))).toBe(true);
    });
    const sent = writes().find((w) => w.url.startsWith("/api/import/resume?"));
    expect(sent?.url).toBe("/api/import/resume?backend=ollama&confirm_hosted=false");
    expect(sent?.headers["content-type"]).toBe("application/pdf");
  });

  it("says when nothing was proposed and shows an error when a decision fails", async () => {
    const empty = await open({ response: imported({ candidates: [], dropped: {} }) });
    type(empty, "Some text.");
    press(empty, /find facts/i);
    await vi.waitFor(() => {
      expect(empty.textContent).toContain("No facts were proposed");
    });
    await unmount(mounted as ReturnType<typeof mount>);
    await server?.close();

    const failing = await open({
      pending: [candidate()],
      refuse: (seen) =>
        seen.url.endsWith("/approve") || seen.url.endsWith("/reject")
          ? { status: 409, body: { error: { code: "candidate_not_pending", message: "Already decided." } } }
          : undefined,
    });
    await vi.waitFor(() => {
      expect(failing.querySelector("li.candidate")).not.toBeNull();
    });
    press(failing, /approve/i);
    await vi.waitFor(() => {
      expect(failing.querySelector('[role="alert"]')?.textContent).toContain("candidate_not_pending");
    });
    press(failing, /reject/i);
    await vi.waitFor(() => {
      expect(failing.querySelector("li.candidate")?.textContent).not.toContain("Rejected");
    });
  });

  it("shows an unreachable error when the API does not answer", async () => {
    const host = freshHost();
    mounted = mount(ResumeImport, { target: host, props: { client: new ApiClient("http://127.0.0.1:9") } });
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("unreachable");
    });
  });
});
