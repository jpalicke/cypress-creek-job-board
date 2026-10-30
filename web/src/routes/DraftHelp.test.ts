// ABOUTME: Component tests for draft help: the review gate, the disabled Copy and the hostile text.
// ABOUTME: The API is a real local HTTP server with hand written answers; nothing sends or copies alone.
import { mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DraftHelp from "./DraftHelp.svelte";
import { ApiClient } from "../lib/api";
import {
  freshHost,
  makeRow,
  startServer,
  type Handler,
  type TestServer,
} from "../test-support";
import type { ProviderInfo, SuggestionResponse } from "../lib/types";

const LOCAL: ProviderInfo = {
  provider: "ollama",
  model: "m",
  local: true,
  strict_schema: true,
  context_tokens: 4096,
  cost_per_mtok: { input: 0, output: 0 },
};
const HOSTED: ProviderInfo = { ...LOCAL, provider: "openai_compatible", local: false };

function answer(overrides: Partial<SuggestionResponse> = {}): SuggestionResponse {
  return {
    requirement_id: "R-1",
    requirement_text: "Needs Python.",
    status: "drafted",
    failure: null,
    needs_human_review: true,
    sentences: [
      {
        text: "Backend Developer at Gravy Boat Labs, where I built and ran Python services.",
        fact_ids: ["F-0001"],
        passed: true,
        verdicts: [{ validator: "V6", passed: true, reason: "ok" }],
      },
      {
        text: "I led a team of 40 engineers.",
        fact_ids: ["F-0001"],
        passed: false,
        verdicts: [{ validator: "V9", passed: false, reason: "a number is not in the cited facts" }],
      },
    ],
    facts: [{ id: "F-0001", claim: "Backend Developer at Gravy Boat Labs." }],
    ...overrides,
  };
}

let server: TestServer | undefined;
let mounted: ReturnType<typeof mount> | undefined;
let written: string[] = [];

beforeEach(() => {
  written = [];
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: (value: string): Promise<void> => {
        written.push(value);
        return Promise.resolve();
      },
    },
  });
});

afterEach(async () => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  await server?.close();
  server = undefined;
  document.body.replaceChildren();
});

async function open(
  handler: Handler,
  options: { row?: Parameters<typeof makeRow>[0]; providers?: ProviderInfo[] } = {},
): Promise<HTMLElement> {
  server = await startServer(handler);
  const host = freshHost();
  mounted = mount(DraftHelp, {
    target: host,
    props: {
      reportId: "rep-1",
      row: makeRow({ requirement_id: "R-1", text: "Needs Python.", ...options.row }),
      providers: options.providers ?? [LOCAL],
      client: new ApiClient(server.url),
    },
  });
  return host;
}

function button(host: HTMLElement, name: RegExp): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => name.test(b.textContent));
  if (!found) throw new Error(`no button ${String(name)}`);
  return found;
}

async function drafted(host: HTMLElement): Promise<void> {
  button(host, /draft help/i).click();
  await vi.waitFor(() => {
    expect(host.querySelectorAll("li.bullet").length).toBeGreaterThan(0);
  });
}

const csrf: Handler = (seen) =>
  seen.url === "/api/session" ? { body: { csrf_token: "tok" } } : { body: answer() };

describe("DraftHelp", () => {
  it("sends nothing until the Draft help button is pressed", async () => {
    const host = await open(csrf);
    await new Promise((done) => setTimeout(done, 50));
    expect(server?.seen).toEqual([]);
    expect(button(host, /draft help/i).disabled).toBe(false);
  });

  it("offers no draft for a requirement with no support, and points to the fact bank", async () => {
    const host = await open(csrf, { row: { support: "none", fact_ids: [] } });
    expect(host.textContent).toContain("No verified fact supports this");
    expect(host.textContent).toContain("add a fact to your bank");
    expect(host.querySelector("button")).toBeNull();
  });

  it("starts with every Copy disabled and every review box unticked", async () => {
    const host = await open(csrf);
    await drafted(host);
    const boxes = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(boxes.length).toBe(2);
    expect(boxes.every((box) => !box.checked)).toBe(true);
    const copies = [...host.querySelectorAll("button")].filter((b) => /^copy/i.test(b.textContent));
    expect(copies.length).toBe(2);
    expect(copies.every((copy) => copy.disabled)).toBe(true);
    expect(written).toEqual([]);
  });

  it("enables Copy only for the bullet whose own box is ticked, and unticking disables it again", async () => {
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      body: answer({
        sentences: [
          ...answer().sentences.slice(0, 1),
          { text: "Ran Python services.", fact_ids: ["F-0001"], passed: true, verdicts: [] },
        ],
      }),
    }));
    await drafted(host);
    const boxes = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    const copies = (): HTMLButtonElement[] =>
      [...host.querySelectorAll("button")].filter((b) => /^copy/i.test(b.textContent));
    boxes[1]?.click();
    await vi.waitFor(() => {
      expect(copies()[1]?.disabled).toBe(false);
    });
    expect(copies()[0]?.disabled).toBe(true);
    boxes[1]?.click();
    await vi.waitFor(() => {
      expect(copies()[1]?.disabled).toBe(true);
    });
  });

  it("copies one bullet only when its Copy is clicked", async () => {
    const host = await open(csrf);
    await drafted(host);
    host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[0]?.click();
    expect(written).toEqual([]);
    await vi.waitFor(() => {
      expect([...host.querySelectorAll("button")].find((b) => /^copy/i.test(b.textContent))?.disabled).toBe(false);
    });
    [...host.querySelectorAll("button")].find((b) => /^copy/i.test(b.textContent))?.click();
    await vi.waitFor(() => {
      expect(written).toEqual(["Backend Developer at Gravy Boat Labs, where I built and ran Python services."]);
    });
  });

  it("shows a failed bullet flagged with its reason and keeps Copy disabled even when ticked", async () => {
    const host = await open(csrf);
    await drafted(host);
    const flagged = host.querySelectorAll("li.bullet")[1] as HTMLElement;
    expect(flagged.textContent).toContain("Failed a check");
    expect(flagged.textContent).toContain("a number is not in the cited facts");
    flagged.querySelector<HTMLInputElement>('input[type="checkbox"]')?.click();
    await new Promise((done) => setTimeout(done, 20));
    expect(flagged.querySelector<HTMLButtonElement>("button")?.disabled).toBe(true);
  });

  it("shows the cited facts with their claim text", async () => {
    const host = await open(csrf);
    await drafted(host);
    expect(host.textContent).toContain("F-0001");
    expect(host.textContent).toContain("Backend Developer at Gravy Boat Labs.");
  });

  it("renders hostile text as text and never as markup", async () => {
    const hostile = '<img src=x onerror="window.__x = 1"><script>window.__x = 2</script>';
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      body: answer({
        sentences: [{ text: hostile, fact_ids: ["F-0001"], passed: false, verdicts: [] }],
      }),
    }));
    await drafted(host);
    expect(host.querySelector("img, script")).toBeNull();
    expect(host.textContent).toContain(hostile);
  });

  it("says why nothing was drafted when the model did not run", async () => {
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      body: answer({ status: "not_run", failure: "provider_unavailable", sentences: [], facts: [] }),
    }));
    button(host, /draft help/i).click();
    await vi.waitFor(() => {
      expect(host.textContent).toContain("did not run");
    });
    expect(host.textContent).toContain("provider_unavailable");
  });

  it("shows the typed error when the API refuses", async () => {
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      status: 404,
      body: { error: { code: "not_found", message: "Not found." } },
    }));
    button(host, /draft help/i).click();
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("not_found");
    });
  });

  it("needs a tick before a hosted backend gets the requirement", async () => {
    const host = await open(csrf, { providers: [HOSTED] });
    expect(button(host, /draft help/i).disabled).toBe(true);
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.click();
    await vi.waitFor(() => {
      expect(button(host, /draft help/i).disabled).toBe(false);
    });
    button(host, /draft help/i).click();
    await vi.waitFor(() => {
      expect(server?.seen.some((s) => s.url.endsWith("/suggestions"))).toBe(true);
    });
    const request = server?.seen.find((s) => s.url.endsWith("/suggestions"));
    expect(JSON.parse(request?.body ?? "{}")).toEqual({
      requirement_id: "R-1",
      backend: "openai_compatible",
      confirm_hosted: true,
    });
  });

  it("says nothing was drafted when the API answers no_support for a requirement", async () => {
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      body: answer({ status: "no_support", sentences: [], facts: [] }),
    }));
    button(host, /draft help/i).click();
    await vi.waitFor(() => {
      expect(host.textContent).toContain("nothing was drafted");
    });
  });

  it("shows an unreachable error when the API does not answer", async () => {
    const host = freshHost();
    mounted = mount(DraftHelp, {
      target: host,
      props: {
        reportId: "rep-1",
        row: makeRow({ requirement_id: "R-1" }),
        providers: [LOCAL],
        client: new ApiClient("http://127.0.0.1:9"),
      },
    });
    button(host, /draft help/i).click();
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("unreachable");
    });
  });

  it("shows a bullet whose cited fact is unknown without inventing a claim", async () => {
    const host = await open((seen) => (seen.url === "/api/session" ? { body: { csrf_token: "t" } } : {
      body: answer({ facts: [] }),
    }));
    await drafted(host);
    expect(host.querySelectorAll("li.bullet")[0]?.textContent).toContain("F-0001");
  });

  it("offers no button while the backend list is empty", async () => {
    const host = await open(csrf, { providers: [] });
    expect(button(host, /draft help/i).disabled).toBe(true);
  });
});
