<!-- ABOUTME: The app shell: a header and a hash router: Analyze, a stored report and the fact bank. -->
<!-- ABOUTME: Business logic stays in the API; this file only picks which screen to show. -->
<script lang="ts">
  import { onMount } from "svelte";
  import Analyze from "./routes/Analyze.svelte";
  import FactBank from "./routes/FactBank.svelte";
  import ResumeImport from "./routes/ResumeImport.svelte";
  import ReportPage from "./routes/ReportPage.svelte";

  const REPORT_ROUTE = /^#\/report\/([A-Za-z0-9_-]+)$/;

  let hash = $state(window.location.hash);

  onMount(() => {
    const update = (): void => {
      hash = window.location.hash;
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  });

  const reportId = $derived(REPORT_ROUTE.exec(hash)?.[1] ?? null);
</script>

<header>
  <h1>Cypress Creek</h1>
  <nav aria-label="Main">
    <a href="#/">Analyze</a>
    <a href="#/facts">Fact bank</a>
    <a href="#/import">Start from a resume</a>
  </nav>
</header>

<main>
  {#if hash === "#/facts"}
    <FactBank />
  {:else if hash === "#/import"}
    <ResumeImport />
  {:else if reportId}
    {#key reportId}
      <ReportPage {reportId} />
    {/key}
  {:else}
    <Analyze />
  {/if}
</main>
