import math
import pytest
from app.threshold import compute_waiting_time


class TestComputeWaitingTime:
    def test_zero_mu_returns_inf(self):
        assert compute_waiting_time(queue_length=5, mu_k=0.0, lambda_=1.0, tau=5.0) == math.inf

    def test_empty_queue_formula(self):
        # queue_length=1 → x=max(1,1)=1 → (1-1)/(2*mu) = 0
        # w = 0 + tau / (1 + exp(mu - lambda))
        # w = 5.0 / (1 + exp(1.0 - 0.5)) = 5.0 / (1 + exp(0.5))
        expected = 5.0 / (1 + math.exp(1.0 - 0.5))
        assert compute_waiting_time(queue_length=1, mu_k=1.0, lambda_=0.5, tau=5.0) == pytest.approx(expected)

    def test_larger_queue_increases_wait(self):
        w_small = compute_waiting_time(queue_length=2, mu_k=1.0, lambda_=0.5, tau=5.0)
        w_large = compute_waiting_time(queue_length=10, mu_k=1.0, lambda_=0.5, tau=5.0)
        assert w_large > w_small

    def test_high_arrival_rate_increases_wait(self):
        w_low = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=0.5, tau=5.0)
        w_high = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=3.0, tau=5.0)
        assert w_high > w_low

    def test_queue_length_zero_treated_as_one(self):
        # queue_length=0 → x=max(0,1)=1 → same as queue_length=1
        w_zero = compute_waiting_time(queue_length=0, mu_k=1.0, lambda_=0.5, tau=5.0)
        w_one = compute_waiting_time(queue_length=1, mu_k=1.0, lambda_=0.5, tau=5.0)
        assert w_zero == pytest.approx(w_one)

    def test_higher_mu_decreases_wait(self):
        w_slow = compute_waiting_time(queue_length=5, mu_k=0.5, lambda_=0.3, tau=5.0)
        w_fast = compute_waiting_time(queue_length=5, mu_k=2.0, lambda_=0.3, tau=5.0)
        assert w_fast < w_slow
