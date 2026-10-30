// ABOUTME: Helpers for the unit and component tests: a report builder and a small real HTTP server.
// ABOUTME: The server plays hand written answers over real HTTP, so no fetch call is mocked.
import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import type { GapReport, ReportRow, ScoreResult } from "./lib/types";

export function makeRow(overrides: Partial<ReportRow> = {}): ReportRow {
  return {
    requirement_id: "R-1",
    text: "Needs Python.",
    importance: "required",
    ceiling: "strong",
    support: "strong",
    gate: "term_match",
    fact_ids: ["F-0001"],
    rationale: null,
    entailment: "confirmed",
    not_model_checked: false,
    failure: null,
    span: null,
    raise_attempted: false,
    ...overrides,
  };
}

export function makeScore(overrides: Partial<ScoreResult> = {}): ScoreResult {
  return {
    score: 62.5,
    supported: 1,
    total: 2,
    counts: { strong: 1, partial: 0, none: 1 },
    inputs: {
      weights: { required: 3, unspecified: 2, preferred: 1, strong: 1, partial: 0.5, none: 0 },
      lines: [],
    },
    ...overrides,
  };
}

export function makeReport(overrides: Partial<GapReport> = {}): GapReport {
  return {
    posting_id: "post-1",
    status: "complete",
    incomplete_reasons: [],
    rows: [],
    gaps: [],
    not_assessed_count: 0,
    not_assessed: [],
    dropped: [],
    warnings: [],
    score: makeScore(),
    score_disclaimer: "triage only, not a probability",
    rule_only_ids: [],
    provenance: {
      backend: "ollama",
      model: "m",
      run_id: "run-1",
      prompt_hashes: {},
      usage: { input_tokens: 0, output_tokens: 0 },
    },
    ...overrides,
  };
}

/** A fresh empty element in the page for a component to mount into. */
export function freshHost(): HTMLElement {
  document.body.replaceChildren();
  const host = document.createElement("div");
  document.body.append(host);
  return host;
}

export interface Seen {
  method: string;
  url: string;
  headers: IncomingMessage["headers"];
  body: string;
}

export interface Reply {
  status?: number;
  body: unknown;
}

export type Handler = (seen: Seen) => Reply;

export interface TestServer {
  url: string;
  seen: Seen[];
  close: () => Promise<void>;
}

/** A real HTTP server on a free loopback port that answers with the handler's hand written reply. */
export async function startServer(handler: Handler): Promise<TestServer> {
  const seen: Seen[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const entry: Seen = {
        method: request.method ?? "",
        url: request.url ?? "",
        headers: request.headers,
        body: Buffer.concat(chunks).toString("utf-8"),
      };
      seen.push(entry);
      const reply = handler(entry);
      response.writeHead(reply.status ?? 200, { "Content-Type": "application/json" });
      response.end(typeof reply.body === "string" ? reply.body : JSON.stringify(reply.body));
    });
  });
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${String(port)}`,
    seen,
    close: () =>
      new Promise<void>((done) => {
        server.close(() => {
          done();
        });
      }),
  };
}
