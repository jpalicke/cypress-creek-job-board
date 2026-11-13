<!-- ABOUTME: The resume import screen: run an import, then approve or reject each proposed fact. -->
<!-- ABOUTME: Nothing is sent until the button is pressed, and each candidate is decided one by one. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type ApiClient } from "../lib/api";
  import type { CandidateOut, ImportResponse, ProviderInfo } from "../lib/types";

  let { client = api }: { client?: ApiClient } = $props();

  let mode = $state<"paste" | "pdf">("paste");
  let text = $state("");
  let pdf = $state<File | null>(null);
  let providers = $state<ProviderInfo[]>([]);
  let confirmHosted = $state(false);
  let running = $state(false);
  let error = $state<ApiError | null>(null);
  let result = $state<ImportResponse | null>(null);
  let pending = $state<CandidateOut[]>([]);
  // What happened to each candidate in this session: the fact id when approved, or "rejected".
  let decided = $state<Record<string, string>>({});

  const backend = $derived(providers[0]);
  const hosted = $derived(backend !== undefined && !backend.local);
  const hasInput = $derived(mode === "paste" ? text.trim() !== "" : pdf !== null);
  const canRun = $derived(!running && backend !== undefined && hasInput && (!hosted || confirmHosted));

  function asError(problem: unknown): ApiError {
    return problem instanceof ApiError
      ? problem
      : new ApiError(0, "unreachable", "The API did not answer. Is it running on port 5309?");
  }

  onMount(() => {
    client.providers().then(
      (answer) => {
        providers = answer.providers;
      },
      (problem: unknown) => {
        error = asError(problem);
      },
    );
    client.importCandidates().then(
      (answer) => {
        pending = answer.candidates;
      },
      () => undefined,
    );
  });

  function chosenPdf(event: Event): void {
    pdf = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
  }

  async function run(event: Event): Promise<void> {
    event.preventDefault();
    if (!backend) return;
    running = true;
    error = null;
    result = null;
    try {
      result =
        mode === "pdf" && pdf
          ? await client.importResumePdf(await pdf.arrayBuffer(), backend.provider, confirmHosted)
          : await client.importResume(text, backend.provider, confirmHosted);
      pending = (await client.importCandidates()).candidates;
    } catch (problem) {
      error = asError(problem);
    } finally {
      running = false;
    }
  }

  async function approve(candidate: CandidateOut): Promise<void> {
    error = null;
    try {
      const answer = await client.approveCandidate(candidate.id);
      decided[candidate.id] = answer.fact.id;
    } catch (problem) {
      error = asError(problem);
    }
  }

  async function reject(candidate: CandidateOut): Promise<void> {
    error = null;
    try {
      await client.rejectCandidate(candidate.id);
      decided[candidate.id] = "rejected";
    } catch (problem) {
      error = asError(problem);
    }
  }
</script>

<section aria-label="Start from a resume">
  <h2>Start from a resume</h2>
  <p class="muted">
    Paste your resume or choose a PDF. A model proposes facts, and each proposal shows the words of
    the resume it came from. Nothing is sent until you press the button, nothing is approved for
    you, and approved facts arrive in your fact bank unverified and local only: you verify them
    yourself on the <a href="#/facts">Fact bank</a> screen.
  </p>

  {#if error}
    <p role="alert" class="banner error">{error.code}: {error.message}</p>
  {/if}

  <form onsubmit={run}>
    <fieldset>
      <legend>Where is the resume?</legend>
      <label><input type="radio" name="mode" value="paste" bind:group={mode} /> Paste text</label>
      <label><input type="radio" name="mode" value="pdf" bind:group={mode} /> PDF</label>
    </fieldset>
    {#if mode === "paste"}
      <label for="resume-text">Resume text</label>
      <textarea id="resume-text" aria-label="Resume text" bind:value={text}></textarea>
    {:else}
      <label for="resume-pdf">Resume PDF</label>
      <input id="resume-pdf" type="file" accept="application/pdf" onchange={chosenPdf} />
    {/if}
    {#if backend}
      <p class="muted">
        Backend: {backend.provider} / {backend.model}
        {backend.local ? "(runs on this computer)" : "(hosted: not on this computer)"}.
        What is sent: the text of the resume{mode === "paste" ? ` (${String(text.length)} characters)` : " read from the PDF"}
        and nothing else.
      </p>
    {/if}
    {#if hosted}
      <label>
        <input type="checkbox" bind:checked={confirmHosted} />
        I confirm my resume text is sent to the hosted backend {backend?.provider}.
      </label>
    {/if}
    <button type="submit" disabled={!canRun}>{running ? "Reading..." : "Find facts in this resume"}</button>
  </form>

  {#if result}
    <section aria-label="Import result" data-testid="result">
      {#if result.status === "not_run"}
        <p class="banner warn">The import did not run{result.failure ? `: ${result.failure}` : ""}.</p>
      {/if}
      {#if result.extraction_warnings.length > 0}
        <p class="banner warn">
          Text removed from the PDF before reading:
          {#each result.extraction_warnings as warning (warning.kind)}
            <span class="tag">{warning.kind} ({warning.count})</span>
          {/each}
        </p>
      {/if}
      {#if Object.keys(result.dropped).length > 0}
        <p class="muted" data-testid="dropped">
          Proposals dropped because the resume did not support them:
          {#each Object.entries(result.dropped) as [reason, count] (reason)}
            <span class="tag">{reason} ({count})</span>
          {/each}
        </p>
      {/if}
    </section>
  {/if}

  {#if pending.length > 0}
    <h3>Proposed facts ({pending.length})</h3>
    <ul class="facts">
      {#each pending as candidate (candidate.id)}
        <li class="candidate">
          <p>{candidate.claim}</p>
          <p class="muted">Kind: {candidate.kind}{candidate.tags.length > 0 ? `. Skills: ${candidate.tags.join(", ")}` : ""}</p>
          <blockquote class="muted">From the resume: {candidate.source}</blockquote>
          {#if decided[candidate.id] === "rejected"}
            <p><strong>Rejected.</strong></p>
          {:else if decided[candidate.id]}
            <p>
              <strong>Approved as {decided[candidate.id]}</strong>, unverified and local only. Verify it
              on the <a href="#/facts">Fact bank</a> screen.
            </p>
          {:else}
            <button type="button" onclick={() => approve(candidate)}>Approve this fact</button>
            <button type="button" onclick={() => reject(candidate)}>Reject</button>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if result?.status === "done"}
    <p class="muted">No facts were proposed from this resume.</p>
  {/if}
</section>
