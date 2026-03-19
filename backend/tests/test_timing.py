"""Tests for backend/app/timing.py — QueryTimer and timed_fetch."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.timing import QueryTimer, timed_fetch, SLOW_QUERY_MS


class TestQueryTimer:
    """Tests for QueryTimer checkpoint timer."""

    def test_mark_adds_checkpoints(self) -> None:
        qt = QueryTimer("test-route")
        qt.mark("step_a")
        qt.mark("step_b")
        qt.mark("step_c")

        assert len(qt._marks) == 3
        names = [name for name, _ in qt._marks]
        assert names == ["step_a", "step_b", "step_c"]

    def test_log_does_not_raise(self) -> None:
        qt = QueryTimer("test-route")
        qt.mark("step_a")
        qt.mark("step_b")
        # Should complete without exception
        qt.log()

    def test_log_without_marks_does_not_raise(self) -> None:
        qt = QueryTimer("empty-route")
        qt.log()


class TestTimedFetch:
    """Tests for timed_fetch async wrapper."""

    async def test_returns_correct_result(self) -> None:
        expected = [{"id": 1, "name": "test"}]
        mock_method = AsyncMock(return_value=expected)

        result = await timed_fetch("label", mock_method, "SELECT 1")

        assert result == expected

    async def test_calls_method_with_correct_args(self) -> None:
        mock_method = AsyncMock(return_value=None)
        query = "SELECT * FROM users WHERE id = $1 AND active = $2"
        arg1 = 42
        arg2 = True

        await timed_fetch("users", mock_method, query, arg1, arg2)

        mock_method.assert_awaited_once_with(query, arg1, arg2)

    @patch("app.timing.logger")
    async def test_fast_query_does_not_warn(self, mock_logger: MagicMock) -> None:
        mock_method = AsyncMock(return_value=[])

        await timed_fetch("fast", mock_method, "SELECT 1")

        mock_logger.warning.assert_not_called()
        mock_logger.debug.assert_called_once()

    @patch("app.timing.logger")
    async def test_slow_query_warns(self, mock_logger: MagicMock) -> None:
        async def slow_method(query: str, *args: object) -> list[object]:
            await asyncio.sleep(0.25)  # 250ms > SLOW_QUERY_MS (200)
            return []

        await timed_fetch("slow", slow_method, "SELECT pg_sleep(1)")

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "SLOW" in call_args[0][0]
