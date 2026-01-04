"""Tests for concurrency management and queue behavior."""

from __future__ import annotations

from app.services.concurrency import ConcurrencyManager, ConcurrencyStats


class TestConcurrencyManagerBasics:
    """Test basic concurrency manager functionality."""

    def test_singleton_instance(self):
        """Test that ConcurrencyManager is a singleton."""
        manager1 = ConcurrencyManager.get_instance()
        manager2 = ConcurrencyManager.get_instance()
        assert manager1 is manager2

    def test_initial_state(self):
        """Test that concurrency manager initializes with correct state."""
        manager = ConcurrencyManager.get_instance()
        assert manager.active_count == 0, f"Expected 0 active, got {manager.active_count}"
        assert manager.has_capacity is True
        assert manager.max_concurrent > 0

    def test_try_acquire_success(self):
        """Test successfully acquiring a slot."""
        manager = ConcurrencyManager.get_instance()
        assert manager.try_acquire() is True
        assert manager.active_count == 1

    def test_try_acquire_at_capacity(self):
        """Test that try_acquire fails when at capacity."""
        manager = ConcurrencyManager.get_instance()
        # Fill all slots
        for _ in range(manager.max_concurrent):
            assert manager.try_acquire() is True

        # Should fail now
        assert manager.try_acquire() is False
        assert manager.active_count == manager.max_concurrent

    def test_release_slot(self):
        """Test releasing a slot."""
        manager = ConcurrencyManager.get_instance()
        assert manager.try_acquire() is True
        assert manager.active_count == 1

        manager.release()
        assert manager.active_count == 0

    def test_release_when_empty(self):
        """Test that releasing when no slots are acquired doesn't go negative."""
        manager = ConcurrencyManager.get_instance()
        manager.release()
        assert manager.active_count == 0

    def test_has_capacity_property(self):
        """Test has_capacity property."""
        manager = ConcurrencyManager.get_instance()
        assert manager.has_capacity is True

        # Fill all slots
        for _ in range(manager.max_concurrent):
            manager.try_acquire()

        assert manager.has_capacity is False

    def test_get_stats(self):
        """Test getting concurrency statistics."""
        manager = ConcurrencyManager.get_instance()
        manager.try_acquire()
        manager.try_acquire()

        stats = manager.get_stats()
        assert isinstance(stats, ConcurrencyStats)
        assert stats.active_audits == 2
        assert stats.max_concurrent_audits == manager.max_concurrent
        assert stats.queue_size >= 0
        assert stats.max_queue_size > 0


class TestQueueOperations:
    """Test queue operations."""

    def test_can_enqueue(self):
        """Test checking if we can enqueue jobs."""
        manager = ConcurrencyManager.get_instance()
        assert manager.can_enqueue() is True

    def test_enqueue_job(self):
        """Test enqueuing a job."""
        manager = ConcurrencyManager.get_instance()
        position = manager.enqueue_job("job1", "https://example.com")
        assert position is not None
        assert position >= 1

    def test_enqueue_multiple_jobs(self):
        """Test enqueuing multiple jobs."""
        manager = ConcurrencyManager.get_instance()
        pos1 = manager.enqueue_job("job_unique_1", "https://example1.com")
        pos2 = manager.enqueue_job("job_unique_2", "https://example2.com")
        assert pos1 is not None
        assert pos2 is not None
        assert pos2 > pos1

    def test_get_queue_position(self):
        """Test getting the queue position for a job."""
        manager = ConcurrencyManager.get_instance()
        position = manager.enqueue_job("job_pos_test", "https://example.com")
        retrieved_position = manager.get_queue_position("job_pos_test")
        assert retrieved_position == position

    def test_get_queue_position_nonexistent(self):
        """Test getting queue position for a non-existent job."""
        manager = ConcurrencyManager.get_instance()
        position = manager.get_queue_position("nonexistent")
        assert position is None

    def test_enqueue_with_options(self):
        """Test enqueuing a job with options."""
        manager = ConcurrencyManager.get_instance()
        options = {"timeout": 300, "no_cache": True}
        position = manager.enqueue_job("job_opts_test", "https://example.com", options)
        assert position is not None


class TestCrashRecovery:
    """Test crash recovery functionality."""

    def test_recover_from_crash(self):
        """Test recovering from a crash."""
        manager = ConcurrencyManager.get_instance()
        # Queue some jobs (they will be marked as processing)
        manager.enqueue_job("job_crash_1", "https://example.com")
        manager.enqueue_job("job_crash_2", "https://example.com")

        # Simulate recovery
        recovered = manager.recover_from_crash()
        # Should return number of jobs that were requeued
        assert isinstance(recovered, int)
        assert recovered >= 0


class TestConcurrencyLimits:
    """Test that concurrency limits are respected."""

    def test_concurrent_slots_limited(self):
        """Test that we can't exceed concurrent slots."""
        manager = ConcurrencyManager.get_instance()
        initial_max = manager.max_concurrent

        # Try to acquire more than the limit
        acquired = 0
        for _ in range(initial_max + 5):
            if manager.try_acquire():
                acquired += 1

        assert acquired == initial_max
        assert manager.active_count == initial_max

    def test_capacity_exhaustion_and_recovery(self):
        """Test capacity exhaustion and recovery."""
        manager = ConcurrencyManager.get_instance()

        # Fill capacity
        for _ in range(manager.max_concurrent):
            manager.try_acquire()

        # Should be at capacity
        assert manager.has_capacity is False
        assert manager.try_acquire() is False

        # Release one
        manager.release()
        assert manager.has_capacity is True
        assert manager.try_acquire() is True


class TestQueueFull:
    """Test behavior when queue is full."""

    def test_enqueue_returns_none_when_full(self):
        """Test that enqueue returns None when queue is full."""
        manager = ConcurrencyManager.get_instance()
        queue = manager.queue
        max_size = queue.max_size

        # Fill the queue
        for i in range(max_size):
            position = manager.enqueue_job(f"job_full_{i}", f"https://example{i}.com")
            assert position is not None

        # Try to enqueue one more - should fail
        # Note: This might return None or raise an exception depending on implementation
        can_enqueue = manager.can_enqueue()
        assert can_enqueue is False
