"""Audit-related Pydantic schemas."""

from typing import Dict, Optional

from pydantic import BaseModel

from app.schemas.common import Rating, Status


# === Lighthouse Models ===


class CategoryScores(BaseModel):
    """Lighthouse category scores (0-1 scale)."""

    performance: float
    accessibility: float
    best_practices: float
    seo: float


class CoreWebVitals(BaseModel):
    """Core Web Vitals from Lighthouse."""

    lcp_ms: Optional[float] = None
    cls: Optional[float] = None
    inp_ms: Optional[float] = None
    tbt_ms: Optional[float] = None


class Opportunity(BaseModel):
    """Lighthouse optimization opportunity."""

    id: str
    title: str
    description: str
    estimated_savings_ms: Optional[float] = None


class LighthouseMetrics(BaseModel):
    """Extracted metrics from Lighthouse report."""

    categories: CategoryScores
    vitals: CoreWebVitals
    opportunities: list[Opportunity]


class LighthouseReport(BaseModel):
    """Lighthouse reports for mobile and desktop."""

    mobile: Optional[LighthouseMetrics] = None
    desktop: Optional[LighthouseMetrics] = None


# === CrUX Models ===


class MetricDistribution(BaseModel):
    """Distribution of users across good/needs-improvement/poor."""

    good: float
    needs_improvement: float
    poor: float


class CrUXMetric(BaseModel):
    """A single CrUX metric."""

    p75: Optional[float] = None
    distribution: Optional[MetricDistribution] = None
    rating: Optional[Rating] = None


class CrUXData(BaseModel):
    """Chrome User Experience Report field data."""

    lcp: Optional[CrUXMetric] = None
    cls: Optional[CrUXMetric] = None
    inp: Optional[CrUXMetric] = None
    fcp: Optional[CrUXMetric] = None
    ttfb: Optional[CrUXMetric] = None
    origin_fallback: bool = False
    overall_rating: Optional[Rating] = None


# === AI Report Models ===


class PerformanceAnalysis(BaseModel):
    """AI-generated performance analysis."""

    mobile_summary: str
    desktop_summary: str
    mobile_vs_desktop: str


class CoreWebVitalsAnalysis(BaseModel):
    """AI-generated CWV analysis."""

    lcp_analysis: str
    cls_analysis: str
    inp_tbt_analysis: str


class CategoryInsights(BaseModel):
    """AI-generated category insights."""

    performance: str
    accessibility: str
    best_practices: str
    seo: str


class AIOpportunity(BaseModel):
    """AI-analyzed opportunity."""

    title: str
    description: str
    estimated_savings: str
    priority: str
    effort: str
    business_impact: str


class AIRecommendation(BaseModel):
    """AI-generated recommendation."""

    priority: int
    title: str
    description: str
    rationale: str
    expected_impact: str
    implementation_complexity: str
    quick_win: bool


class AIReport(BaseModel):
    """Full AI-generated analysis report."""

    executive_summary: str
    performance_analysis: PerformanceAnalysis
    core_web_vitals_analysis: CoreWebVitalsAnalysis
    category_insights: CategoryInsights
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[AIOpportunity]
    recommendations: list[AIRecommendation]
    business_impact_summary: str
    next_steps: list[str]


# === Main Response Models ===


class Insights(BaseModel):
    """Combined insights with metrics and AI report."""

    metrics: LighthouseReport
    ai_report: Optional[AIReport] = None


class AuditResponse(BaseModel):
    """The main audit response returned by the API."""

    status: Status
    url: str
    lighthouse: LighthouseReport
    crux: Optional[CrUXData] = None
    insights: Insights
    error: Optional[str] = None
    timing: Optional[Dict[str, float]] = None  # Performance profiling data


# === Request Models ===


class AuditRequest(BaseModel):
    """Request model for audit endpoint."""

    url: str
    timeout: Optional[int] = 600
    no_cache: Optional[bool] = False
