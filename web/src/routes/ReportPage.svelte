<!-- ABOUTME: The page for one stored report: fetches it by id from the API and shows the gap report. -->
<!-- ABOUTME: A failure is shown as a typed error, never as a blank page. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type ApiClient } from "../lib/api";
  import type { ReportResponse } from "../lib/types";
  import GapReport from "./GapReport.svelte";

  let { reportId, client = api }: { reportId: string; client?: ApiClient } = $props();

  let stored = $state<ReportResponse | null>(null);
  let error = $state<ApiError | null>(null);

  onMount(() => {
    client.report(reportId).then(
      (answer) => {
        stored = answer;
      },
      (failure: unknown) => {
        error = failure instanceof ApiError ? failure : new ApiError(0, "unreachable", "The API did not answer.");
      },
    );
  });
</script>

{#if error}
  <p role="alert" class="banner error">{error.code}: {error.message}</p>
{:else if stored}
  <GapReport report={stored.report} />
{:else}
  <p class="muted" aria-live="polite">Loading the report...</p>
{/if}
