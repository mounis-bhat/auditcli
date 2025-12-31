"""AI report generation using Gemini."""

import json
import os
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.models import (
    AIReport,
    CrUXData,
    LighthouseReport,
)

SYSTEM_PROMPT = """
You are a senior web performance consultant writing a comprehensive website audit report for business stakeholders and technical teams.

Your goal is to provide actionable, insightful analysis that helps stakeholders understand:
1. The current state of their website's performance
2. How it compares to industry standards
3. The business impact of identified issues
4. Clear, prioritized steps to improve

Rules:
- Only reference metrics and facts explicitly provided in the input data
- Do NOT invent numbers, causes, or specific tools unless they directly relate to the data
- If data is missing, acknowledge it and explain what it means
- All recommendations must map to specific issues found in the data
- Use clear language accessible to non-technical stakeholders while including technical details for developers
- Provide context for all metrics (what's good, what's bad, industry standards)
- Focus on business impact: user experience, conversion rates, SEO rankings, bounce rates
- Output must be valid JSON and follow the provided schema exactly
"""

USER_PROMPT_TEMPLATE = """
Analyze this website performance data and create a comprehensive audit report.

Input data:
{input_json}

Context for Core Web Vitals thresholds:
- LCP (Largest Contentful Paint): Good < 2500ms, Needs Improvement 2500-4000ms, Poor > 4000ms
- CLS (Cumulative Layout Shift): Good < 0.1, Needs Improvement 0.1-0.25, Poor > 0.25
- INP (Interaction to Next Paint): Good < 200ms, Needs Improvement 200-500ms, Poor > 500ms
- TBT (Total Blocking Time): Good < 200ms, Needs Improvement 200-600ms, Poor > 600ms

Category score interpretation (0-1 scale):
- 0.9-1.0: Excellent
- 0.5-0.89: Needs Improvement  
- 0-0.49: Poor

Required output JSON schema:
{{
  "executive_summary": "A comprehensive 3-4 paragraph summary covering: 1) Overall website health and key findings, 2) Critical issues requiring immediate attention, 3) Business impact of current performance, 4) High-level improvement roadmap",
  
  "performance_analysis": {{
    "mobile_summary": "2-3 paragraph detailed analysis of mobile performance including all category scores, Core Web Vitals interpretation, and comparison to industry standards",
    "desktop_summary": "2-3 paragraph detailed analysis of desktop performance including all category scores, Core Web Vitals interpretation, and comparison to industry standards",
    "mobile_vs_desktop": "1-2 paragraph comparison explaining the performance gap between mobile and desktop, why it matters, and which platform needs more attention"
  }},
  
  "core_web_vitals_analysis": {{
    "lcp_analysis": "Detailed analysis of LCP performance on both platforms, what's causing issues (if any), and impact on user experience",
    "cls_analysis": "Detailed analysis of CLS performance on both platforms, what it means for visual stability",
    "inp_tbt_analysis": "Detailed analysis of interactivity metrics (INP/TBT), what they mean for user responsiveness"
  }},
  
  "category_insights": {{
    "performance": "Analysis of the performance score and what it indicates about page speed and optimization",
    "accessibility": "Analysis of accessibility score and its importance for inclusive web experience and legal compliance",
    "best_practices": "Analysis of best practices score covering security, modern web standards, and code quality",
    "seo": "Analysis of SEO score and its impact on search engine visibility and organic traffic"
  }},
  
  "strengths": ["List 3-5 specific strengths with context about why they matter"],
  
  "weaknesses": ["List 3-5 specific weaknesses with quantified impact where possible"],
  
  "opportunities": [
    {{
      "title": "Opportunity title",
      "description": "What this optimization involves",
      "estimated_savings": "Time savings in ms if available, or qualitative impact",
      "priority": "High | Medium | Low",
      "effort": "Low | Medium | High",
      "business_impact": "How this affects users, conversions, or SEO"
    }}
  ],
  
  "recommendations": [
    {{
      "priority": 1,
      "title": "Clear, actionable recommendation title",
      "description": "Detailed explanation of what needs to be done",
      "rationale": "Why this matters and what problem it solves",
      "expected_impact": "High | Medium | Low",
      "implementation_complexity": "Low | Medium | High",
      "quick_win": true or false
    }}
  ],
  
  "business_impact_summary": "2-3 paragraph analysis of how current performance affects: 1) User experience and engagement, 2) Search engine rankings and organic traffic, 3) Conversion rates and revenue potential, 4) Brand perception and trust",
  
  "next_steps": ["List of 5-7 immediate, actionable next steps in priority order"]
}}
"""


def _build_ai_input(
    url: str, lighthouse: LighthouseReport, crux: Optional[CrUXData]
) -> Dict[str, Any]:
    """Build input data for AI analysis."""
    return {
        "url": url,
        "lighthouse": lighthouse.model_dump(exclude_none=True),
        "crux": crux.model_dump(exclude_none=True) if crux else None,
    }


def generate_ai_report(
    url: str, lighthouse: LighthouseReport, crux: Optional[CrUXData]
) -> Optional[AIReport]:
    """
    Generate AI analysis report using Gemini.
    Returns None if API key missing or generation fails.
    """
    load_dotenv()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None  # No API key, return None (not an error)

    input_data = _build_ai_input(url, lighthouse, crux)

    try:
        client = genai.Client(api_key=api_key)

        prompt = USER_PROMPT_TEMPLATE.format(
            input_json=json.dumps(input_data, indent=2)
        )

        response = client.models.generate_content(  # type: ignore
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=AIReport,
            ),
        )

        if not response.text:
            return None

        parsed = json.loads(response.text)
        return AIReport.model_validate(parsed)

    except Exception:
        return None  # Generation failed, return None
