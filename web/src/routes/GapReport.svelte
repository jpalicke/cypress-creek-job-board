<!-- ABOUTME: The gap report screen: requirements by support, the score with its disclaimer, warnings. -->
<!-- ABOUTME: Every value is shown with text interpolation, which escapes, so hostile text stays text. -->
<script lang="ts">
  import { groupBySupport, isIncomplete, scoreLine, SUPPORT_ORDER, SUPPORT_TITLES } from "../lib/grouping";
  import type { GapReport } from "../lib/types";

  let { report }: { report: GapReport } = $props();

  const groups = $derived(groupBySupport(report.rows));
  const incomplete = $derived(isIncomplete(report));
  const line = $derived(scoreLine(report));
</script>

<article class="report" aria-label="Gap report">
  <h2>Gap report</h2>

  {#if report.warnings.length > 0}
    <section data-testid="warnings" aria-label="Warnings" class="banner warn">
      <h3>Warnings</h3>
      <ul>
        {#each report.warnings as warning (warning.kind)}
          <li>{warning.kind} ({warning.count})</li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if incomplete}
    <div role="alert" class="banner error">
      <strong>Incomplete.</strong> The analysis did not finish, so there is no score.
      <ul>
        {#each report.incomplete_reasons as reason (reason)}
          <li>{reason}</li>
        {/each}
      </ul>
    </div>
  {:else}
    <section data-testid="score" aria-label="Score" class="banner ok">
      {#if line !== null && report.score !== null}
        <p>
          <strong>Score: {line}</strong> ({report.score_disclaimer}).
          {`Supported ${String(report.score.supported)} of ${String(report.score.total)}.`}
        </p>
      {:else}
        <p><strong>No score</strong>, there were no requirements to score ({report.score_disclaimer}).</p>
      {/if}
    </section>
  {/if}

  {#if report.rows.length === 0}
    <p class="muted">No requirements were found in this posting.</p>
  {:else}
    {#each SUPPORT_ORDER as support (support)}
      <section aria-label={SUPPORT_TITLES[support]}>
        <h3>{SUPPORT_TITLES[support]} ({groups[support].length})</h3>
        {#each groups[support] as row (row.requirement_id)}
          <div class="row">
            <p>
              <strong>{row.requirement_id}</strong>
              <span class="tag">{row.importance}</span>
              {#if row.not_model_checked}<span class="tag">not model checked</span>{/if}
              <br />
              {row.text}
            </p>
            <p class="muted">
              {#if row.fact_ids.length > 0}Facts: {row.fact_ids.join(", ")}{:else}no verified fact cited{/if}
            </p>
            {#if row.rationale}<p class="muted">Why: {row.rationale}</p>{/if}
            {#if row.failure}<p class="muted">Model check failed: {row.failure}</p>{/if}
          </div>
        {/each}
      </section>
    {/each}
  {/if}

  {#if report.not_assessed.length > 0}
    <section data-testid="not-assessed" aria-label="Not assessed">
      <h3>Not assessed ({report.not_assessed.length})</h3>
      <p class="muted">
        These sentences look like requirements but extraction did not cover them. The score does not
        include them.
      </p>
      <ul>
        {#each report.not_assessed as sentence (sentence.span.join("-"))}
          <li>{sentence.text}</li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if report.dropped.length > 0}
    <section data-testid="dropped" aria-label="Dropped proposals">
      <h3>Proposals dropped ({report.dropped.length})</h3>
      <ul>
        {#each report.dropped as item, index (index)}
          <li>{item.text} ({item.reason})</li>
        {/each}
      </ul>
    </section>
  {/if}

  <footer class="muted">
    Made by {report.provenance.backend} {report.provenance.model}, run {report.provenance.run_id}.
    Triage only: read the facts yourself.
  </footer>
</article>
