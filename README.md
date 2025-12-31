# AuditCLI

A simple CLI tool that runs Lighthouse audits, fetches CrUX field data, and generates AI-powered insights. Returns everything as JSON.

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
- Google Gemini API key (for AI insights)
- Google PageSpeed Insights API key (for CrUX field data)
- [jq](https://jqlang.github.io/jq/) (optional, for pretty-printing JSON)

## Environment Variables

Create a `.env` file:

```env
GOOGLE_API_KEY=your_gemini_key_here  # For AI insights
PSI_API_KEY=your_psi_key_here        # For CrUX field data
```

### Getting API Keys

- **Gemini API Key**: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **PSI API Key**: Get from [Google Cloud Console](https://developers.google.com/speed/docs/insights/v5/get-started)

## Usage

```bash
# Run audit
uv run auditcli <url>

# Example
uv run auditcli https://mounis.net

# With jq for pretty output
uv run auditcli https://mounis.net | jq

# Extract specific fields with jq
uv run auditcli https://mounis.net | jq '.lighthouse.mobile.categories'
uv run auditcli https://mounis.net | jq '.insights.ai_report.executive_summary'
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
  }
}
```

### Status Values

| Status    | Description                                                     |
| --------- | --------------------------------------------------------------- |
| `success` | Everything worked (Lighthouse + CrUX + AI)                      |
| `partial` | Lighthouse worked but CrUX or AI failed (null for failed parts) |
| `failed`  | Lighthouse completely failed                                    |

### Error Response

```json
{
  "status": "failed",
  "url": "https://example.com",
  "error": "Error message here",
  "lighthouse": { "mobile": null, "desktop": null },
  "insights": { "metrics": {...}, "ai_report": null }
}
```

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

## Integration

For integrating with a SvelteKit application, see [SVELTEKIT_INTEGRATION.md](./SVELTEKIT_INTEGRATION.md).

## Development

```bash
# Run tests
uv run python -m pytest tests/ -v

# Run a test audit
uv run auditcli https://mounis.net | jq '.status'
```

## License

MIT
