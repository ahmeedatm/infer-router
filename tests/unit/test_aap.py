import pytest
from unittest.mock import AsyncMock, MagicMock
from app.aap import _compare_results, _update_accuracy_window


class TestCompareResults:
    def test_both_none_is_match(self):
        assert _compare_results(None, None) is True

    def test_gold_none_candidate_present_is_mismatch(self):
        assert _compare_results(None, {"class": "cat"}) is False

    def test_gold_present_candidate_none_is_mismatch(self):
        assert _compare_results({"class": "cat"}, None) is False

    def test_both_present_is_match(self):
        # Current PoC implementation: any two non-None results count as a match.
        assert _compare_results({"class": "cat"}, {"class": "dog"}) is True

    def test_both_present_same_value_is_match(self):
        assert _compare_results({"class": "cat"}, {"class": "cat"}) is True


class TestUpdateAccuracyWindow:
    def _make_redis_mock(self, lrange_return: list) -> AsyncMock:
        """Build a Redis AsyncMock with a properly wired async context manager pipeline."""
        mock_pipe = AsyncMock()
        # Wire the async context manager protocol on the pipeline object itself.
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        # pipeline() is a regular (sync) call that returns the context manager object.
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.lrange = AsyncMock(return_value=lrange_return)
        return mock_redis

    @pytest.mark.asyncio
    async def test_stores_accuracy_in_redis(self):
        mock_redis = self._make_redis_mock([b"1", b"1"])

        await _update_accuracy_window(mock_redis, "Fast-Model", match=True, window=10)

        mock_redis.set.assert_called_once()
        set_args = mock_redis.set.call_args[0]
        assert "accuracy:Fast-Model" in set_args[0]
        assert set_args[1] == "1.0"

    @pytest.mark.asyncio
    async def test_partial_accuracy(self):
        # 1 match out of 2 = 0.5 accuracy
        mock_redis = self._make_redis_mock([b"1", b"0"])

        await _update_accuracy_window(mock_redis, "Fast-Model", match=False, window=10)

        set_args = mock_redis.set.call_args[0]
        assert set_args[1] == "0.5"
