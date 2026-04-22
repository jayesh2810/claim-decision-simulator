<script lang="ts">
  import type { AuditEntry } from './types';

  type Props = {
    entry: AuditEntry;
    index: number;
    visible: boolean;
    fraudScore?: number;
  };

  let { entry, index, visible, fraudScore = 0 }: Props = $props();

  let open = $state(true);

  const b = $derived.by(() => {
    if (entry.step === 'fraud') {
      if (fraudScore >= 50) return { label: `⚠ SCORE: ${fraudScore}/100`, tone: 'warn' as const };
      return { label: `SCORE: ${fraudScore}/100`, tone: 'muted' as const };
    }
    if (entry.status === 'fail') return { label: '✗ FAIL', tone: 'bad' as const };
    if (entry.status === 'warning') return { label: '⚠ REVIEW', tone: 'warn' as const };
    if (entry.status === 'info') return { label: 'CALC', tone: 'muted' as const };
    return { label: '✓ PASS', tone: 'good' as const };
  });

  const formatFinding = (f: Record<string, unknown>): string => {
    if ('check' in f && 'result' in f) {
      const ok = f.result ? '✓' : '✗';
      let s = `${ok} ${String(f.check)}`;
      if (Array.isArray(f.violations) && f.violations.length) {
        const bits = (f.violations as Record<string, unknown>[]).map((v) =>
          'rule' in v ? `✗ ${String(v.rule)}${v.detail ? ` (${String(v.detail)})` : ''}` : JSON.stringify(v),
        );
        s += `: ${bits.join('; ')}`;
      } else if (f.detail) {
        s += ` — ${String(f.detail)}`;
      }
      return s;
    }
    if ('label' in f && 'value' in f) {
      const val = f.value;
      if (Array.isArray(val)) return `${String(f.label)}: ${val.join(', ')}`;
      return `${String(f.label)}: ${String(val)}`;
    }
    if ('rule' in f) {
      return `✗ ${String(f.rule)}${f.detail ? ` — ${String(f.detail)}` : ''}`;
    }
    return JSON.stringify(f);
  };
</script>

<div
  class="step"
  class:visible
  style:animation-delay="{visible ? index * 0.12 : 0}s"
  role="region"
  aria-label={entry.title}
>
  <button type="button" class="step-head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="step-num">{index + 1}</span>
    <span class="step-title">{entry.title}</span>
    <span
      class="badge"
      class:badge-good={b.tone === 'good'}
      class:badge-bad={b.tone === 'bad'}
      class:badge-warn={b.tone === 'warn'}
      class:badge-muted={b.tone === 'muted'}>{b.label}</span
    >
    <span class="chev" aria-hidden="true">{open ? '▼' : '▶'}</span>
  </button>
  {#if open}
    <div class="step-body">
      <ul class="findings">
        {#each entry.findings as finding}
          <li>{formatFinding(finding as Record<string, unknown>)}</li>
        {/each}
      </ul>
      <p class="reasoning">{entry.reasoning}</p>
    </div>
  {/if}
</div>

<style>
  .step {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 0.65rem;
    overflow: hidden;
    opacity: 0;
    transform: translateY(12px);
  }

  .step.visible {
    animation: rise 0.45s ease forwards;
  }

  @keyframes rise {
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .step-head {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1rem;
    background: transparent;
    border: none;
    color: inherit;
    cursor: pointer;
    text-align: left;
    font-size: 0.95rem;
  }

  .step-head:hover {
    background: var(--surface-elevated);
  }

  .step-num {
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 8px;
    background: var(--teal-dim);
    color: var(--teal);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 0.85rem;
  }

  .step-title {
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  .badge {
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.2rem 0.5rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    white-space: nowrap;
  }

  .badge-good {
    color: var(--green);
    background: var(--green-dim);
    border-color: rgba(52, 211, 153, 0.35);
  }
  .badge-bad {
    color: var(--red);
    background: var(--red-dim);
    border-color: rgba(248, 113, 113, 0.35);
  }
  .badge-warn {
    color: var(--amber);
    background: var(--amber-dim);
    border-color: rgba(245, 158, 11, 0.35);
  }
  .badge-muted {
    color: var(--muted);
    background: rgba(148, 163, 184, 0.1);
  }

  .chev {
    color: var(--muted);
    font-size: 0.75rem;
  }

  .step-body {
    padding: 0 1rem 1rem 1rem;
    border-top: 1px solid var(--border);
  }

  .findings {
    margin: 0.85rem 0 0 0;
    padding-left: 1.1rem;
    color: var(--muted);
    font-size: 0.88rem;
    line-height: 1.55;
  }

  .reasoning {
    margin: 0.75rem 0 0 0;
    font-size: 0.88rem;
    color: var(--text);
    line-height: 1.5;
    opacity: 0.95;
  }
</style>
