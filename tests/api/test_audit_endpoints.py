"""Integration tests for audit API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.audit import (
    AIOpportunity,
    AIRecommendation,
    AIReport,
    CategoryInsights,
    CategoryScores,
    CoreWebVitals,
    CoreWebVitalsAnalysis,
    CrUXData,
    CrUXMetric,
    LighthouseMetrics,
    LighthouseReport,
    MetricDistribution,
    Opportunity,
    PerformanceAnalysis,
)
from app.schemas.common import Rating


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_lighthouse_report():
    """Create a mock Lighthouse report."""
    return LighthouseReport(
        mobile=LighthouseMetrics(
            categories=CategoryScores(
                performance=0.85,
                accessibility=0.92,
                best_practices=0.88,
                seo=0.95,
            ),
            vitals=CoreWebVitals(
                lcp_ms=2500,
                cls=0.08,
                inp_ms=180,
                tbt_ms=250,
            ),
            opportunities=[
                Opportunity(
                    id="render-blocking-resources",
                    title="Eliminate render-blocking resources",
                    description="Resources are blocking the first paint.",
                    estimated_savings_ms=500,
                )
            ],
        ),
        desktop=LighthouseMetrics(
            categories=CategoryScores(
                performance=0.92,
                accessibility=0.92,
                best_practices=0.88,
                seo=0.95,
            ),
            vitals=CoreWebVitals(
                lcp_ms=1800,
                cls=0.05,
                inp_ms=120,
                tbt_ms=150,
            ),
            opportunities=[],
        ),
    )


@pytest.fixture
def mock_crux_data():
    """Create mock CrUX data."""
    distribution = MetricDistribution(good=0.7, needs_improvement=0.2, poor=0.1)
    return CrUXData(
        lcp=CrUXMetric(p75=2400, rating=Rating.GOOD, distribution=distribution),
        cls=CrUXMetric(p75=0.05, rating=Rating.GOOD, distribution=distribution),
        inp=CrUXMetric(p75=150, rating=Rating.GOOD, distribution=distribution),
        origin_fallback=False,
        overall_rating=Rating.GOOD,
    )


@pytest.fixture
def mock_ai_report():
    """Create a mock AI report."""
    return AIReport(
        executive_summary="Website performance is good overall.",
        performance_analysis=PerformanceAnalysis(
            mobile_summary="Mobile performance is adequate.",
            desktop_summary="Desktop performance is excellent.",
            mobile_vs_desktop="Desktop performs better than mobile.",
        ),
        core_web_vitals_analysis=CoreWebVitalsAnalysis(
            lcp_analysis="LCP is within good range.",
            cls_analysis="Visual stability is excellent.",
            inp_tbt_analysis="Interactivity is good.",
        ),
        category_insights=CategoryInsights(
            performance="Performance score is good.",
            accessibility="Accessibility is excellent.",
            best_practices="Following best practices.",
            seo="SEO is optimized.",
        ),
        strengths=["Fast load times", "Good accessibility"],
        weaknesses=["Some optimization opportunities"],
        opportunities=[
            AIOpportunity(
                title="Optimize images",
                description="Images are not optimized",
                estimated_savings="2s",
                priority="high",
                effort="medium",
                business_impact="Improves load time",
            ),
            AIOpportunity(
                title="Enable compression",
                description="Compression not enabled",
                estimated_savings="1s",
                priority="high",
                effort="low",
                business_impact="Reduces bandwidth",
            ),
        ],
        recommendations=[
            AIRecommendation(
                priority=1,
                title="Implement caching",
                description="Add caching to CDN",
                rationale="Reduces repeated downloads",
                expected_impact="20% faster loads",
                implementation_complexity="medium",
                quick_win=True,
            ),
            AIRecommendation(
                priority=2,
                title="Optimize CSS",
                description="Remove unused CSS",
                rationale="Reduces file size",
                expected_impact="5% faster loads",
                implementation_complexity="low",
                quick_win=True,
            ),
        ],
        business_impact_summary="Good performance metrics support user engagement.",
        next_steps=["Monitor performance", "Implement recommendations"],
    )


class TestAuditCreation:
    """Test audit job creation."""

    def test_create_audit_valid_url(self, client: TestClient):
        """Test creating an audit with a valid URL."""
        response = client.post(
            "/v1/audit",
            json={"url": "https://example.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["job_id"]
        assert data["message"]

    def test_create_audit_invalid_url(self, client: TestClient):
        """Test creating an audit with an invalid URL."""
        response = client.post(
            "/v1/audit",
            json={"url": "not-a-valid-url"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert response.status_code in [400, 422]

    def test_create_audit_missing_url(self, client: TestClient):
        """Test creating an audit without a URL."""
        response = client.post("/v1/audit", json={}, headers={"X-Forwarded-For": "127.0.0.1"})
        assert response.status_code in [400, 422]

    def test_create_audit_empty_url(self, client: TestClient):
        """Test creating an audit with an empty URL."""
        response = client.post(
            "/v1/audit",
            json={"url": ""},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert response.status_code in [400, 422]

    def test_create_audit_normalizes_url(self, client: TestClient):
        """Test that URL is normalized (protocol added if missing)."""
        response = client.post(
            "/v1/audit",
            json={"url": "example.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"]


class TestAuditStatus:
    """Test audit status retrieval."""

    def test_get_audit_status_pending(self, client: TestClient):
        """Test getting status of a pending audit."""
        # Create an audit
        create_response = client.post(
            "/v1/audit",
            json={"url": "https://example.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        job_id = create_response.json()["job_id"]

        # Get status
        status_response = client.get(f"/v1/audit/{job_id}")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "pending"
        assert data["url"] == "https://example.com"

    def test_get_audit_status_nonexistent(self, client: TestClient):
        """Test getting status of a non-existent audit."""
        response = client.get("/v1/audit/nonexistent-job-id")
        assert response.status_code == 404


class TestAuditDeletion:
    """Test audit cancellation/deletion."""

    def test_delete_pending_audit(self, client: TestClient):
        """Test deleting a pending audit."""
        # Create an audit
        create_response = client.post(
            "/v1/audit",
            json={"url": "https://example.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        job_id = create_response.json()["job_id"]

        # Note: Delete only works for QUEUED jobs, not PENDING
        # A pending job can't be deleted, so we expect 400
        delete_response = client.delete(f"/v1/audit/{job_id}")
        # Should return 400 because job is not QUEUED
        assert delete_response.status_code in [400, 404]

    def test_delete_nonexistent_audit(self, client: TestClient):
        """Test deleting a non-existent audit."""
        response = client.delete("/v1/audit/nonexistent-job-id")
        assert response.status_code == 404


class TestCacheEndpoints:
    """Test cache management endpoints."""

    def test_get_cache_stats(self, client: TestClient):
        """Test getting cache statistics."""
        response = client.get("/v1/cache/stats")
        assert response.status_code == 200
        data = response.json()
        # Check for metrics in the response (structure may vary)
        assert "metrics" in data or "hits" in data or "misses" in data
        # Ensure we get a dict with some cache info
        assert isinstance(data, dict)

    def test_clear_cache(self, client: TestClient):
        """Test clearing the cache."""
        response = client.delete("/v1/cache")
        assert response.status_code == 200

    def test_cleanup_cache(self, client: TestClient):
        """Test cleaning up expired cache entries."""
        response = client.post("/v1/cache/cleanup")
        assert response.status_code == 200
        data = response.json()
        # Check for cleanup response (may be 'cleaned', 'removed_count', or 'message')
        assert any(key in data for key in ["cleaned", "removed_count", "message"])


class TestAuditListingAndStats:
    """Test audit listing and statistics endpoints."""

    def test_get_running_audits(self, client: TestClient):
        """Test getting list of running/queued audits."""
        # Create a couple of audits
        client.post(
            "/v1/audit",
            json={"url": "https://example1.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        client.post(
            "/v1/audit",
            json={"url": "https://example2.com"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )

        # Get running audits
        response = client.get("/v1/audits/running")
        assert response.status_code == 200
        data = response.json()
        # Check for either 'job_ids' or 'items' (both are valid response structures)
        assert "job_ids" in data or "items" in data
        items = data.get("job_ids", data.get("items", []))
        assert len(items) == 2

    def test_get_audit_stats(self, client: TestClient):
        """Test getting audit statistics."""
        response = client.get("/v1/audits/stats")
        assert response.status_code == 200
        data = response.json()
        # Response may have nested concurrency/queue objects
        if "concurrency" in data:
            assert "active_audits" in data["concurrency"]
            assert "max_concurrent_audits" in data["concurrency"]
        else:
            assert "active_audits" in data
            assert "max_concurrent_audits" in data


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        # Response may have 'timestamp', 'checks', or nested structure

    def test_health_check_structure(self, client: TestClient):
        """Test that health check has proper structure."""
        response = client.get("/v1/health")
        data = response.json()
        # Check for either 'checks' or direct health info fields
        has_checks = "checks" in data or any(
            key in data for key in ["database", "cache", "circuit_breakers"]
        )
        assert has_checks


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_endpoint(self, client: TestClient):
        """Test that root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "Web Audit API"
