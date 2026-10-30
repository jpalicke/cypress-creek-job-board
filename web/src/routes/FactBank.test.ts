// ABOUTME: Component tests for the fact bank screen: states, the verify button, forms and delete.
// ABOUTME: The API is a real local HTTP server holding a small bank; the UI shows what it returns.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import FactBank from "./FactBank.svelte";
import { ApiClient } from "../lib/api";
import { freshHost, startServer, type Seen, type TestServer } from "../test-support";
import type { Fact } from "../lib/types";

function fact(overrides: Partial<Fact> = {}): Fact {
  return {
    id: "F-0001",
    claim: "Built a reporting service in Python.",
    kind: "project",
    employer: null,
    issuer: null,
    role: null,
    start: null,
    end: null,
    tags: [{ name: "python", level: "working" }],
    verified_on: null,
    evidence: { type: "self_attested", pointer: "my notes" },
    share: "local_only",
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

/** A bank in memory behind a real HTTP server, answering the way the API does. */
async function open(initial: Fact[], reject?: (seen: Seen) => unknown): Promise<HTMLElement> {
  const bank = [...initial];
  server = await startServer((seen) => {
    const refusal = reject?.(seen);
    if (refusal) return refusal as { status: number; body: unknown };
    const id = /\/api\/facts\/(F-\d{4})/.exec(seen.url)?.[1];
    const index = bank.findIndex((f) => f.id === id);
    if (seen.url === "/api/session") return { body: { csrf_token: "t" } };
    if (seen.url === "/api/facts" && seen.method === "GET") {
      return { body: { facts: bank, unverified_ids: bank.filter((f) => !f.verified_on).map((f) => f.id) } };
    }
    if (seen.url === "/api/facts" && seen.method === "POST") {
      const created = fact({ ...(JSON.parse(seen.body) as Partial<Fact>), id: "F-0099", verified_on: null, share: "local_only" });
      bank.push(created);
      return { status: 201, body: created };
    }
    const current = bank[index];
    if (!current) return { status: 404, body: { error: { code: "not_found", message: "Not found." } } };
    if (seen.url.endsWith("/verify")) bank[index] = { ...current, verified_on: "2026-06-01" };
    else if (seen.url.endsWith("/unverify")) bank[index] = { ...current, verified_on: null };
    else if (seen.url.endsWith("/share")) bank[index] = { ...current, share: (JSON.parse(seen.body) as { share: Fact["share"] }).share };
    else if (seen.method === "PUT") {
      const edited = JSON.parse(seen.body) as Partial<Fact>;
      bank[index] = { ...current, ...edited, verified_on: edited.claim === current.claim ? current.verified_on : null };
    } else if (seen.method === "DELETE") {
      bank.splice(index, 1);
      return { body: { removed: true } };
    }
    return { body: bank[index] };
  });
  const host = freshHost();
  mounted = mount(FactBank, { target: host, props: { client: new ApiClient(server.url) } });
  await vi.waitFor(() => {
    expect(host.querySelector(".toolbar")).not.toBeNull();
  });
  return host;
}

function press(host: HTMLElement, name: RegExp): void {
  const found = [...host.querySelectorAll("button")].find((b) => name.test(b.textContent));
  if (!found) throw new Error(`no button ${String(name)}`);
  found.click();
  flushSync();
}

function type(field: HTMLInputElement | HTMLTextAreaElement | null, value: string): void {
  if (!field) throw new Error("no such field");
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

function writes(): Seen[] {
  return (server?.seen ?? []).filter((s) => s.method !== "GET" && s.url !== "/api/session");
}

const verifiedFact = fact({ id: "F-0002", claim: "Ran the nightly batch.", verified_on: "2026-03-01", share: "shareable" });

describe("FactBank", () => {
  it("shows each fact with its state: verified or not, and whether a model may see it", async () => {
    const host = await open([fact(), verifiedFact]);
    const rows = host.querySelectorAll("li.fact");
    expect(rows[0]?.textContent).toContain("Unverified");
    expect(rows[0]?.textContent).toContain("Local only");
    expect(rows[0]?.textContent).toContain("never shown to a model");
    expect(rows[1]?.textContent).toContain("Verified on 2026-03-01");
    expect(rows[1]?.textContent).toContain("may be shown to a model");
    expect(rows[0]?.textContent).toContain("python (working)");
    expect(host.querySelector("input[type=checkbox]")).toBeNull();
  });

  it("verifies exactly one fact, only when its own button is pressed", async () => {
    const host = await open([fact(), fact({ id: "F-0003", claim: "Second claim." })]);
    expect(writes()).toEqual([]);
    const first = host.querySelectorAll("li.fact")[0] as HTMLElement;
    [...first.querySelectorAll("button")].find((b) => /^verify/i.test(b.textContent))?.click();
    await vi.waitFor(() => {
      expect(host.querySelectorAll("li.fact")[0]?.textContent).toContain("Verified on 2026-06-01");
    });
    expect(writes().map((w) => w.url)).toEqual(["/api/facts/F-0001/verify"]);
    expect(host.querySelectorAll("li.fact")[1]?.textContent).toContain("Unverified");
  });

  it("changes the share state with its own labelled control and leaves verification alone", async () => {
    const host = await open([verifiedFact]);
    press(host, /make local only/i);
    await vi.waitFor(() => {
      expect(host.querySelector("li.fact")?.textContent).toContain("Local only");
    });
    expect(writes().map((w) => `${w.method} ${w.url}`)).toEqual(["PUT /api/facts/F-0002/share"]);
    expect(host.querySelector("li.fact")?.textContent).toContain("Verified on 2026-03-01");
  });

  it("adds a fact without sending any verification, share or id", async () => {
    const host = await open([]);
    press(host, /add a fact/i);
    type(host.querySelector<HTMLTextAreaElement>("textarea[name=claim]"), "Wrote a parser.");
    type(host.querySelector<HTMLInputElement>("input[name=pointer]"), "notes");
    press(host, /^save fact/i);
    await vi.waitFor(() => {
      expect(host.querySelector("li.fact")?.textContent).toContain("Wrote a parser.");
    });
    const body = JSON.parse(writes()[0]?.body ?? "{}") as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(
      ["claim", "employer", "end", "evidence", "issuer", "kind", "role", "start", "tags"].sort(),
    );
    expect(host.querySelector("li.fact")?.textContent).toContain("Unverified");
  });

  it("shows the API's error next to the field and keeps the form", async () => {
    const host = await open([], (seen) =>
      seen.method === "POST" && seen.url === "/api/facts"
        ? { status: 422, body: { error: { code: "invalid_request", message: "The request is invalid.", details: [{ field: "start", problem: "2999-01-01 is in the future" }] } } }
        : undefined,
    );
    press(host, /add a fact/i);
    press(host, /^save fact/i);
    await vi.waitFor(() => {
      expect(host.querySelector("[data-field-error=start]")?.textContent).toContain("is in the future");
    });
    expect(host.querySelector("textarea[name=claim]")).not.toBeNull();
  });

  it("warns that editing unverifies, and shows the fact unverified after the save", async () => {
    const host = await open([verifiedFact]);
    press(host, /^edit/i);
    expect(host.textContent).toContain("it becomes unverified");
    type(host.querySelector<HTMLTextAreaElement>("textarea[name=claim]"), "Ran the weekly batch.");
    press(host, /^save fact/i);
    await vi.waitFor(() => {
      expect(host.querySelector("li.fact")?.textContent).toContain("Unverified");
    });
    expect(host.querySelector("li.fact")?.textContent).toContain("Ran the weekly batch.");
  });

  it("asks before deleting and sends nothing until confirmed", async () => {
    const host = await open([fact()]);
    press(host, /^delete/i);
    expect(writes()).toEqual([]);
    press(host, /cancel/i);
    expect(host.querySelector("li.fact")).not.toBeNull();
    press(host, /^delete/i);
    press(host, /confirm delete/i);
    await vi.waitFor(() => {
      expect(host.querySelector("li.fact")).toBeNull();
    });
    expect(writes().map((w) => w.method)).toEqual(["DELETE"]);
  });

  it("renders hostile text as text and never as markup", async () => {
    const hostile = '<script>window.__x = 1</script><img src=x onerror="window.__x = 2">';
    const host = await open([fact({ claim: hostile, tags: [{ name: hostile, level: "expert" }] })]);
    expect(host.querySelector("img, script")).toBeNull();
    expect(host.textContent).toContain(hostile);
  });

  it("says there is no bank yet when the file does not exist, and still offers to add a fact", async () => {
    server = await startServer(() => ({ status: 404, body: { error: { code: "bank_not_found", message: "The fact bank file was not found." } } }));
    const host = freshHost();
    mounted = mount(FactBank, { target: host, props: { client: new ApiClient(server.url) } });
    await vi.waitFor(() => {
      expect(host.textContent).toContain("No fact bank yet");
    });
    expect([...host.querySelectorAll("button")].some((b) => /add a fact/i.test(b.textContent))).toBe(true);
  });

  it("filters by state without asking the API again", async () => {
    const host = await open([fact(), verifiedFact]);
    const before = server?.seen.length ?? 0;
    const filter = host.querySelector<HTMLSelectElement>("select[name=filter]");
    if (!filter) throw new Error("no filter");
    filter.value = "unverified";
    filter.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => {
      expect(host.querySelectorAll("li.fact").length).toBe(1);
    });
    expect(host.querySelector("li.fact")?.textContent).toContain("F-0001");
    expect(server?.seen.length).toBe(before);
  });

  it("states that the bank is local and which facts a model may see", async () => {
    const host = await open([fact()]);
    expect(host.textContent).toContain("stays on this computer");
    expect(host.textContent).toContain("Only verified facts");
  });

  it("filters by tag and by whether a model may see the fact", async () => {
    const host = await open([fact(), fact({ id: "F-0003", claim: "Wrote SQL.", tags: [{ name: "sql", level: "expert" }], share: "shareable" })]);
    type(host.querySelector<HTMLInputElement>("input[name=tagfilter]"), "sql");
    expect(host.querySelectorAll("li.fact").length).toBe(1);
    type(host.querySelector<HTMLInputElement>("input[name=tagfilter]"), "");
    for (const [value, id] of [["shareable", "F-0003"], ["local_only", "F-0001"], ["verified", ""]] as const) {
      const filter = host.querySelector<HTMLSelectElement>("select[name=filter]");
      if (!filter) throw new Error("no filter");
      filter.value = value;
      filter.dispatchEvent(new Event("change", { bubbles: true }));
      flushSync();
      expect(host.querySelector("li.fact")?.textContent ?? "").toContain(id);
    }
  });

  it("removes a verification only when its own button is pressed", async () => {
    const host = await open([verifiedFact]);
    press(host, /remove verification/i);
    await vi.waitFor(() => {
      expect(host.querySelector("li.fact")?.textContent).toContain("Unverified");
    });
    expect(writes().map((w) => w.url)).toEqual(["/api/facts/F-0002/unverify"]);
  });

  it("adds and removes tag rows in the form and shows an error next to the tag", async () => {
    const host = await open([], (seen) =>
      seen.method === "POST" && seen.url === "/api/facts"
        ? { status: 422, body: { error: { code: "invalid_request", message: "The request is invalid.", details: [{ field: "tags.0.name", problem: "tag name is empty after normalization" }] } } }
        : undefined,
    );
    press(host, /add a fact/i);
    press(host, /add a tag/i);
    press(host, /add a tag/i);
    expect(host.querySelectorAll("fieldset select").length).toBe(2);
    press(host, /remove tag/i);
    expect(host.querySelectorAll("fieldset select").length).toBe(1);
    press(host, /^save fact/i);
    await vi.waitFor(() => {
      expect(host.querySelector("[data-field-error='tags.0']")?.textContent).toContain("empty");
    });
  });

  it("closes the form on Cancel without sending anything", async () => {
    const host = await open([fact()]);
    press(host, /^edit/i);
    press(host, /^cancel/i);
    expect(host.querySelector("form")).toBeNull();
    expect(writes()).toEqual([]);
  });

  it("shows a banner when the API refuses an action", async () => {
    const host = await open([fact()], (seen) =>
      seen.url.endsWith("/verify")
        ? { status: 404, body: { error: { code: "not_found", message: "Not found." } } }
        : undefined,
    );
    press(host, /^verify/i);
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("not_found");
    });
  });

  it("shows a general error when a save fails without a field", async () => {
    const host = await open([], (seen) =>
      seen.method === "POST" && seen.url === "/api/facts"
        ? { status: 422, body: { error: { code: "bank_invalid", message: "The fact bank is not valid." } } }
        : undefined,
    );
    press(host, /add a fact/i);
    press(host, /^save fact/i);
    await vi.waitFor(() => {
      expect(host.querySelector("form [role=alert]")?.textContent).toContain("bank_invalid");
    });
  });

  it("shows the role, employer, issuer and dates of a fact when it has them", async () => {
    const host = await open([
      fact({ role: "Developer", employer: "Gravy Boat Labs", issuer: "State University", start: "2020-01-01", end: "2021-01-01" }),
    ]);
    const text = host.querySelector("li.fact")?.textContent ?? "";
    expect(text).toContain("Developer, Gravy Boat Labs, State University");
    expect(text).toContain("2020-01-01 to 2021-01-01");
  });

  it("opens the edit form filled with the fact, tags and evidence included", async () => {
    const host = await open([fact({ employer: "Gravy Boat Labs", start: "2020-01-01" })]);
    press(host, /^edit/i);
    expect(host.querySelector<HTMLInputElement>("input[name=employer]")?.value).toBe("Gravy Boat Labs");
    expect(host.querySelector<HTMLInputElement>("input[name=start]")?.value).toBe("2020-01-01");
    expect(host.querySelector<HTMLInputElement>("input[name=pointer]")?.value).toBe("my notes");
    expect(host.querySelectorAll("fieldset select").length).toBe(1);
  });

  it("says the bank is empty when the file exists with no facts", async () => {
    const host = await open([]);
    expect(host.textContent).toContain("The bank is empty");
  });

  it("shows the typed error when the bank cannot be loaded", async () => {
    server = await startServer(() => ({ status: 422, body: { error: { code: "bank_invalid", message: "The fact bank is not valid." } } }));
    const host = freshHost();
    mounted = mount(FactBank, { target: host, props: { client: new ApiClient(server.url) } });
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("bank_invalid");
    });
  });

  it("shows an unreachable error when the API does not answer", async () => {
    const host = freshHost();
    mounted = mount(FactBank, { target: host, props: { client: new ApiClient("http://127.0.0.1:9") } });
    await vi.waitFor(() => {
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("unreachable");
    });
  });
});
