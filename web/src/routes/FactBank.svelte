<!-- ABOUTME: The fact bank screen: view, add, edit, share, verify and delete facts of the local bank. -->
<!-- ABOUTME: Verification is one button per fact; fact text is shown as text and no rule is copied here. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type ApiClient } from "../lib/api";
  import type { EvidenceType, Fact, FactDraft, Kind, Level, Tag } from "../lib/types";

  let { client = api }: { client?: ApiClient } = $props();

  const KINDS: Kind[] = ["employment", "project", "education", "certification", "achievement"];
  const LEVELS: Level[] = ["familiar", "working", "expert"];
  const EVIDENCE: EvidenceType[] = ["employer_doc", "repo", "certificate", "public_url", "self_attested"];

  let facts = $state<Fact[]>([]);
  let loaded = $state(false);
  let noBank = $state(false);
  let failure = $state<ApiError | null>(null);
  let filter = $state("all");
  let tagFilter = $state("");
  let editing = $state<string | null>(null);
  let confirming = $state<string | null>(null);
  let busy = $state(false);
  let saveError = $state<ApiError | null>(null);

  let form = $state(emptyForm());

  function emptyForm(): {
    claim: string;
    kind: Kind;
    employer: string;
    issuer: string;
    role: string;
    start: string;
    end: string;
    tags: Tag[];
    evidenceType: EvidenceType;
    pointer: string;
  } {
    return {
      claim: "",
      kind: "project",
      employer: "",
      issuer: "",
      role: "",
      start: "",
      end: "",
      tags: [],
      evidenceType: "self_attested",
      pointer: "",
    };
  }

  function asError(problem: unknown): ApiError {
    return problem instanceof ApiError
      ? problem
      : new ApiError(0, "unreachable", "The API did not answer. Is it running on port 5309?");
  }

  async function load(): Promise<void> {
    try {
      facts = (await client.facts()).facts;
      noBank = false;
    } catch (problem) {
      const error = asError(problem);
      if (error.code === "bank_not_found") {
        facts = [];
        noBank = true;
      } else {
        failure = error;
      }
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    void load();
  });

  const shown = $derived(
    facts.filter((fact) => {
      if (filter === "verified" && !fact.verified_on) return false;
      if (filter === "unverified" && fact.verified_on) return false;
      if (filter === "local_only" && fact.share !== "local_only") return false;
      if (filter === "shareable" && fact.share !== "shareable") return false;
      const wanted = tagFilter.trim().toLowerCase();
      return wanted === "" || fact.tags.some((tag) => tag.name.includes(wanted));
    }),
  );

  function replace(updated: Fact): void {
    facts = facts.map((fact) => (fact.id === updated.id ? updated : fact));
  }

  async function act(work: () => Promise<void>): Promise<void> {
    busy = true;
    failure = null;
    try {
      await work();
    } catch (problem) {
      failure = asError(problem);
    } finally {
      busy = false;
    }
  }

  function startAdd(): void {
    form = emptyForm();
    saveError = null;
    editing = "new";
  }

  function startEdit(fact: Fact): void {
    form = {
      claim: fact.claim,
      kind: fact.kind,
      employer: fact.employer ?? "",
      issuer: fact.issuer ?? "",
      role: fact.role ?? "",
      start: fact.start ?? "",
      end: fact.end ?? "",
      tags: fact.tags.map((tag) => ({ ...tag })),
      evidenceType: fact.evidence.type,
      pointer: fact.evidence.pointer,
    };
    saveError = null;
    editing = fact.id;
  }

  function draft(): FactDraft {
    const blank = (value: string): string | null => (value.trim() === "" ? null : value.trim());
    return {
      claim: form.claim,
      kind: form.kind,
      employer: blank(form.employer),
      issuer: blank(form.issuer),
      role: blank(form.role),
      start: blank(form.start),
      end: blank(form.end),
      tags: form.tags,
      evidence: { type: form.evidenceType, pointer: form.pointer },
    };
  }

  async function save(event: Event): Promise<void> {
    event.preventDefault();
    busy = true;
    saveError = null;
    try {
      if (editing === "new") {
        const created = await client.addFact(draft());
        facts = [...facts, created];
        noBank = false;
      } else if (editing !== null) {
        replace(await client.editFact(editing, draft()));
      }
      editing = null;
    } catch (problem) {
      saveError = asError(problem);
    } finally {
      busy = false;
    }
  }

  /** The API's problem text for one field, or the first one that starts with it (tags.0.level). */
  function problem(field: string): string | null {
    const found = saveError?.details.find((d) => d.field === field || d.field.startsWith(`${field}.`));
    return found ? found.problem : null;
  }

  const verify = (fact: Fact): Promise<void> => act(async () => { replace(await client.verifyFact(fact.id)); });
  const unverify = (fact: Fact): Promise<void> => act(async () => { replace(await client.unverifyFact(fact.id)); });
  const share = (fact: Fact): Promise<void> =>
    act(async () => {
      replace(await client.setFactShare(fact.id, fact.share === "shareable" ? "local_only" : "shareable"));
    });
  const remove = (fact: Fact): Promise<void> =>
    act(async () => {
      await client.deleteFact(fact.id);
      facts = facts.filter((other) => other.id !== fact.id);
      confirming = null;
    });
</script>

{#snippet field(name: string, label: string, content: import("svelte").Snippet)}
  <div class="field">
    <label for={`fact-${name}`}>{label}</label>
    {@render content()}
    {#if problem(name)}<span role="alert" class="error" data-field-error={name}>{problem(name)}</span>{/if}
  </div>
{/snippet}

<section aria-label="Fact bank" data-testid="bank">
  <h2>Fact bank</h2>
  <p class="muted">
    Your bank stays on this computer: nothing on this screen sends it anywhere. Only verified facts
    are ever used, and a model may see only a verified fact marked as shareable. Local only facts
    are never shown to a model. Verifying is something only you do, one fact at a time.
  </p>

  {#if failure}
    <p role="alert" class="banner error">{failure.code}: {failure.message}</p>
  {/if}

  {#if !loaded}
    <p class="muted" aria-live="polite">Loading the bank...</p>
  {:else}
    {#if noBank}
      <p class="banner warn">No fact bank yet. Adding your first fact creates the file.</p>
    {/if}

    <div class="toolbar">
      <label>
        Show
        <select name="filter" bind:value={filter}>
          <option value="all">All facts</option>
          <option value="verified">Verified</option>
          <option value="unverified">Unverified</option>
          <option value="local_only">Local only</option>
          <option value="shareable">May be shown to a model</option>
        </select>
      </label>
      <label>Tag <input type="text" name="tagfilter" bind:value={tagFilter} /></label>
      <button type="button" onclick={startAdd} disabled={busy || editing !== null}>Add a fact</button>
    </div>

    {#if editing !== null}
      <form onsubmit={save} aria-label={editing === "new" ? "Add a fact" : `Edit ${editing}`}>
        {#if editing !== "new"}
          <p class="banner warn">
            If you change what this fact says, it becomes unverified until you verify it again.
          </p>
        {/if}
        {#if saveError && saveError.details.length === 0}
          <p role="alert" class="banner error">{saveError.code}: {saveError.message}</p>
        {/if}
        {#snippet claimField()}<textarea id="fact-claim" name="claim" bind:value={form.claim}></textarea>{/snippet}
        {@render field("claim", "What is true", claimField)}
        {#snippet kindField()}
          <select id="fact-kind" name="kind" bind:value={form.kind}>
            {#each KINDS as kind (kind)}<option value={kind}>{kind}</option>{/each}
          </select>
        {/snippet}
        {@render field("kind", "Kind", kindField)}
        {#snippet employerField()}<input id="fact-employer" name="employer" bind:value={form.employer} />{/snippet}
        {@render field("employer", "Employer", employerField)}
        {#snippet issuerField()}<input id="fact-issuer" name="issuer" bind:value={form.issuer} />{/snippet}
        {@render field("issuer", "Issuer (school or certifying body)", issuerField)}
        {#snippet roleField()}<input id="fact-role" name="role" bind:value={form.role} />{/snippet}
        {@render field("role", "Role", roleField)}
        {#snippet startField()}<input id="fact-start" name="start" placeholder="YYYY-MM-DD" bind:value={form.start} />{/snippet}
        {@render field("start", "Start", startField)}
        {#snippet endField()}<input id="fact-end" name="end" placeholder="YYYY-MM-DD" bind:value={form.end} />{/snippet}
        {@render field("end", "End", endField)}

        <fieldset>
          <legend>Skills and levels</legend>
          {#each form.tags as tag, index (index)}
            <div class="field">
              <input aria-label={`Tag ${String(index + 1)} name`} bind:value={tag.name} />
              <select aria-label={`Tag ${String(index + 1)} level`} bind:value={tag.level}>
                {#each LEVELS as level (level)}<option value={level}>{level}</option>{/each}
              </select>
              <button type="button" onclick={() => { form.tags.splice(index, 1); }}>Remove tag</button>
              {#if problem(`tags.${String(index)}`)}
                <span role="alert" class="error" data-field-error={`tags.${String(index)}`}>{problem(`tags.${String(index)}`)}</span>
              {/if}
            </div>
          {/each}
          <button type="button" onclick={() => { form.tags.push({ name: "", level: "working" }); }}>Add a tag</button>
        </fieldset>

        {#snippet evidenceField()}
          <select id="fact-evidence" name="evidence_type" bind:value={form.evidenceType}>
            {#each EVIDENCE as type (type)}<option value={type}>{type}</option>{/each}
          </select>
          <input id="fact-pointer" name="pointer" aria-label="Where it can be checked" placeholder="where it can be checked" bind:value={form.pointer} />
        {/snippet}
        {@render field("evidence", "Evidence", evidenceField)}

        <button type="submit" disabled={busy}>Save fact</button>
        <button type="button" onclick={() => { editing = null; }}>Cancel</button>
      </form>
    {/if}

    {#if facts.length === 0 && !noBank}
      <p class="muted">The bank is empty.</p>
    {/if}

    <ul class="facts">
      {#each shown as fact (fact.id)}
        <li class="fact">
          <p><strong>{fact.id}</strong> <span class="tag">{fact.kind}</span></p>
          <p>{fact.claim}</p>
          {#if fact.employer || fact.role || fact.issuer || fact.start || fact.end}
            <p class="muted">
              {[fact.role, fact.employer, fact.issuer].filter(Boolean).join(", ")}
              {fact.start ?? ""}{fact.start || fact.end ? " to " : ""}{fact.end ?? ""}
            </p>
          {/if}
          {#if fact.tags.length > 0}
            <p class="muted">
              {#each fact.tags as tag, index (index)}<span class="tag">{tag.name} ({tag.level})</span> {/each}
            </p>
          {/if}
          <p class="muted">Source: {fact.evidence.type}, {fact.evidence.pointer}</p>
          <p>
            {#if fact.verified_on}<strong>Verified on {fact.verified_on}</strong>{:else}<strong>Unverified</strong>, not used by any report or draft{/if}
            |
            {#if fact.share === "shareable"}Shareable: may be shown to a model{:else}Local only: never shown to a model{/if}
          </p>
          <div class="actions">
            {#if fact.verified_on}
              <button type="button" disabled={busy} onclick={() => unverify(fact)}>Remove verification</button>
            {:else}
              <button type="button" disabled={busy} onclick={() => verify(fact)}>Verify this fact</button>
            {/if}
            <button type="button" disabled={busy} onclick={() => share(fact)}>
              {fact.share === "shareable" ? "Make local only" : "Allow a model to see this fact"}
            </button>
            <button type="button" disabled={busy || editing !== null} onclick={() => { startEdit(fact); }}>Edit</button>
            {#if confirming === fact.id}
              <button type="button" disabled={busy} onclick={() => remove(fact)}>Confirm delete {fact.id}</button>
              <button type="button" onclick={() => { confirming = null; }}>Cancel</button>
            {:else}
              <button type="button" disabled={busy} onclick={() => { confirming = fact.id; }}>Delete</button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>
