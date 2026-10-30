<!-- ABOUTME: The Analyze screen: paste, link or PDF input, a backend picker, a run button, then the report. -->
<!-- ABOUTME: Nothing is sent until the person presses the button, and a hosted backend needs a tick. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type ApiClient } from "../lib/api";
  import type { GapReport as Report, PostingResponse, ProviderInfo } from "../lib/types";
  import GapReport from "./GapReport.svelte";

  let { client = api }: { client?: ApiClient } = $props();

  type Mode = "paste" | "link" | "pdf";

  let mode = $state<Mode>("paste");
  let text = $state("");
  let url = $state("");
  let pdf = $state<File | null>(null);
  let providers = $state<ProviderInfo[]>([]);
  let backend = $state("");
  let confirmHosted = $state(false);
  let running = $state(false);
  let error = $state<ApiError | null>(null);
  let posting = $state<PostingResponse | null>(null);
  let result = $state<{ id: string; report: Report } | null>(null);

  const selected = $derived(providers.find((p) => p.provider === backend));
  const hosted = $derived(selected !== undefined && !selected.local);
  const canRun = $derived(!running && selected !== undefined && (!hosted || confirmHosted));

  function asError(failure: unknown): ApiError {
    return failure instanceof ApiError
      ? failure
      : new ApiError(0, "unreachable", "The API did not answer. Is it running on port 5309?");
  }

  onMount(() => {
    client.providers().then(
      (answer) => {
        providers = answer.providers;
        backend = answer.providers[0]?.provider ?? "";
      },
      (failure: unknown) => {
        error = asError(failure);
      },
    );
  });

  function chosenPdf(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    pdf = input.files?.[0] ?? null;
  }

  async function addPosting(): Promise<PostingResponse> {
    if (mode === "link") return client.addLinkedPosting(url);
    if (mode === "pdf") {
      if (!pdf) throw new ApiError(0, "no_pdf", "Choose a PDF file first.");
      return client.addPdfPosting(await pdf.arrayBuffer());
    }
    return client.addPastedPosting(text);
  }

  async function run(event: Event): Promise<void> {
    event.preventDefault();
    running = true;
    error = null;
    posting = null;
    result = null;
    try {
      posting = await addPosting();
      const answer = await client.analyze(posting.id, backend, confirmHosted);
      result = { id: answer.report_id, report: answer.report };
    } catch (failure) {
      error = asError(failure);
    } finally {
      running = false;
    }
  }
</script>

<section aria-label="Analyze a posting">
  <h2>Analyze a posting</h2>
  <p class="muted">
    Paste a posting, give a link or choose a PDF. Nothing is sent anywhere until you press Analyze,
    and the tool never applies, copies or sends anything for you.
  </p>

  {#if error}
    <div role="alert" class="banner error">
      {error.code}: {error.message}
      {#if error.details.length > 0}
        <ul>
          {#each error.details as detail, index (index)}
            <li>{detail.field}: {detail.problem}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <form onsubmit={run}>
    <fieldset>
      <legend>Where is the posting?</legend>
      <label><input type="radio" name="mode" value="paste" bind:group={mode} /> Paste text</label>
      <label><input type="radio" name="mode" value="link" bind:group={mode} /> Link</label>
      <label><input type="radio" name="mode" value="pdf" bind:group={mode} /> PDF</label>
    </fieldset>

    {#if mode === "paste"}
      <label for="posting-text">Posting text</label>
      <textarea id="posting-text" aria-label="Posting text" bind:value={text}></textarea>
    {:else if mode === "link"}
      <label for="posting-link">Posting link</label>
      <input id="posting-link" aria-label="Posting link" type="url" bind:value={url} />
    {:else}
      <label for="posting-pdf">Posting PDF</label>
      <input id="posting-pdf" aria-label="Posting PDF" type="file" accept="application/pdf" onchange={chosenPdf} />
    {/if}

    <label for="backend">Backend</label>
    <select id="backend" aria-label="Backend" bind:value={backend}>
      {#each providers as provider (provider.provider)}
        <option value={provider.provider}>
          {provider.provider} / {provider.model} ({provider.local ? "runs on this computer" : "hosted"})
        </option>
      {/each}
    </select>
    {#if providers.length === 0}
      <p class="muted">
        No backend is configured. Set CYPRESS_CREEK_PROVIDER and CYPRESS_CREEK_MODEL (see docs/setup.md)
        and restart the API.
      </p>
    {/if}

    {#if hosted}
      <label>
        <input type="checkbox" bind:checked={confirmHosted} />
        I understand this sends the posting text and my shareable facts to a hosted service.
      </label>
    {/if}

    <p><button type="submit" disabled={!canRun}>{running ? "Analyzing..." : "Analyze"}</button></p>
  </form>

  {#if posting}
    {@const warnings = [
      ...posting.warnings.map((w) => `${w.kind} (${String(w.count)})`),
      ...posting.extraction_warnings.map((w) => `${w.kind} (${String(w.count)})`),
      ...posting.fetch_warnings,
    ]}
    {#if warnings.length > 0}
      <section data-testid="posting-warnings" aria-label="Posting warnings" class="banner warn">
        <h3>About this posting</h3>
        <ul>
          {#each warnings as warning, index (index)}
            <li>{warning}</li>
          {/each}
        </ul>
      </section>
    {/if}
    <details>
      <summary>The posting as the tool read it</summary>
      <pre data-testid="posting-preview">{posting.text}</pre>
    </details>
  {/if}

  {#if result}
    <p><a href={"#/report/" + result.id}>Link to this report</a></p>
    <GapReport report={result.report} />
  {/if}
</section>
