from __future__ import annotations

from datetime import date as date_type, timedelta


class TimeSeriesTransform:
    """Производные временные ряды: скользящее среднее, стрики, агрегация чекпоинтов."""

    @staticmethod
    def rolling_avg(data: dict[str, float], window: int) -> dict[str, float]:
        """Compute rolling average over a window of days.

        Only produces values for dates where the full window of data is present.
        """
        if not data:
            return {}
        result: dict[str, float] = {}
        for d_str in sorted(data):
            d = date_type.fromisoformat(d_str)
            vals: list[float] = []
            for offset in range(window):
                wd = str(d - timedelta(days=offset))
                if wd in data:
                    vals.append(data[wd])
            if len(vals) == window:
                result[d_str] = sum(vals) / window
        return result

    @staticmethod
    def streak(
        parent_data: dict[str, float],
        all_dates: list[str],
        target_value: bool,
    ) -> dict[str, float]:
        """Compute streak length for consecutive days with target_value (True=1.0 or False=0.0).

        Missing days (no entry) reset the streak to 0.
        Returns only dates where parent has data.
        """
        target = 1.0 if target_value else 0.0
        result: dict[str, float] = {}
        current_streak = 0
        for d in all_dates:
            if d not in parent_data:
                current_streak = 0
                continue
            if parent_data[d] == target:
                current_streak += 1
            else:
                current_streak = 0
            result[d] = float(current_streak)
        return result

    @staticmethod
    def checkpoint_agg(
        checkpoint_indices: list[int],
        source_data: dict[int, dict[str, float]],
        agg_fn: type[max] | type[min],
    ) -> dict[str, float]:
        """Compute max or min across checkpoint sources per date."""
        all_dates: set[str] = set()
        for ci in checkpoint_indices:
            all_dates.update(source_data.get(ci, {}).keys())
        result: dict[str, float] = {}
        for d in all_dates:
            vals = [source_data[ci][d] for ci in checkpoint_indices if d in source_data.get(ci, {})]
            if vals:
                result[d] = agg_fn(vals)
        return result

    @staticmethod
    def shift_dates(data: dict[str, float], days: int) -> dict[str, float]:
        """Shift date keys forward by N days."""
        return {str(date_type.fromisoformat(d) + timedelta(days=days)): v for d, v in data.items()}
