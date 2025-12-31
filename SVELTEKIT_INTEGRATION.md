# SvelteKit Integration Guide for AuditCLI

This guide covers integrating the `auditcli` tool into a SvelteKit application.

## Prerequisites

- Node.js 18+
- SvelteKit project
- Python 3.13+ with `uv` installed on the server
- `auditcli` installed and accessible via `uv run auditcli`

---

## 1. Project Setup

### Environment Variables

```env
# .env
AUDITCLI_PATH=/path/to/web-audit-ai  # Path to auditcli project
```

---

## 2. Type Definitions

Create type definitions that match the CLI's JSON output.

```typescript
// src/lib/types/audit.ts

export type Status = 'success' | 'partial' | 'failed';
export type Rating = 'good' | 'needs_improvement' | 'poor';

export interface AuditResponse {
  status: Status;
  url: string;
  lighthouse: LighthouseReport;
  crux: CrUXData | null;
  insights: Insights;
  error?: string;
}

export interface LighthouseReport {
  mobile: LighthouseMetrics | null;
  desktop: LighthouseMetrics | null;
}

export interface LighthouseMetrics {
  categories: CategoryScores;
  vitals: CoreWebVitals;
  opportunities: Opportunity[];
}

export interface CategoryScores {
  performance: number;
  accessibility: number;
  best_practices: number;
  seo: number;
}

export interface CoreWebVitals {
  lcp_ms: number | null;
  cls: number | null;
  inp_ms: number | null;
  tbt_ms: number | null;
}

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  estimated_savings_ms: number | null;
}

export interface CrUXData {
  lcp: CrUXMetric | null;
  cls: CrUXMetric | null;
  inp: CrUXMetric | null;
  fcp: CrUXMetric | null;
  ttfb: CrUXMetric | null;
  origin_fallback: boolean;
  overall_rating: Rating | null;
}

export interface CrUXMetric {
  p75: number | null;
  distribution: MetricDistribution | null;
  rating: Rating | null;
}

export interface MetricDistribution {
  good: number;
  needs_improvement: number;
  poor: number;
}

export interface Insights {
  metrics: LighthouseReport;
  ai_report: AIReport | null;
}

export interface AIReport {
  executive_summary: string;
  performance_analysis: PerformanceAnalysis;
  core_web_vitals_analysis: CoreWebVitalsAnalysis;
  category_insights: CategoryInsights;
  strengths: string[];
  weaknesses: string[];
  opportunities: AIOpportunity[];
  recommendations: AIRecommendation[];
  business_impact_summary: string;
  next_steps: string[];
}

export interface PerformanceAnalysis {
  mobile_summary: string;
  desktop_summary: string;
  mobile_vs_desktop: string;
}

export interface CoreWebVitalsAnalysis {
  lcp_analysis: string;
  cls_analysis: string;
  inp_tbt_analysis: string;
}

export interface CategoryInsights {
  performance: string;
  accessibility: string;
  best_practices: string;
  seo: string;
}

export interface AIOpportunity {
  title: string;
  description: string;
  estimated_savings: string;
  priority: string;
  effort: string;
  business_impact: string;
}

export interface AIRecommendation {
  priority: number;
  title: string;
  description: string;
  rationale: string;
  expected_impact: string;
  implementation_complexity: string;
  quick_win: boolean;
}
```

---

## 3. Server-Side Service

Create a service to execute the CLI and parse results.

```typescript
// src/lib/server/audit.service.ts

import { exec } from 'child_process';
import { promisify } from 'util';
import type { AuditResponse } from '$lib/types/audit';

const execAsync = promisify(exec);

export async function runAudit(url: string): Promise<AuditResponse> {
  const command = `uv run auditcli ${url}`;

  try {
    const { stdout } = await execAsync(command, {
      cwd: process.env.AUDITCLI_PATH || process.cwd(),
      timeout: 300000, // 5 minute timeout
      maxBuffer: 10 * 1024 * 1024, // 10MB buffer
    });

    return JSON.parse(stdout);
  } catch (error: any) {
    // Try to parse error output as JSON
    if (error.stdout) {
      try {
        return JSON.parse(error.stdout);
      } catch {
        // Not JSON, fall through
      }
    }

    return {
      status: 'failed',
      url,
      lighthouse: { mobile: null, desktop: null },
      crux: null,
      insights: { metrics: { mobile: null, desktop: null }, ai_report: null },
      error: error.message || 'Failed to run audit',
    };
  }
}

export function isValidUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol);
  } catch {
    return false;
  }
}
```

---

## 4. API Endpoint

```typescript
// src/routes/api/audit/+server.ts

import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { runAudit, isValidUrl } from '$lib/server/audit.service';

export const POST: RequestHandler = async ({ request }) => {
  const body = await request.json();
  const { url } = body;

  if (!url || typeof url !== 'string') {
    throw error(400, { message: 'URL is required' });
  }

  if (!isValidUrl(url)) {
    throw error(400, { message: 'Invalid URL format' });
  }

  const result = await runAudit(url);

  if (result.status === 'failed') {
    throw error(500, { message: result.error || 'Audit failed' });
  }

  return json(result);
};
```

---

## 5. Client-Side Store

```typescript
// src/lib/stores/audit.store.ts

import { writable, derived } from 'svelte/store';
import type { AuditResponse } from '$lib/types/audit';

interface AuditState {
  loading: boolean;
  error: string | null;
  response: AuditResponse | null;
}

function createAuditStore() {
  const { subscribe, set, update } = writable<AuditState>({
    loading: false,
    error: null,
    response: null,
  });

  return {
    subscribe,

    async runAudit(url: string) {
      update((state) => ({ ...state, loading: true, error: null }));

      try {
        const res = await fetch('/api/audit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.message || 'Audit failed');
        }

        const response: AuditResponse = await res.json();
        update((state) => ({ ...state, loading: false, response }));
        return response;
      } catch (error: any) {
        update((state) => ({
          ...state,
          loading: false,
          error: error.message,
        }));
        throw error;
      }
    },

    reset() {
      set({ loading: false, error: null, response: null });
    },
  };
}

export const auditStore = createAuditStore();

// Derived stores
export const lighthouse = derived(
  auditStore,
  ($store) => $store.response?.lighthouse ?? null
);

export const crux = derived(
  auditStore,
  ($store) => $store.response?.crux ?? null
);

export const aiReport = derived(
  auditStore,
  ($store) => $store.response?.insights.ai_report ?? null
);
```

---

## 6. UI Components

### Audit Form

```svelte
<!-- src/lib/components/AuditForm.svelte -->
<script lang="ts">
  import { auditStore } from '$lib/stores/audit.store';

  let url = '';

  $: loading = $auditStore.loading;
  $: error = $auditStore.error;

  async function handleSubmit() {
    if (!url) return;
    await auditStore.runAudit(url);
  }
</script>

<form on:submit|preventDefault={handleSubmit}>
  <input
    type="url"
    bind:value={url}
    placeholder="https://example.com"
    required
    disabled={loading}
  />
  <button type="submit" disabled={loading || !url}>
    {loading ? 'Auditing...' : 'Run Audit'}
  </button>

  {#if error}
    <p class="error">{error}</p>
  {/if}
</form>
```

### Score Badge

```svelte
<!-- src/lib/components/ScoreBadge.svelte -->
<script lang="ts">
  export let score: number;
  export let label: string;

  $: displayScore = Math.round(score * 100);
  $: rating = displayScore >= 90 ? 'good' : displayScore >= 50 ? 'needs-improvement' : 'poor';
</script>

<div class="score-badge {rating}">
  <span class="score">{displayScore}</span>
  <span class="label">{label}</span>
</div>

<style>
  .score-badge {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 1rem;
    border-radius: 8px;
  }

  .score { font-size: 2rem; font-weight: bold; }
  .label { font-size: 0.875rem; }

  .good { background: #d4edda; color: #155724; }
  .needs-improvement { background: #fff3cd; color: #856404; }
  .poor { background: #f8d7da; color: #721c24; }
</style>
```

### Main Page

```svelte
<!-- src/routes/audit/+page.svelte -->
<script lang="ts">
  import { auditStore, lighthouse, crux, aiReport } from '$lib/stores/audit.store';
  import AuditForm from '$lib/components/AuditForm.svelte';
  import ScoreBadge from '$lib/components/ScoreBadge.svelte';

  $: loading = $auditStore.loading;
  $: response = $auditStore.response;
</script>

<main>
  <h1>Website Audit</h1>
  <AuditForm />

  {#if loading}
    <p>Running audit... (this may take a few minutes)</p>
  {/if}

  {#if response && $lighthouse?.mobile}
    <section>
      <h2>Mobile Scores</h2>
      <div class="scores">
        <ScoreBadge score={$lighthouse.mobile.categories.performance} label="Performance" />
        <ScoreBadge score={$lighthouse.mobile.categories.accessibility} label="Accessibility" />
        <ScoreBadge score={$lighthouse.mobile.categories.best_practices} label="Best Practices" />
        <ScoreBadge score={$lighthouse.mobile.categories.seo} label="SEO" />
      </div>
    </section>

    {#if $aiReport}
      <section>
        <h2>AI Analysis</h2>
        <p>{$aiReport.executive_summary}</p>
      </section>
    {/if}
  {/if}
</main>
```

---

## 7. File Structure

```
src/
├── lib/
│   ├── components/
│   │   ├── AuditForm.svelte
│   │   └── ScoreBadge.svelte
│   ├── server/
│   │   └── audit.service.ts
│   ├── stores/
│   │   └── audit.store.ts
│   └── types/
│       └── audit.ts
└── routes/
    ├── api/
    │   └── audit/
    │       └── +server.ts
    └── audit/
        └── +page.svelte
```

---

## Quick Start Checklist

- [ ] Copy type definitions to `src/lib/types/audit.ts`
- [ ] Create audit service at `src/lib/server/audit.service.ts`
- [ ] Create API endpoint at `src/routes/api/audit/+server.ts`
- [ ] Create store at `src/lib/stores/audit.store.ts`
- [ ] Create UI components
- [ ] Set `AUDITCLI_PATH` in `.env`
- [ ] Set `GOOGLE_API_KEY` and `PSI_API_KEY` in the auditcli `.env`
- [ ] Test: `uv run auditcli https://mounis.net | jq '.status'`
