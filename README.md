# AuditCLI

A robust, production-ready FastAPI web service that runs comprehensive web audits using Lighthouse, fetches real-world performance data from CrUX, and generates AI-powered insights. Features automatic caching, comprehensive input validation, graceful error handling, configurable timeouts, and detailed performance profiling. Returns everything as structured JSON for easy integration with CI/CD pipelines and monitoring systems.

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd auditcli

# Install dependencies with uv
uv sync
```

## Requirements

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- Google Chrome (for Lighthouse)
- Lighthouse CLI (`npm install -g lighthouse`)
- Google Gemini API key (for AI insights) - **validated on startup**
- Google PageSpeed Insights API key (for CrUX field data) - **validated on startup**

## Environment Variables

Create a `.env` file:

```env
# API Keys (required)
GOOGLE_API_KEY=your_gemini_key_here  # For AI insights
PSI_API_KEY=your_psi_key_here        # For CrUX field data

# Database and caching
AUDIT_CACHE_PATH=./audit_cache.db    # Path to SQLite cache database (default: ./audit_cache.db)
CACHE_TTL_SECONDS=86400              # Cache TTL in seconds (default: 86400 = 1 day)

# Audit settings
AUDIT_TIMEOUT=600                    # Default audit timeout in seconds (default: 600)

# Concurrency Controls
MAX_CONCURRENT_AUDITS=10             # Maximum number of audits running concurrently (default: 10)
MAX_QUEUE_SIZE=50                    # Maximum queue size for pending audits (default: 50)
QUEUE_TIMEOUT_SECONDS=300            # Timeout for queued audits in seconds (default: 300)

# Browser Pool Settings
BROWSER_POOL_SIZE=5                  # Number of browsers to keep in pool (default: 5)
BROWSER_LAUNCH_TIMEOUT=30            # Browser launch timeout in seconds (default: 30)
BROWSER_IDLE_TIMEOUT=300             # Idle browser cleanup timeout in seconds (default: 300)
```

### Getting API Keys

- **Gemini API Key**: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **PSI API Key**: Get from [Google Cloud Console](https://developers.google.com/speed/docs/insights/v5/get-started)

## Quick Start

1. **Install dependencies**: `uv sync`
2. **Set up API keys** in `.env` file
3. **Start the server**: `uv run uvicorn app.main:app --reload`
4. **Test the API**: `curl -X POST http://localhost:8000/v1/audit -H "Content-Type: application/json" -d '{"url": "https://example.com"}'`

## API Usage

The service provides a REST API for running web audits asynchronously with real-time progress updates.

### Create Audit Job

```bash
curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://yourwebsite.com"}'
```

Response:
```json
{
  "job_id": "abc123...",
  "status": "pending",
  "message": "Audit job created. Poll GET /v1/audit/{job_id} for status."
}
```

### Check Job Status

```bash
curl http://localhost:8000/v1/audit/{job_id}
```

### WebSocket Progress Updates

Connect to `ws://localhost:8000/v1/audit/{job_id}` for real-time progress updates.

### Examples

```bash
# Start an audit
JOB_ID=$(curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://mounis.net"}' | jq -r '.job_id')

# Check status
curl http://localhost:8000/v1/audit/$JOB_ID | jq

# Extract specific data
curl http://localhost:8000/v1/audit/$JOB_ID | jq '.result.lighthouse.mobile.categories'
curl http://localhost:8000/v1/audit/$JOB_ID | jq '.result.insights.ai_report.executive_summary'
curl http://localhost:8000/v1/audit/$JOB_ID | jq '.result.timing'
```

## API Response

Successful audits return a JSON response with the following structure:

```json
{
  "status": "success",
  "url": "https://mounis.net",
  "lighthouse": {
    "mobile": {
      "categories": {
        "performance": 0.66,
        "accessibility": 0.96,
        "best_practices": 1.0,
        "seo": 0.82
      },
      "vitals": {
        "lcp_ms": 7206.21,
        "cls": 0.0003,
        "tbt_ms": 277.29
      },
      "opportunities": [...]
    },
    "desktop": {
      "categories": {...},
      "vitals": {...},
      "opportunities": [...]
    }
  },
  "crux": {
    "lcp": { "p75": 2500, "rating": "good", "distribution": {...} },
    "cls": { "p75": 0.05, "rating": "good", "distribution": {...} },
    "inp": { "p75": 150, "rating": "good", "distribution": {...} },
    "origin_fallback": false,
    "overall_rating": "good"
   },
   "insights": {
     "metrics": {...},
     "ai_report": {
       "executive_summary": "...",
       "performance_analysis": {...},
       "core_web_vitals_analysis": {...},
       "category_insights": {...},
       "strengths": [...],
       "weaknesses": [...],
       "opportunities": [...],
       "recommendations": [...],
       "business_impact_summary": "...",
       "next_steps": [...]
     }
   },
   "timing": {
     "lighthouse": 45.2,
     "crux": 1.8,
     "ai": 12.5
   }
 }
```

### Status Values

| Status    | Description                                                     |
| --------- | --------------------------------------------------------------- |
| `success` | Everything worked (Lighthouse + CrUX + AI)                      |
| `partial` | Lighthouse worked but CrUX or AI failed (null for failed parts) |
| `failed`  | Lighthouse failed or validation/API errors                      |

### Performance Timing

The `timing` field provides execution time (in seconds) for each audit component:

- `lighthouse`: Time spent running Lighthouse audits (mobile + desktop)
- `crux`: Time spent fetching Chrome User Experience Report data
- `ai`: Time spent generating AI analysis report

This helps identify performance bottlenecks in the audit process.

### Error Response

```json
{
  "job_id": "abc123...",
  "status": "failed",
  "error": "Error message here"
}
```

### Job Status Response

The `/v1/audit/{job_id}` endpoint returns job status:

```json
{
  "job_id": "abc123...",
  "status": "completed",
  "url": "https://example.com",
  "progress": {
    "current_stage": "ai_analysis",
    "completed_stages": ["lighthouse_mobile", "lighthouse_desktop", "crux"],
    "pending_stages": []
  },
  "result": { /* full audit result */ },
  "error": null,
  "created_at": "2024-01-01T12:00:00Z",
  "queue_position": null
}
```

## Caching

Audit results are automatically cached in SQLite (`audit_cache.db`) to improve performance and reduce API calls:

- **Automatic Caching**: Successful audits are cached for 24 hours (configurable)
- **Cache TTL**: Set `CACHE_TTL_SECONDS` environment variable (default: 86400 = 1 day)
- **Bypass Cache**: Set `no_cache: true` in audit request to skip cache check and force fresh audit
- **SHA256 Hashing**: URLs are hashed for efficient lookups and privacy
- **Graceful Handling**: Cache corruption is automatically detected and database is recreated

### Cache Examples

```bash
# Use cached results (default behavior)
curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Force fresh audit, don't cache result
curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "no_cache": true}'

# Check cache statistics
curl http://localhost:8000/v1/cache/stats
```

## Validation & Error Handling

The API performs comprehensive validation:

- **API Keys**: Validates presence and basic format of `GOOGLE_API_KEY` and `PSI_API_KEY` on startup
- **URLs**: Normalizes URLs, enforces http/https protocols, validates domain format
- **Graceful Degradation**: Partial failures return `status: "partial"` with available data
- **Structured Errors**: All errors return consistent JSON format, never crash
- **Rate Limiting**: Per-IP limits to prevent abuse

## Data Sources

### Lab Data (Lighthouse)

Lighthouse runs simulated audits in a controlled environment:

- Performance, Accessibility, SEO, Best Practices scores (0-1)
- Core Web Vitals (LCP, CLS, INP/TBT)
- Optimization opportunities with estimated savings

### Field Data (CrUX)

Real-world user data from Chrome User Experience Report:

- Real user Core Web Vitals (p75 values)
- User experience distribution (% good/needs-improvement/poor)
- Falls back to origin-level data if URL-specific unavailable

**Note**: CrUX data requires sufficient traffic. Sites without enough traffic will have `crux: null`.

### AI Insights (Gemini)

AI-generated analysis including:

- Executive summary
- Performance analysis (mobile vs desktop)
- Core Web Vitals deep dive
- Strengths and weaknesses
- Prioritized recommendations
- Business impact assessment

## Features

- **Comprehensive Auditing**: Lighthouse performance, accessibility, SEO, and best practices scores
- **Real-World Data**: Chrome User Experience Report (CrUX) field data integration
- **AI-Powered Insights**: Gemini AI analysis with actionable recommendations
- **Automatic Caching**: SQLite-based caching with configurable TTL to reduce API costs
- **Input Validation**: Pre-flight validation with `--validate-only` flag
- **Error Resilience**: Retry logic, graceful degradation, structured error responses
- **Performance Monitoring**: Built-in timing and profiling for bottleneck identification
- **Production Ready**: Configurable timeouts, environment variable validation, no crashes

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/audit` | Create new audit job |
| `GET` | `/v1/audit/{job_id}` | Get audit job status/results |
| `DELETE` | `/v1/audit/{job_id}` | Cancel queued audit job |
| `GET` | `/v1/audits/running` | List running/queued audits |
| `GET` | `/v1/audits/stats` | System statistics |
| `GET` | `/v1/cache/stats` | Cache statistics |
| `POST` | `/v1/cache/cleanup` | Clean expired cache entries |
| `DELETE` | `/v1/cache` | Clear all cache |
| `WS` | `/v1/audit/{job_id}` | Real-time progress updates |
| `GET` | `/v1/health` | Comprehensive health check |

## Integration

The API is designed for easy integration with:

- **CI/CD pipelines**: Automated performance monitoring
- **Monitoring systems**: Real-time performance tracking
- **Web applications**: Frontend dashboards for performance insights
- **Alerting systems**: Performance regression detection

### WebSocket Progress Updates

Connect to `/v1/audit/{job_id}` for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/v1/audit/' + jobId);
ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log('Stage completed:', update.stage);
};
```

## Development

```bash
# Run tests
uv run python -m pytest tests/ -v

# Start development server
uv run uvicorn app.main:app --reload

# Test API endpoints
curl http://localhost:8000/v1/health  # Comprehensive health check
curl http://localhost:8000/v1/cache/stats  # Cache statistics
curl -X GET http://localhost:8000/v1/audits/running  # Running audits

# Test audit creation
curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "timeout": 300}'

# Test error handling
curl -X POST http://localhost:8000/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "invalid-url"}'  # Invalid URL test

# Check audit statistics
curl http://localhost:8000/v1/audits/stats

# View API documentation
open http://localhost:8000/docs  # FastAPI auto-generated docs
```

## License

MIT
