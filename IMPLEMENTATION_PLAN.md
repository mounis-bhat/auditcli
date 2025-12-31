# AuditCLI Implementation Plan

This document outlines the implementation plan for optimizing the AuditCLI tool to make it more robust for server-side integration with SvelteKit. The plan focuses on high-priority reliability improvements, caching with SQLite3, and security enhancements.

## Overview
The optimizations will be implemented in phases, starting with foundational reliability improvements, then adding caching and testing. All changes maintain backward compatibility with the existing CLI interface.

## Phase 1: High Priority - Foundation (Reliability & Performance)

### 1. Enhanced Error Handling ✅ (1-2 days)
- Create custom exception classes in `src/errors.py`
  - `AuditError`: Base exception for audit failures
  - `APIError`: For external API failures (Gemini, PSI)
  - `ValidationError`: For input validation failures
- Add retry logic with exponential backoff for API calls using `tenacity` library
- Implement graceful degradation:
  - If CrUX data unavailable, return partial success with `crux: null`
  - If AI insights fail, return partial success with `ai_report: null`
- Format all errors as structured JSON in `main.py`

### 2. Input Validation ✅ (0.5-1 day)
- Add comprehensive URL validation in `main.py`:
  - Use `urllib.parse` to normalize URLs
  - Require http/https protocols
  - Basic domain validation
- Validate API keys on startup:
  - Check presence in environment variables
  - Basic format validation (non-empty, expected patterns)
- Add `--validate-only` flag for pre-flight validation
- Return user-friendly error messages instead of crashes

### 3. Performance Optimization ✅ (1-2 days)
- Add configurable timeouts via `--timeout` flag (default 10 minutes)
- Implement timeout handling for subprocess calls
- Optimize API call patterns (sequential, no async complexity)
- Add basic profiling to identify bottlenecks

## Phase 2: Medium Priority - Scalability & Security

### 4. Caching with SQLite3 ✅ (2-3 days)
- Create `src/cache.py` module with SQLite database (`audit_cache.db`)
- Database schema:
  ```sql
  CREATE TABLE cache (
    url_hash TEXT PRIMARY KEY,
    normalized_url TEXT,
    result_json TEXT,
    created_at TIMESTAMP,
    ttl_seconds INTEGER
  )
  ```
- Cache by normalized URL hash (SHA256)
- Environment variable `CACHE_TTL_SECONDS` (default 86400 = 1 day)
- Cache operations:
  - Check cache before running full audit
  - Store results on successful completion
  - Add `--no-cache` flag to bypass caching
- Handle cache corruption gracefully (recreate DB if needed)

### 5. Security Hardening (1-2 days)
- Enforce environment variables only for API keys:
  - Remove any fallback to config files
  - Validate keys on startup (presence, basic format)
- Sanitize all outputs to prevent accidental key leakage
- Ensure no sensitive data in JSON responses

### 6. Testing Expansion (2-3 days)
- Unit tests for new modules:
  - `test_errors.py` for exception handling
  - `test_cache.py` for caching logic
  - `test_validation.py` for input validation
- Integration tests with mocked APIs using `responses` library
- CLI end-to-end tests for various scenarios
- Error scenario testing (timeouts, invalid inputs, API failures)

## Phase 3: Integration & Validation (0.5-1 day)
- Update README.md with new flags and options
- Test integration with SvelteKit to ensure no breaking changes
- Document caching behavior and environment variables
- Run full test suite to validate all changes

## Dependencies
- `tenacity`: For retry logic with backoff
- `responses`: For API mocking in tests (existing in some test suites)

## Environment Variables
Add to `.env`:
```
CACHE_TTL_SECONDS=86400  # Cache TTL in seconds (1 day)
```

## CLI Flags
New flags implemented:
- `--timeout SECONDS`: Set audit timeout (default 600) ✅
- `--no-cache`: Skip cache check and don't store results ✅
- `--validate-only`: Validate inputs without running audit ✅

## Risk Assessment
- Low risk: All changes maintain CLI interface compatibility
- Single-server usage eliminates concurrency issues with SQLite
- Sequential processing avoids race conditions

## Success Criteria
- All existing tests pass
- CLI handles errors gracefully without crashes
- Caching reduces redundant API calls
- SvelteKit integration works seamlessly
- No performance regressions

## Timeline
Total estimated effort: 6-11 days
- Phase 1: 3-5 days
- Phase 2: 5-8 days
- Phase 3: 0.5-1 day</content>
<parameter name="filePath">IMPLEMENTATION_PLAN.md