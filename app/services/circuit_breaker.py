"""Circuit breaker pattern for external service protection."""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5  # Failures before opening circuit
    recovery_timeout: float = 30.0  # Seconds to wait before half-open
    half_open_max_calls: int = 1  # Max test calls in half-open state
    success_threshold: int = 1  # Successes needed to close from half-open


@dataclass
class CircuitBreakerStats:
    """Statistics for a circuit breaker."""

    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: float | None
    last_success_time: float | None
    total_calls: int
    total_failures: int
    total_successes: int
    consecutive_failures: int
    time_in_current_state: float


@dataclass
class CircuitBreaker:
    """
    Circuit breaker implementation for protecting external service calls.

    States:
    - CLOSED: Normal operation. Track failures.
    - OPEN: Service is failing. Fail fast without calling.
    - HALF_OPEN: Testing if service recovered. Allow limited calls.

    Usage:
        breaker = CircuitBreaker("psi_api")

        if breaker.can_execute():
            try:
                result = call_external_service()
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            # Circuit is open, fail fast
            raise ServiceUnavailableError("PSI API circuit is open")
    """

    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _last_failure_time: float | None = field(default=None, init=False)
    _last_success_time: float | None = field(default=None, init=False)
    _state_changed_at: float = field(default_factory=time.time, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # Lifetime statistics
    _total_calls: int = field(default=0, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_successes: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for automatic transitions."""
        with self._lock:
            self._check_state_transition()
            return self._state

    def _check_state_transition(self) -> None:
        """Check if circuit should transition states based on time."""
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        self._state = new_state
        self._state_changed_at = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._half_open_calls = 0

    def can_execute(self) -> bool:
        """
        Check if a call can be made through this circuit breaker.

        Returns True if the call should proceed, False if it should fail fast.
        """
        with self._lock:
            self._check_state_transition()

            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                return False

            # HALF_OPEN: Allow limited test calls
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True

            return False

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            self._last_success_time = time.time()
            self._failure_count = 0  # Reset consecutive failures

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

            elif self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._transition_to(CircuitState.OPEN)

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0

    def get_stats(self) -> CircuitBreakerStats:
        """Get current circuit breaker statistics."""
        with self._lock:
            self._check_state_transition()
            return CircuitBreakerStats(
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                last_failure_time=self._last_failure_time,
                last_success_time=self._last_success_time,
                total_calls=self._total_calls,
                total_failures=self._total_failures,
                total_successes=self._total_successes,
                consecutive_failures=self._failure_count,
                time_in_current_state=time.time() - self._state_changed_at,
            )


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Provides a singleton-like access to circuit breakers by name.
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._breaker_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CircuitBreakerRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_or_create(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        """Get an existing circuit breaker or create a new one."""
        with self._breaker_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name, config=config or CircuitBreakerConfig()
                )
            return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Get a circuit breaker by name, or None if not found."""
        with self._breaker_lock:
            return self._breakers.get(name)

    def get_all_stats(self) -> dict[str, CircuitBreakerStats]:
        """Get statistics for all circuit breakers."""
        with self._breaker_lock:
            return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        with self._breaker_lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def reset(self, name: str) -> bool:
        """Reset a specific circuit breaker. Returns True if found and reset."""
        with self._breaker_lock:
            if name in self._breakers:
                self._breakers[name].reset()
                return True
            return False


# Convenience functions for global access
def get_circuit_breaker(name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    return CircuitBreakerRegistry.get_instance().get_or_create(name, config)


def get_all_circuit_breaker_stats() -> dict[str, CircuitBreakerStats]:
    """Get statistics for all registered circuit breakers."""
    return CircuitBreakerRegistry.get_instance().get_all_stats()


def reset_circuit_breaker(name: str) -> bool:
    """Reset a specific circuit breaker."""
    return CircuitBreakerRegistry.get_instance().reset(name)


def reset_all_circuit_breakers() -> None:
    """Reset all circuit breakers."""
    CircuitBreakerRegistry.get_instance().reset_all()


# Pre-configured circuit breakers for known services
PSI_CIRCUIT_BREAKER = "psi_api"
AI_CIRCUIT_BREAKER = "google_ai"


def get_psi_circuit_breaker() -> CircuitBreaker:
    """Get the PSI API circuit breaker."""
    return get_circuit_breaker(
        PSI_CIRCUIT_BREAKER,
        CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=60.0,  # Wait 1 minute before retrying
            half_open_max_calls=1,
            success_threshold=2,  # Need 2 successes to fully close
        ),
    )


def get_ai_circuit_breaker() -> CircuitBreaker:
    """Get the Google AI API circuit breaker."""
    return get_circuit_breaker(
        AI_CIRCUIT_BREAKER,
        CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=60.0,
            half_open_max_calls=1,
            success_threshold=2,
        ),
    )
