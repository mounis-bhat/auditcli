# SvelteKit Integration Guide for AuditCLI

This guide covers integrating the `auditcli` tool into a SvelteKit application.

## Prerequisites

- Node.js 18+
- SvelteKit 2+ with Svelte 5 (uses runes)
- Python 3.13+ with `uv` installed on the server
- `auditcli` installed and accessible via `uv run auditcli`

## Key Features

- **Comprehensive Auditing**: Lighthouse performance, accessibility, SEO, and best practices scores
- **Real-World Data**: Chrome User Experience Report (CrUX) field data integration
- **AI-Powered Insights**: Gemini AI analysis with actionable recommendations
- **Automatic Caching**: SQLite-based caching with configurable TTL to reduce API costs
- **Input Validation**: Pre-flight validation with `--validate-only` flag
- **Error Resilience**: Retry logic, graceful degradation, structured error responses
- **Performance Monitoring**: Built-in timing and profiling for bottleneck identification
- **Production Ready**: Configurable timeouts, environment variable validation, no crashes

---

## 1. Project Setup

### Environment Variables

```env
# .env
AUDITCLI_PATH=/home/mounis/Development/personal/auditcli  # Path to auditcli project
RATE_LIMIT_WINDOW_MS=900000                               # 15 minutes
RATE_LIMIT_MAX_REQUESTS=10                                # Max 10 audits per window per IP
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
  timing?: Record<string, number>;
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

**Note**: The auditcli automatically caches results for 24 hours (configurable via `CACHE_TTL_SECONDS`). Use `noCache: true` to force fresh audits, or `timeout` to set custom timeouts in seconds.

```typescript
// src/lib/server/audit.service.ts

import { exec } from 'child_process';
import { promisify } from 'util';
import type { AuditResponse } from '$lib/types/audit';

const execAsync = promisify(exec);

export async function runAudit(url: string, options?: { noCache?: boolean; timeout?: number }): Promise<AuditResponse> {
  let command = `uv run auditcli`;

  if (options?.noCache) {
    command += ` --no-cache`;
  }

  if (options?.timeout) {
    command += ` --timeout ${options.timeout}`;
  }

  command += ` ${url}`;

  try {
    const { stdout } = await execAsync(command, {
      cwd: process.env.AUDITCLI_PATH || process.cwd(),
      timeout: (options?.timeout || 600) * 1000 + 60000, // CLI timeout + 1 minute buffer
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
  const { url, noCache = false, timeout } = body;

  if (!url || typeof url !== 'string') {
    throw error(400, { message: 'URL is required' });
  }

  if (!isValidUrl(url)) {
    throw error(400, { message: 'Invalid URL format' });
  }

  const options = {
    noCache: Boolean(noCache),
    ...(timeout && typeof timeout === 'number' && { timeout })
  };

  const result = await runAudit(url, options);

  if (result.status === 'failed') {
    throw error(500, { message: result.error || 'Audit failed' });
  }

  return json(result);
};
```

---

## 5. Batch Audits (Queue Implementation)

For handling multiple URLs, implement a queue system to process audits sequentially (one at a time) to avoid overloading the server.

Create a new API endpoint for batch processing:

```typescript
// src/routes/api/audit/batch/+server.ts

import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { runAudit, isValidUrl } from '$lib/server/audit.service';

interface BatchRequest {
  urls: string[];
}

interface BatchResponse {
  results: Array<{
    url: string;
    success: boolean;
    data?: any;
    error?: string;
  }>;
}

export const POST: RequestHandler = async ({ request }) => {
  const body: BatchRequest = await request.json();
  const { urls } = body;

  if (!urls || !Array.isArray(urls)) {
    throw error(400, { message: 'URLs array is required' });
  }

  if (urls.length > 10) {
    throw error(400, { message: 'Maximum 10 URLs per batch' });
  }

  const results: BatchResponse['results'] = [];

  for (const url of urls) {
    if (!isValidUrl(url)) {
      results.push({ url, success: false, error: 'Invalid URL format' });
      continue;
    }

    try {
      const data = await runAudit(url);
      results.push({ url, success: true, data });
    } catch (err: any) {
      results.push({ url, success: false, error: err.message });
    }
  }

  return json({ results });
};
```

This processes URLs one by one sequentially. For more advanced queuing, consider using a job queue library.

---

## 6. Rate Limiting

Implement custom rate limiting to prevent abuse and ensure fair usage. This simple in-memory implementation tracks requests per IP.

```typescript
// src/lib/rate-limit.ts

interface RateLimitEntry {
  count: number;
  resetTime: number;
}

const rateLimitMap = new Map<string, RateLimitEntry>();

export function checkRateLimit(ip: string): { allowed: boolean; resetTime?: number } {
  const now = Date.now();
  const windowMs = parseInt(process.env.RATE_LIMIT_WINDOW_MS || '900000'); // 15 minutes
  const maxRequests = parseInt(process.env.RATE_LIMIT_MAX_REQUESTS || '10');

  const entry = rateLimitMap.get(ip);

  if (!entry || now > entry.resetTime) {
    // First request or window expired
    rateLimitMap.set(ip, { count: 1, resetTime: now + windowMs });
    return { allowed: true };
  }

  if (entry.count >= maxRequests) {
    return { allowed: false, resetTime: entry.resetTime };
  }

  entry.count++;
  return { allowed: true };
}
```

Add to hooks for global rate limiting:

```typescript
// src/hooks.server.ts

import type { Handle } from '@sveltejs/kit';
import { checkRateLimit } from '$lib/rate-limit';

export const handle: Handle = async ({ event, resolve }) => {
  const ip = event.getClientAddress();
  const rateLimit = checkRateLimit(ip);

  if (!rateLimit.allowed) {
    return new Response(
      JSON.stringify({
        error: 'Too many audit requests from this IP, please try again later.',
        resetTime: new Date(rateLimit.resetTime!).toISOString(),
      }),
      {
        status: 429,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': Math.ceil((rateLimit.resetTime! - Date.now()) / 1000).toString(),
        },
      }
    );
  }

  return resolve(event);
};
```

---

## 8. Client-Side State (Svelte 5 Runes)

```typescript
// src/lib/stores/audit.svelte.ts

import type { AuditResponse } from '$lib/types/audit';

class AuditState {
  loading = $state(false);
  error = $state<string | null>(null);
  response = $state<AuditResponse | null>(null);

  // Derived state
  lighthouse = $derived(this.response?.lighthouse ?? null);
  crux = $derived(this.response?.crux ?? null);
  aiReport = $derived(this.response?.insights.ai_report ?? null);

  async runAudit(url: string, options?: { noCache?: boolean; timeout?: number }) {
    this.loading = true;
    this.error = null;

    try {
      const res = await fetch('/api/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, ...options }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.message || 'Audit failed');
      }

      this.response = await res.json();
      return this.response;
    } catch (error: any) {
      this.error = error.message;
      throw error;
    } finally {
      this.loading = false;
    }
  }

  reset() {
    this.loading = false;
    this.error = null;
    this.response = null;
  }
}

export const auditState = new AuditState();
```

---

## 9. UI Components

### Audit Form

```svelte
<!-- src/lib/components/AuditForm.svelte -->
<script lang="ts">
  import { auditState } from '$lib/stores/audit.svelte';

  let url = $state('');
  let noCache = $state(false);
  let customTimeout = $state('');

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!url) return;

    const options: { noCache?: boolean; timeout?: number } = {};

    if (noCache) options.noCache = true;
    if (customTimeout) options.timeout = parseInt(customTimeout);

    await auditState.runAudit(url, Object.keys(options).length > 0 ? options : undefined);
  }
</script>

<form onsubmit={handleSubmit}>
  <input
    type="url"
    bind:value={url}
    placeholder="https://example.com"
    required
    disabled={auditState.loading}
  />

  <label>
    <input type="checkbox" bind:checked={noCache} disabled={auditState.loading} />
    Skip cache (force fresh audit)
  </label>

  <label>
    Timeout (seconds, default: 600):
    <input
      type="number"
      bind:value={customTimeout}
      placeholder="600"
      min="30"
      max="3600"
      disabled={auditState.loading}
    />
  </label>

  <button type="submit" disabled={auditState.loading || !url}>
    {auditState.loading ? 'Auditing...' : 'Run Audit'}
  </button>

  {#if auditState.error}
    <p class="error">{auditState.error}</p>
  {/if}
</form>
```

### Score Badge

```svelte
<!-- src/lib/components/ScoreBadge.svelte -->
<script lang="ts">
  interface Props {
    score: number;
    label: string;
  }

  let { score, label }: Props = $props();

  let displayScore = $derived(Math.round(score * 100));
  let rating = $derived(displayScore >= 90 ? 'good' : displayScore >= 50 ? 'needs-improvement' : 'poor');
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
  import { auditState } from '$lib/stores/audit.svelte';
  import AuditForm from '$lib/components/AuditForm.svelte';
  import ScoreBadge from '$lib/components/ScoreBadge.svelte';
</script>

<main>
  <h1>Website Audit</h1>
  <AuditForm />

  {#if auditState.loading}
    <p>Running audit... (this may take a few minutes)</p>
  {/if}

  {#if auditState.response && auditState.lighthouse?.mobile}
    <section>
      <h2>Mobile Scores</h2>
      <div class="scores">
        <ScoreBadge score={auditState.lighthouse.mobile.categories.performance} label="Performance" />
        <ScoreBadge score={auditState.lighthouse.mobile.categories.accessibility} label="Accessibility" />
        <ScoreBadge score={auditState.lighthouse.mobile.categories.best_practices} label="Best Practices" />
        <ScoreBadge score={auditState.lighthouse.mobile.categories.seo} label="SEO" />
      </div>
    </section>

    {#if auditState.aiReport}
      <section>
        <h2>AI Analysis</h2>
        <p>{auditState.aiReport.executive_summary}</p>
      </section>
    {/if}
  {/if}
</main>
```

---

## 10. File Structure

```
src/
├── hooks.server.ts
├── lib/
│   ├── components/
│   │   ├── AuditForm.svelte
│   │   └── ScoreBadge.svelte
│   ├── rate-limit.ts
│   ├── server/
│   │   └── audit.service.ts
│   ├── stores/
│   │   └── audit.svelte.ts
│   └── types/
│       └── audit.ts
└── routes/
    ├── api/
    │   └── audit/
    │       ├── +server.ts
    │       └── batch/
    │           └── +server.ts
    └── audit/
        └── +page.svelte
```

---

## 11. Quick Start Checklist

- [ ] Copy type definitions to `src/lib/types/audit.ts`
- [ ] Create audit service at `src/lib/server/audit.service.ts`
- [ ] Create API endpoint at `src/routes/api/audit/+server.ts`
- [ ] Create batch audit endpoint at `src/routes/api/audit/batch/+server.ts`
- [ ] Implement rate limiting in `src/lib/rate-limit.ts` and `src/hooks.server.ts`
- [ ] Create state module at `src/lib/stores/audit.svelte.ts`
- [ ] Create UI components
- [ ] Set `AUDITCLI_PATH`, `RATE_LIMIT_WINDOW_MS`, and `RATE_LIMIT_MAX_REQUESTS` in `.env`
- [ ] Set `GOOGLE_API_KEY`, `PSI_API_KEY`, and optionally `CACHE_TTL_SECONDS` in the auditcli `.env`
- [ ] Test: `uv run auditcli https://mounis.net | jq '.status'`
- [ ] Test caching: `uv run auditcli --no-cache https://mounis.net` (skip cache)
- [ ] Test validation: `uv run auditcli --validate-only https://example.com`
