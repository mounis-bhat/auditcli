# AuditCLI Concurrency Improvements

This document outlines planned improvements to enhance the performance, stability, and scalability of running multiple audits concurrently.

## Current State Assessment

### Concurrency Support
The system can run multiple audits concurrently using FastAPI's background tasks and `asyncio.to_thread()`. Each audit executes synchronously in its own thread from the default asyncio thread pool.

### Limitations
- **Resource Contention**: Each Lighthouse audit spawns 2 headless Chrome instances via subprocess calls. Multiple concurrent audits create excessive Chrome processes, consuming CPU and memory.
- **No Concurrency Limits**: Beyond per-IP rate limiting (5 jobs), there are no global limits on concurrent audits or Chrome instances.
- **Sequential Processing**: Audit stages (Lighthouse → CrUX → AI) run sequentially within each audit.
- **Cache Inefficiency**: Multiple concurrent requests for the same URL all perform full audits instead of sharing cached results.
- **Thread Safety**: Generally good with locks, but SQLite concurrent writes may cause issues.

## Proposed Improvements

### Priority 1: Concurrency Controls
- **Environment Variables**:
  - `MAX_CONCURRENT_AUDITS` (default: 10)
  - `MAX_CHROME_INSTANCES` (default: 5)
  - `THREAD_POOL_WORKERS` (default: 20)
- **Implementation**: Add semaphores and queues to prevent resource exhaustion
- **Benefits**: Improved stability and predictable resource usage

### Priority 2: Lighthouse Optimization
- **Browser Pooling**: Replace subprocess-based Lighthouse CLI with Python libraries (`pyppeteer` or `playwright`) for reusable browser instances
- **Resource Management**: Maintain a pool of headless Chrome instances to reduce startup overhead
- **Process Monitoring**: Add cleanup and monitoring of Chrome processes
- **Benefits**: 50-80% reduction in Chrome startup time and resource usage

### Priority 3: Parallel Processing
- **Concurrent Stages**: Run Lighthouse mobile/desktop audits in parallel instead of sequentially
- **Async APIs**: Make CrUX and AI API calls async to overlap with CPU-bound operations
- **Custom Executor**: Configure thread pool for better resource utilization
- **Benefits**: Reduced total audit time, better throughput

### Priority 4: Cache Improvements
- **URL Locking**: Prevent duplicate concurrent audits of the same URL with distributed locks
- **SQLite Optimization**: Enable WAL mode for better concurrent write performance
- **Cache Warming**: Implement strategies to preload frequently requested results
- **Benefits**: Eliminate redundant work, improve cache reliability

### Priority 5: Monitoring & Observability
- **Metrics Collection**:
  - Concurrent audit count
  - Active Chrome instance count
  - Cache hit/miss rates
  - Average audit duration
  - Resource usage per audit
- **Health Checks**: Add circuit breakers for external services
- **Performance Profiling**: Built-in timing and bottleneck identification
- **Benefits**: Better operational visibility and issue detection

### Priority 6: Configuration & Deployment
- **Environment Variables**: Update `.env.example` with new concurrency settings
- **Documentation**: Comprehensive deployment and scaling guides
- **Container Limits**: Resource limits for Chrome processes in Docker
- **Benefits**: Easier deployment and scaling

## Tradeoffs and Considerations

### Browser Pooling vs. Isolation
- **Pooling**: Better performance through instance reuse
- **Isolation**: Separate instances prevent cross-audit interference
- **Recommendation**: Implement pooling with configurable isolation levels

### Parallelization Complexity
- **Pros**: Reduced latency and better resource utilization
- **Cons**: More complex error handling and debugging
- **Recommendation**: Start with Lighthouse parallelization, evaluate API async conversion

### Caching Strategy
- **URL Locking**: Prevents waste but adds complexity
- **Distributed**: Required for multi-process deployments
- **Recommendation**: Implement simple in-memory locking initially, expand to Redis later

### Resource Limits
- **Conservative**: Stable but lower throughput
- **Aggressive**: Higher throughput but risk of resource exhaustion
- **Recommendation**: Start conservative, tune based on monitoring data

## Implementation Phases

### Phase 1: Basic Concurrency (1-2 days)
- Add concurrency limits and semaphores
- Implement basic monitoring
- Update configuration

### Phase 2: Lighthouse Optimization (3-5 days)
- Replace subprocess calls with browser library
- Implement instance pooling
- Add process management

### Phase 3: Advanced Features (5-7 days)
- Parallelize audit stages
- Improve caching with locking
- Add comprehensive monitoring

### Phase 4: Production Readiness (2-3 days)
- Performance testing
- Documentation updates
- Deployment configuration

## Success Metrics

- **Throughput**: 2-3x increase in concurrent audit capacity
- **Resource Usage**: 50% reduction in Chrome startup overhead
- **Cache Efficiency**: >90% hit rate for concurrent identical requests
- **Stability**: No resource exhaustion under normal load
- **Latency**: 30-50% reduction in total audit time

## Testing Strategy

- Load testing with various concurrency levels
- Resource monitoring during tests
- Cache performance validation
- Error handling under resource pressure
- Multi-process deployment testing

## Rollback Plan

- Feature flags for all major changes
- Gradual rollout with monitoring
- Quick rollback to subprocess-based Lighthouse if needed
- Configuration-based concurrency limits for easy adjustment