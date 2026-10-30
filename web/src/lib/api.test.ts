// ABOUTME: Tests the API client against a real local HTTP server that plays hand written answers.
// ABOUTME: Checks the CSRF token flow, the typed errors and that no answer is trusted as markup.
import { afterEach, describe, expect, it } from "vitest";
import { ApiClient, ApiError } from "./api";
import { startServer, type Handler, type TestServer } from "../test-support";

let server: TestServer | undefined;

async function clientFor(handler: Handler): Promise<ApiClient> {
  server = await startServer(handler);
  return new ApiClient(server.url);
}

afterEach(async () => {
  await server?.close();
  server = undefined;
});

const session = { body: { csrf_token: "token-1" } };

describe("ApiClient", () => {
  it("reads reads without a token", async () => {
    const client = await clientFor(() => ({ body: { providers: [] } }));
    expect(await client.providers()).toEqual({ providers: [] });
    expect(server?.seen[0]?.headers["x-csrf-token"]).toBeUndefined();
    expect(server?.seen).toHaveLength(1);
  });

  it("gets the session token once and sends it on every write", async () => {
    const client = await clientFor((seen) =>
      seen.url === "/api/session" ? session : { body: { id: "post-1" } },
    );
    await client.addPastedPosting("Needs Python.");
    await client.addLinkedPosting("https://example.com/job");
    const writes = server?.seen.filter((s) => s.method === "POST") ?? [];
    expect(writes.map((w) => w.headers["x-csrf-token"])).toEqual(["token-1", "token-1"]);
    expect(server?.seen.filter((s) => s.url === "/api/session")).toHaveLength(1);
  });

  it("posts a paste, a link, a pdf and an analyze request in the documented shapes", async () => {
    const client = await clientFor((seen) =>
      seen.url === "/api/session" ? session : { body: { id: "post-1" } },
    );
    await client.addPastedPosting("Needs Python.");
    await client.addLinkedPosting("https://example.com/job");
    await client.addPdfPosting(new TextEncoder().encode("%PDF-1.4").buffer);
    await client.analyze("post 1", "ollama", true);
    const posts = server?.seen.filter((s) => s.method === "POST") ?? [];
    expect(JSON.parse(posts[0]?.body ?? "")).toEqual({ source: "paste", text: "Needs Python." });
    expect(JSON.parse(posts[1]?.body ?? "")).toEqual({
      source: "link",
      url: "https://example.com/job",
    });
    expect(posts[2]?.headers["content-type"]).toBe("application/pdf");
    expect(posts[2]?.body).toBe("%PDF-1.4");
    expect(posts[3]?.url).toBe("/api/postings/post%201/analyze");
    expect(JSON.parse(posts[3]?.body ?? "")).toEqual({ backend: "ollama", confirm_hosted: true });
  });

  it("asks for a new token once when the server says the token is wrong", async () => {
    let tokens = 0;
    const client = await clientFor((seen) => {
      if (seen.url === "/api/session") return { body: { csrf_token: `token-${String(++tokens)}` } };
      if (seen.headers["x-csrf-token"] === "token-1") {
        return {
          status: 403,
          body: { error: { code: "csrf_token_invalid", message: "Missing or invalid CSRF token." } },
        };
      }
      return { body: { id: "post-1" } };
    });
    expect(await client.addPastedPosting("x")).toEqual({ id: "post-1" });
    expect(tokens).toBe(2);
  });

  it("does not retry a second token failure forever", async () => {
    const client = await clientFor((seen) =>
      seen.url === "/api/session"
        ? session
        : {
            status: 403,
            body: { error: { code: "csrf_token_invalid", message: "Missing or invalid CSRF token." } },
          },
    );
    await expect(client.addPastedPosting("x")).rejects.toMatchObject({ code: "csrf_token_invalid" });
    expect(server?.seen.filter((s) => s.method === "POST")).toHaveLength(2);
  });

  it("turns a typed error answer into an ApiError with its fixed message and details", async () => {
    const client = await clientFor(() => ({
      status: 422,
      body: {
        error: {
          code: "invalid_request",
          message: "The request is invalid.",
          details: [{ field: "body.text", problem: "Field required" }, "junk"],
        },
      },
    }));
    const error = await client.estimate("post-1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "invalid_request",
      message: "The request is invalid.",
      details: [{ field: "body.text", problem: "Field required" }],
    });
  });

  it("copes with an error answer that is not the typed shape", async () => {
    const client = await clientFor(() => ({ status: 502, body: "<html>Bad gateway</html>" }));
    await expect(client.report("rep-1")).rejects.toMatchObject({
      status: 502,
      code: "http_error",
      message: "The request failed.",
    });
  });

  it("copes with an error body whose fields are the wrong type", async () => {
    const client = await clientFor(() => ({ status: 500, body: { error: { code: 5, message: 6 } } }));
    await expect(client.report("rep-1")).rejects.toMatchObject({
      code: "http_error",
      message: "The request failed.",
    });
  });

  it("reports an API that is not running as unreachable, with no raw network text", async () => {
    const client = new ApiClient("http://127.0.0.1:9");
    const error = await client.providers().catch((e: unknown) => e);
    expect(error).toMatchObject({ code: "unreachable", status: 0 });
    expect((error as ApiError).message).toContain("port 5309");
  });

  it("reads a stored report by id", async () => {
    const client = await clientFor(() => ({ body: { report_id: "rep-1" } }));
    await client.report("rep-1");
    expect(server?.seen[0]?.url).toBe("/api/reports/rep-1");
  });
});
