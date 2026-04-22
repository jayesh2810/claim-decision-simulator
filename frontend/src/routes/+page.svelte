<script lang="ts">
  import { dev } from '$app/environment';
  import { onMount } from 'svelte';
  import DecisionStep from '$lib/DecisionStep.svelte';
  import type { ClaimRecord, SimulateResponse } from '$lib/types';

  let claims = $state<ClaimRecord[]>([]);
  let healthInfo = $state<{ debug?: boolean } | null>(null);
  let loadError = $state<string | null>(null);
  let selectedId = $state<string>('');
  let loading = $state(false);
  let result = $state<SimulateResponse | null>(null);
  let stepVisible = $state<boolean[]>([]);
  let finalVisible = $state(false);
  let mermaidHtml = $state('');

  let fileEl: HTMLInputElement | undefined = $state();
  let selectedFile = $state<File | null>(null);
  let dragActive = $state(false);

  const api = (path: string) => (dev ? path : `http://127.0.0.1:8000${path}`);

  onMount(async () => {
    try {
      const h = await fetch(api('/health'));
      if (h.ok) healthInfo = await h.json();
    } catch {
      healthInfo = null;
    }
    try {
      const res = await fetch(api('/sample-claims'));
      if (res.ok) {
        claims = await res.json();
        const first = claims[0]?.metadata as { claim_id?: string } | undefined;
        if (first?.claim_id) selectedId = first.claim_id;
      }
    } catch {
      /* demo endpoint disabled */
    }
  });

  function onFilePicked(files: FileList | null) {
    const f = files?.[0];
    selectedFile = f ?? null;
  }

  async function animateSteps(n: number) {
    stepVisible = Array(n).fill(false);
    for (let i = 0; i < n; i++) {
      await new Promise((r) => setTimeout(r, 280));
      stepVisible = stepVisible.map((_, j) => j <= i);
    }
  }

  async function runDocumentSimulation() {
    if (!selectedFile) return;
    loading = true;
    result = null;
    stepVisible = [];
    finalVisible = false;
    mermaidHtml = '';
    loadError = null;

    try {
      const fd = new FormData();
      fd.append('file', selectedFile);
      const res = await fetch(api('/simulate/from-document'), {
        method: 'POST',
        body: fd,
      });
      if (!res.ok) {
        let msg = `Request failed (${res.status})`;
        try {
          const err = await res.json();
          if (typeof err?.detail === 'string') msg = err.detail;
          else if (err?.detail?.message) msg = `${err.detail.message}: ${err.detail.detail ?? ''}`;
          else if (err?.detail) msg = JSON.stringify(err.detail);
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }
      const data: SimulateResponse = await res.json();
      result = data;
      const n = data.audit_trail?.length ?? 0;
      await animateSteps(n);
      await new Promise((r) => setTimeout(r, 200));
      finalVisible = true;

      const { default: mermaid } = await import('mermaid');
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        securityLevel: 'loose',
        themeVariables: {
          primaryColor: '#14b8a6',
          primaryTextColor: '#f1f5f9',
          lineColor: '#94a3b8',
          secondaryColor: '#1e293b',
          tertiaryColor: '#0f172a',
        },
      });
      const diagram = `flowchart TD
        A[Document upload plus OCR] --> B[LLM structured extraction]
        B --> C[13-step audit pipeline]
        C --> D{Decision gate}
        D -->|Intake or eligibility fail| E[DENY]
        D -->|Fraud score over 70 or duplicates| F[HOLD FOR REVIEW]
        D -->|All clear| G[APPROVE]`;
      const { svg } = await mermaid.render(`cdsFlow-${Date.now()}`, diagram);
      mermaidHtml = svg;
    } catch (e) {
      loadError = e instanceof Error ? e.message : 'Simulation error';
    } finally {
      loading = false;
    }
  }

  async function runSimulation() {
    const claim = claims.find((c) => (c.metadata as { claim_id: string }).claim_id === selectedId);
    if (!claim) return;
    loading = true;
    result = null;
    stepVisible = [];
    finalVisible = false;
    mermaidHtml = '';
    loadError = null;

    try {
      const res = await fetch(api('/simulate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(claim),
      });
      if (!res.ok) throw new Error(`Simulation failed (${res.status})`);
      const data: SimulateResponse = await res.json();
      result = data;
      const n = data.audit_trail?.length ?? 4;
      await animateSteps(n);
      await new Promise((r) => setTimeout(r, 200));
      finalVisible = true;

      const { default: mermaid } = await import('mermaid');
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        securityLevel: 'loose',
        themeVariables: {
          primaryColor: '#14b8a6',
          primaryTextColor: '#f1f5f9',
          lineColor: '#94a3b8',
          secondaryColor: '#1e293b',
          tertiaryColor: '#0f172a',
        },
      });
      const diagram = `flowchart TD
        A[Structured claim JSON] --> B[1. Document intake]
        B --> C[2. Identity verification]
        C --> D[3. Policy verification]
        D --> E[4. Eligibility]
        E --> F[5. Coverage scope]
        F --> G[6. Exclusion screening]
        G --> H[7. Duplicate detection]
        H --> I[8. Fraud scoring]
        I --> J[9. Third-party liability]
        J --> K[10. Subrogation potential]
        K --> L[11. Compliance]
        L --> M[12. Reserve setting]
        M --> N[13. Payout calculation]
        N --> O{Decision gate}
        O -->|Steps 1-6 or 11 fail| P[DENY]
        O -->|Step 7 fail or fraud over 70| Q[HOLD FOR REVIEW]
        O -->|All clear| R[APPROVE]`;
      const { svg } = await mermaid.render(`cdsFlow-${Date.now()}`, diagram);
      mermaidHtml = svg;
    } catch (e) {
      loadError = e instanceof Error ? e.message : 'Simulation error';
    } finally {
      loading = false;
    }
  }

  function downloadAudit() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${result.claim_id}-audit-trail.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const labelForClaim = (c: ClaimRecord) => {
    const m = c.metadata as {
      claim_id: string;
      claimant_name: string;
      claim_line: string;
    };
    return `${m.claim_id}: ${m.claimant_name} — ${m.claim_line.replace(/_/g, ' ')}`;
  };

  const decisionTone = (d: string) => {
    if (d === 'APPROVE') return 'approve';
    if (d === 'DENY') return 'deny';
    return 'hold';
  };

  function formatMoney(n: number | null) {
    if (n === null || n === undefined) return '—';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
  }
</script>

<svelte:head>
  <title>Claim Decision Simulator</title>
</svelte:head>

<main class="shell">
  <header class="hero">
    <p class="eyebrow">Document-driven adjudication</p>
    <h1>Claim Decision Simulator</h1>
    <p class="lede">
      Upload a claim PDF or image: text is extracted locally (OCR when needed), then <strong>Groq</strong>
      returns a structured decision and step-by-step audit trail. Set <code>GROQ_API_KEY</code> in
      <code>backend/.env</code>.
    </p>
  </header>

  <section class="panel upload-panel">
    <h2 class="section-title">Primary: upload a claim document</h2>
    <p class="hint">
      PDF, PNG, JPEG, or JSON claim files — max size enforced by the API (see backend settings).
    </p>
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="dropzone"
      class:active={dragActive}
      role="region"
      aria-label="Upload claim document"
      ondragenter={() => (dragActive = true)}
      ondragleave={() => (dragActive = false)}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        dragActive = false;
        onFilePicked(e.dataTransfer?.files ?? null);
      }}
    >
      <input
        bind:this={fileEl}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.json,application/pdf,application/json,image/*"
        class="sr-only"
        id="claim-file"
        onchange={(e) => onFilePicked(e.currentTarget.files)}
      />
      <label for="claim-file" class="drop-label">
        <span class="drop-main">Drop a file here or choose file</span>
        {#if selectedFile}
          <span class="file-name">{selectedFile.name}</span>
        {/if}
      </label>
    </div>
    <div class="row-actions">
      <button
        type="button"
        class="primary"
        onclick={runDocumentSimulation}
        disabled={loading || !selectedFile}
      >
        {#if loading}
          <span class="spin" aria-hidden="true"></span>
          Running…
        {:else}
          Run decision from document
        {/if}
      </button>
    </div>
  </section>

  {#if claims.length > 0}
    <section class="panel demo-panel">
      <h2 class="section-title">Optional: deterministic demo (DEBUG backend)</h2>
      <p class="hint">
        Loaded bundled fixtures. Set <code>DEBUG=true</code> in backend env to enable this list.
      </p>
      <div class="controls">
        <label class="field">
          <span>Select sample claim</span>
          <select bind:value={selectedId}>
            {#each claims as c}
              <option value={(c.metadata as { claim_id: string }).claim_id}>{labelForClaim(c)}</option>
            {/each}
          </select>
        </label>
        <button type="button" class="secondary-btn" onclick={runSimulation} disabled={loading || !selectedId}>
          Run deterministic simulate
        </button>
      </div>
    </section>
  {/if}

  {#if healthInfo}
    <p class="status-strip">
      API: connected
      {#if healthInfo.debug}
        · <span class="tag">DEBUG</span>
      {/if}
    </p>
  {/if}

  {#if loadError}
    <p class="err" role="alert">{loadError}</p>
  {/if}

  {#if result}
    {@const meta = claims.find((c) => (c.metadata as { claim_id: string }).claim_id === result!.claim_id)}
    <section class="panel claim-meta">
      <h2>Claim</h2>
      <p class="meta-line">
        <strong>{result.claim_id}</strong>
        {#if meta}
          <span class="dot">·</span>
          {(meta.metadata as { claimant_name: string }).claimant_name}
          <span class="dot">·</span>
          {(meta.metadata as { claim_line: string }).claim_line.replace(/_/g, ' ')}
        {:else}
          <span class="dot">·</span>
          <span class="muted-inline">from uploaded document (LLM)</span>
        {/if}
      </p>
    </section>

    <section class="steps">
      {#each result.audit_trail as entry, i}
        <DecisionStep
          entry={entry}
          index={i}
          visible={stepVisible[i] ?? false}
          fraudScore={entry.step === 'fraud' ? result.fraud_risk_score : 0}
        />
      {/each}
    </section>

    <section class="panel final" class:visible={finalVisible}>
      <h2>Final decision</h2>
      <div class="final-row">
        <span class={`decision decision-${decisionTone(result.final_decision)}`}>
          {#if result.final_decision === 'APPROVE'}
            ✓ APPROVE
          {:else if result.final_decision === 'DENY'}
            ✗ DENY
          {:else}
            ⚠ HOLD FOR REVIEW
          {/if}
        </span>
        <div class="payout">
          <span class="payout-label">Indicated payout</span>
          <span class="payout-val">{formatMoney(result.payout_amount)}</span>
        </div>
      </div>
      <p class="summary">{result.summary}</p>
      <button type="button" class="secondary" onclick={downloadAudit}>Download audit trail (JSON)</button>
    </section>

    <section class="panel mermaid-panel">
      <h2>Workflow</h2>
      <p class="muted small">High-level flow for how this result was produced.</p>
      <div class="mermaid-wrap">
        {#if mermaidHtml}
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          {@html mermaidHtml}
        {/if}
      </div>
    </section>
  {/if}
</main>

<style>
  .shell {
    max-width: 920px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 4rem;
  }

  .hero {
    margin-bottom: 1.75rem;
  }

  .eyebrow {
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 0.72rem;
    color: var(--teal);
    margin: 0 0 0.35rem;
    font-weight: 600;
  }

  h1 {
    margin: 0 0 0.5rem;
    font-size: 1.85rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  .lede {
    margin: 0;
    color: var(--muted);
    max-width: 68ch;
    line-height: 1.55;
    font-size: 0.95rem;
  }

  .lede code {
    font-size: 0.85em;
    background: var(--bg);
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
  }

  .section-title {
    margin: 0 0 0.35rem;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    font-weight: 600;
  }

  .hint {
    margin: 0 0 1rem;
    font-size: 0.88rem;
    color: var(--muted);
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.35rem;
    margin-bottom: 1rem;
  }

  .upload-panel {
    border-color: rgba(20, 184, 166, 0.35);
  }

  .dropzone {
    border: 1px dashed var(--border);
    border-radius: 10px;
    padding: 1.25rem;
    background: var(--bg);
    transition:
      border-color 0.2s,
      background 0.2s;
  }

  .dropzone.active {
    border-color: var(--teal);
    background: var(--teal-dim);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    border: 0;
  }

  .drop-label {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    cursor: pointer;
    color: var(--text);
  }

  .drop-main {
    font-weight: 600;
  }

  .file-name {
    font-size: 0.9rem;
    color: var(--teal);
  }

  .row-actions {
    margin-top: 1rem;
  }

  .controls {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: flex-end;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    flex: 1;
    min-width: 240px;
    font-size: 0.8rem;
    color: var(--muted);
    font-weight: 600;
  }

  select {
    padding: 0.55rem 0.65rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    font-size: 0.95rem;
  }

  .primary {
    padding: 0.65rem 1.35rem;
    border-radius: 10px;
    border: none;
    cursor: pointer;
    font-weight: 600;
    background: linear-gradient(135deg, #14b8a6, #0d9488);
    color: #042f2e;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-height: 2.65rem;
  }

  .primary:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .secondary,
  .secondary-btn {
    padding: 0.55rem 1rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text);
    cursor: pointer;
    font-weight: 500;
  }

  .secondary-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .secondary {
    margin-top: 1rem;
  }

  .secondary:hover,
  .secondary-btn:hover {
    background: var(--surface-elevated);
  }

  .spin {
    width: 1rem;
    height: 1rem;
    border: 2px solid rgba(4, 47, 46, 0.3);
    border-top-color: #042f2e;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .err {
    color: var(--red);
    font-size: 0.9rem;
  }

  .status-strip {
    font-size: 0.8rem;
    color: var(--muted);
    margin: 0 0 0.75rem;
  }

  .tag {
    display: inline-block;
    padding: 0.05rem 0.35rem;
    border-radius: 4px;
    background: var(--amber-dim);
    color: var(--amber);
    font-weight: 600;
    font-size: 0.72rem;
  }

  .claim-meta h2,
  .final h2,
  .mermaid-panel h2 {
    margin: 0 0 0.5rem;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    font-weight: 600;
  }

  .meta-line {
    margin: 0;
    font-size: 1rem;
    color: var(--text);
  }

  .muted-inline {
    color: var(--muted);
    font-size: 0.92rem;
  }

  .dot {
    color: var(--muted);
    margin: 0 0.25rem;
  }

  .final {
    opacity: 0;
    transform: translateY(10px);
    transition:
      opacity 0.35s ease,
      transform 0.35s ease;
  }

  .final.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .final-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }

  .decision {
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .decision-approve {
    color: var(--green);
  }
  .decision-deny {
    color: var(--red);
  }
  .decision-hold {
    color: var(--amber);
  }

  .payout {
    text-align: right;
  }

  .payout-label {
    display: block;
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .payout-val {
    font-size: 1.35rem;
    font-weight: 700;
  }

  .summary {
    margin: 0.85rem 0 0;
    color: var(--muted);
    line-height: 1.5;
    font-size: 0.95rem;
  }

  .muted {
    color: var(--muted);
  }

  .small {
    font-size: 0.85rem;
    margin-top: 0;
  }

  .mermaid-wrap {
    overflow: auto;
    padding: 0.5rem 0;
  }

  .mermaid-wrap :global(svg) {
    max-width: 100%;
    height: auto;
  }
</style>
