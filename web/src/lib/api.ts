// ABOUTME: The typed client for the local API. It reads the CSRF token once and sends it on writes.
// ABOUTME: Every failure becomes an ApiError with a stable code, and no answer is trusted as markup.
import type {
  AnalyzeResponse,
  EstimateResponse,
  PostingResponse,
  ProvidersResponse,
  ReportResponse,
  SessionResponse,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: readonly { field: string; problem: string }[];

  constructor(
    status: number,
    code: string,
    message: string,
    details: readonly { field: string; problem: string }[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Turn an error answer into an ApiError. The fixed message is shown, never raw markup. */
function toApiError(status: number, body: unknown): ApiError {
  if (isRecord(body) && isRecord(body["error"])) {
    const error = body["error"];
    const code = typeof error["code"] === "string" ? error["code"] : "http_error";
    const message = typeof error["message"] === "string" ? error["message"] : "The request failed.";
    const raw = Array.isArray(error["details"]) ? (error["details"] as unknown[]) : [];
    const details = raw.filter(isRecord).map((item) => ({
      field: text(item["field"]),
      problem: text(item["problem"]),
    }));
    return new ApiError(status, code, message, details);
  }
  return new ApiError(status, "http_error", "The request failed.");
}

export class ApiClient {
  private token: string | null = null;

  constructor(private readonly baseUrl = "") {}

  private async sessionToken(refresh = false): Promise<string> {
    if (this.token === null || refresh) {
      const session = await this.send<SessionResponse>("GET", "/api/session", undefined, false);
      this.token = session.csrf_token;
    }
    return this.token;
  }

  private async send<T>(
    method: string,
    path: string,
    body: BodyInit | undefined,
    withToken: boolean,
    contentType = "application/json",
    token?: string,
  ): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = contentType;
    if (withToken) headers["X-CSRF-Token"] = token ?? (await this.sessionToken());
    let response: Response;
    try {
      const init: RequestInit = { method, headers };
      if (body !== undefined) init.body = body;
      response = await fetch(this.baseUrl + path, init);
    } catch {
      throw new ApiError(0, "unreachable", "The API did not answer. Is it running on port 5309?");
    }
    const parsed = (await response.json().catch(() => null)) as unknown;
    if (!response.ok) throw toApiError(response.status, parsed);
    return parsed as T;
  }

  /** A read needs no token. A write sends it, and asks for a new one if the server restarted. */
  private async call<T>(
    method: string,
    path: string,
    body?: BodyInit,
    contentType?: string,
  ): Promise<T> {
    if (!WRITE_METHODS.has(method)) return this.send<T>(method, path, undefined, false);
    try {
      return await this.send<T>(method, path, body, true, contentType);
    } catch (error) {
      if (error instanceof ApiError && error.code === "csrf_token_invalid") {
        const fresh = await this.sessionToken(true);
        return this.send<T>(method, path, body, true, contentType, fresh);
      }
      throw error;
    }
  }

  providers(): Promise<ProvidersResponse> {
    return this.call("GET", "/api/providers");
  }

  addPastedPosting(text: string): Promise<PostingResponse> {
    return this.call("POST", "/api/postings", JSON.stringify({ source: "paste", text }));
  }

  addLinkedPosting(url: string): Promise<PostingResponse> {
    return this.call("POST", "/api/postings", JSON.stringify({ source: "link", url }));
  }

  addPdfPosting(pdf: ArrayBuffer): Promise<PostingResponse> {
    return this.call("POST", "/api/postings", pdf, "application/pdf");
  }

  estimate(postingId: string): Promise<EstimateResponse> {
    return this.call("GET", `/api/postings/${encodeURIComponent(postingId)}/estimate`);
  }

  analyze(postingId: string, backend: string, confirmHosted: boolean): Promise<AnalyzeResponse> {
    const body = JSON.stringify({ backend, confirm_hosted: confirmHosted });
    return this.call("POST", `/api/postings/${encodeURIComponent(postingId)}/analyze`, body);
  }

  report(reportId: string): Promise<ReportResponse> {
    return this.call("GET", `/api/reports/${encodeURIComponent(reportId)}`);
  }
}

export const api = new ApiClient();
