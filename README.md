# AuditCLI

A robust CLI tool that runs Lighthouse audits, fetches CrUX field data, and generates AI-powered insights. Features comprehensive input validation, graceful error handling, configurable timeouts, and performance profiling. Returns everything as structured JSON for easy integration.

**Current Status**: Phase 1 Complete ✅ - Foundation reliability and performance optimizations implemented. Ready for server-side integration.

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
- [jq](https://jqlang.github.io/jq/) (optional, for pretty-printing JSON)

## Environment Variables

Create a `.env` file:

```env
GOOGLE_API_KEY=your_gemini_key_here  # For AI insights
PSI_API_KEY=your_psi_key_here        # For CrUX field data
CACHE_TTL_SECONDS=86400              # Cache TTL in seconds (default: 86400 = 1 day)
```

### Getting API Keys

- **Gemini API Key**: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **PSI API Key**: Get from [Google Cloud Console](https://developers.google.com/speed/docs/insights/v5/get-started)

## Quick Start

1. **Install dependencies**: `uv sync`
2. **Set up API keys** in `.env` file
3. **Test validation**: `uv run auditcli --validate-only https://example.com`
4. **Run your first audit**: `uv run auditcli https://yourwebsite.com | jq`

## Usage

### Command Line Flags

```bash
uv run auditcli [OPTIONS] [URL]

Options:
  --timeout SECONDS    Audit timeout in seconds (default: 600 = 10 minutes)
  --no-cache          Skip cache check and don't store results
  --validate-only      Validate inputs without running audit
  --help, -h          Show help message and exit
```

### Examples

```bash
# Run audit with default settings
uv run auditcli https://mounis.net

# Run audit with custom timeout (5 minutes)
uv run auditcli --timeout 300 https://mounis.net

# Validate inputs without running expensive audit
uv run auditcli --validate-only https://example.com

# Get help
uv run auditcli --help

# Pretty print with jq
uv run auditcli https://mounis.net | jq

# Extract specific data
uv run auditcli https://mounis.net | jq '.lighthouse.mobile.categories'
uv run auditcli https://mounis.net | jq '.insights.ai_report.executive_summary'
uv run auditcli https://mounis.net | jq '.timing'  # Performance profiling data
```

## Output

The tool outputs a single JSON object to stdout:

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

| Status     | Description                                                     |
| ---------- | --------------------------------------------------------------- |
| `success`  | Everything worked (Lighthouse + CrUX + AI)                      |
| `partial`  | Lighthouse worked but CrUX or AI failed (null for failed parts) |
| `failed`   | Lighthouse failed or validation/API errors                      |

### Performance Timing

The `timing` field provides execution time (in seconds) for each audit component:

- `lighthouse`: Time spent running Lighthouse audits (mobile + desktop)
- `crux`: Time spent fetching Chrome User Experience Report data
- `ai`: Time spent generating AI analysis report

This helps identify performance bottlenecks in the audit process.

### Error Response

```json
{
  "status": "failed",
  "error": "Error message here"
}
```

### Validation Response

When using `--validate-only`, successful validation returns:

```json
{
  "status": "success",
  "message": "Validation successful",
  "validated_url": "https://example.com"
}
```

### Validation Errors

Missing API keys or invalid inputs return structured errors:

```json
{
  "status": "failed",
  "error": "Validation error: PSI_API_KEY environment variable is required and must be non-empty"
}
```

## Caching

Audit results are automatically cached in SQLite (`audit_cache.db`) to improve performance and reduce API calls:

- **Automatic Caching**: Successful audits are cached for 24 hours (configurable)
- **Cache TTL**: Set `CACHE_TTL_SECONDS` environment variable (default: 86400 = 1 day)
- **Bypass Cache**: Use `--no-cache` flag to skip cache check and force fresh audit
- **SHA256 Hashing**: URLs are hashed for efficient lookups and privacy
- **Graceful Handling**: Cache corruption is automatically detected and database is recreated

### Cache Examples

```bash
# Use cached results (default behavior)
uv run auditcli https://example.com

# Force fresh audit, don't cache result
uv run auditcli --no-cache https://example.com

# Check cache statistics
uv run python -c "from src.cache import get_cache_stats; import json; print(json.dumps(get_cache_stats(), indent=2))"
```

## Validation & Error Handling

The CLI performs comprehensive validation:

- **API Keys**: Validates presence and basic format of `GOOGLE_API_KEY` and `PSI_API_KEY`
- **URLs**: Normalizes URLs, enforces http/https protocols, validates domain format
- **Pre-flight Check**: Use `--validate-only` to validate inputs without running expensive audits
- **Graceful Degradation**: Partial failures return `status: "partial"` with available data
- **Structured Errors**: All errors return consistent JSON format, never crash

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

### ✅ Phase 1: Foundation (Implemented)
- **Enhanced Error Handling**: Custom exceptions, retry logic with exponential backoff, graceful degradation
- **Input Validation**: Comprehensive URL and API key validation with `--validate-only` pre-flight checks
- **Performance Optimization**: Configurable timeouts (`--timeout` flag), subprocess timeout handling, performance profiling

### ✅ Phase 2: Scalability & Security (Partially Implemented)
- **SQLite Caching**: ✅ Reduce redundant API calls with configurable TTL caching
- **Security Hardening**: Environment variable enforcement, output sanitization
- **Testing Expansion**: Unit tests, integration tests, error scenario coverage

### 🔮 Phase 3: Integration & Validation
- **Documentation Updates**: Comprehensive docs for production deployment
- **SvelteKit Integration**: Seamless server-side integration examples

## Integration

For integrating with a SvelteKit application, see [SVELTEKIT_INTEGRATION.md](./SVELTEKIT_INTEGRATION.md).

## Development

```bash
# Run tests
uv run python -m pytest tests/ -v

# Test validation
uv run auditcli --validate-only https://example.com
uv run auditcli --validate-only invalid-url

# Test timeout functionality
uv run auditcli --timeout 30 --validate-only https://example.com  # Fast validation
uv run auditcli --timeout 1200 https://example.com                # Extended timeout

# Run a test audit
uv run auditcli https://mounis.net | jq '.status'

# Test error handling
PSI_API_KEY="" uv run auditcli https://example.com
uv run auditcli                           # Missing URL test
uv run auditcli invalid://url             # Invalid URL test

# Check performance timing
uv run auditcli https://example.com | jq '.timing'
```

## License

MIT
