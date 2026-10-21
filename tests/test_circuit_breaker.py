"""Tests for utils/circuit_breaker.py"""
import pytest
import time
from utils.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError


class TestCircuitBreaker:
    """Test circuit breaker state transitions"""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_call() is True

    def test_closed_to_open(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_call() is False

    def test_open_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_call() is True

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=0.01, half_open_successes=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN  # not yet

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # only 2 failures after reset

    def test_raise_if_open(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.raise_if_open()

    def test_raise_if_closed_does_not_raise(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.raise_if_open()  # should not raise

    def test_get_status(self):
        cb = CircuitBreaker(failure_threshold=3)
        status = cb.get_status()
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
