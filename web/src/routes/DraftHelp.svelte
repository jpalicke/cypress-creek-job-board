<!-- ABOUTME: Draft help for one requirement: bullets with cited facts, a review box and a gated Copy. -->
<!-- ABOUTME: Nothing is sent or copied alone; a bullet that failed a check can never be copied. -->
<script lang="ts">
  import { api, ApiError, type ApiClient } from "../lib/api";
  import type { ProviderInfo, ReportRow, SuggestionResponse } from "../lib/types";

  let {
    reportId,
    row,
    providers,
    client = api,
  }: { reportId: string; row: ReportRow; providers: ProviderInfo[]; client?: ApiClient } = $props();

  let confirmHosted = $state(false);
  let running = $state(false);
  let error = $state<ApiError | null>(null);
  let result = $state<SuggestionResponse | null>(null);
  // Review ticks live here only: they are not stored and start unticked for every draft.
  let reviewed = $state<Record<number, boolean>>({});
  let copied = $state<number | null>(null);

  const backend = $derived(providers[0]);
  const hosted = $derived(backend !== undefined && !backend.local);
  const canAsk = $derived(!running && backend !== undefined && (!hosted || confirmHosted));
  const supported = $derived(row.support !== "none" && row.fact_ids.length > 0);
  const claims = $derived(new Map((result?.facts ?? []).map((fact) => [fact.id, fact.claim])));

  async function ask(): Promise<void> {
    if (!backend) return;
    running = true;
    error = null;
    result = null;
    reviewed = {};
    copied = null;
    try {
      result = await client.suggestions(reportId, row.requirement_id, backend.provider, confirmHosted);
    } catch (failure) {
      error =
        failure instanceof ApiError
          ? failure
          : new ApiError(0, "unreachable", "The API did not answer. Is it running on port 5309?");
    } finally {
      running = false;
    }
  }

  async function copy(index: number, text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
    copied = index;
  }
</script>

<div class="draft" aria-label={`Draft help for ${row.requirement_id}`}>
  {#if !supported}
    <p class="muted">
      No verified fact supports this, so there is nothing to draft. You can add a fact to your bank
      if it is true.
    </p>
  {:else}
    {#if hosted}
      <label>
        <input type="checkbox" bind:checked={confirmHosted} />
        I confirm this requirement and the cited facts go to the hosted backend {backend?.provider}.
      </label>
    {/if}
    <button type="button" disabled={!canAsk} onclick={ask}>
      {running ? "Drafting..." : "Draft help"}
    </button>
  {/if}

  {#if error}
    <p role="alert" class="banner error">{error.code}: {error.message}</p>
  {/if}

  {#if result}
    {#if result.status === "no_support"}
      <p class="muted">No verified fact supports this, so nothing was drafted.</p>
    {:else if result.status === "not_run"}
      <p class="banner warn">Draft help did not run{result.failure ? `: ${result.failure}` : ""}.</p>
    {:else}
      <p class="muted">
        Draft help only rephrases your own verified facts. Read each bullet, tick that you have
        reviewed it, then copy it yourself. Nothing is sent or applied.
      </p>
      <ul class="bullets">
        {#each result.sentences as sentence, index (index)}
          <li class="bullet">
            <p>{sentence.text}</p>
            {#if !sentence.passed}
              <p class="banner warn">
                Failed a check, so it cannot be copied:
                {#each sentence.verdicts.filter((v) => !v.passed) as verdict, v (v)}
                  <span class="tag">{verdict.validator}: {verdict.reason}</span>
                {/each}
              </p>
            {/if}
            <p class="muted">
              Rests on:
              {#each sentence.fact_ids as id, f (f)}
                <span class="tag">{id}</span> {claims.get(id) ?? ""}
              {/each}
            </p>
            <label>
              <input type="checkbox" checked={reviewed[index] === true} onchange={(event) => {
                reviewed[index] = event.currentTarget.checked;
              }} />
              I have reviewed this bullet and it is true
            </label>
            <button
              type="button"
              disabled={!sentence.passed || reviewed[index] !== true}
              onclick={() => copy(index, sentence.text)}
            >
              Copy
            </button>
            {#if copied === index}<span class="muted" aria-live="polite">Copied.</span>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>
