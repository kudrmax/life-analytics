"""Service layer for correlation reports and pair charts — extracted from AnalyticsService."""

import asyncio
import logging
from datetime import date as date_type, timedelta

from app import database as _db_module
from app.analytics.correlation_math import PearsonMethod
from app.analytics.pair_formatter import PairFormatter
from app.analytics.source_reconstructor import SourceReconstructor
from app.analytics.time_series import TimeSeriesTransform
from app.analytics.value_converter import ValueConverter
from app.analytics.value_fetcher import ValueFetcher
from app.correlation_config import CorrelationConfig, correlation_config
from app.domain.enums import MetricType
from app.formula import get_referenced_metric_ids
from app.domain.privacy import is_blocked, PRIVATE_MASK
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.correlation_repository import CorrelationRepository
from app.services.daily_helpers import build_interval_label_map
from app.source_key import SourceKey, STREAK_TYPES

logger = logging.getLogger(__name__)


class CorrelationService:
    def __init__(self, repo: AnalyticsRepository, conn) -> None:
        self.repo = repo
        self.conn = conn
        self.user_id = repo.user_id

    async def pairwise(self, metric_a: int, metric_b: int, start: str, end: str) -> dict:
        ma = await self.repo.get_metric_with_computed_config(metric_a)
        mb = await self.repo.get_metric_with_computed_config(metric_b)
        if not ma or not mb:
            return {"error": "Metric not found"}

        start_date = date_type.fromisoformat(start)
        end_date = date_type.fromisoformat(end)
        fetcher = ValueFetcher(self.repo)

        a_by_date = await self._fetch_values(fetcher, ma, metric_a, start_date, end_date)
        b_by_date = await self._fetch_values(fetcher, mb, metric_b, start_date, end_date)

        result = PearsonMethod().compute(a_by_date, b_by_date)
        if result.r is None:
            return {"metric_a": metric_a, "metric_b": metric_b, "correlation": None,
                    "message": "Not enough data (need at least 3 common days)"}
        common = sorted(set(a_by_date) & set(b_by_date))
        return {
            "metric_a": metric_a, "metric_b": metric_b,
            "correlation": result.r, "data_points": result.n,
            "pairs": [{"date": d, "a": round(a_by_date[d], 2), "b": round(b_by_date[d], 2)} for d in common],
        }

    async def create_report(self, start: str, end: str, config) -> dict:
        start_date = date_type.fromisoformat(start)
        end_date = date_type.fromisoformat(end)
        report_id = await self.repo.create_report(start_date, end_date)
        asyncio.create_task(run_correlation_report(report_id, self.user_id, start, end, config=config))
        return {"report_id": report_id, "status": "running"}

    async def get_latest_report(self) -> dict:
        rows = await self.repo.get_all_reports()
        if not rows:
            return {"running": None, "report": None}
        running = None
        done_row = None
        for r in rows:
            if r["status"] == "running" and running is None:
                running = {"id": r["id"], "status": "running", "created_at": r["created_at"].isoformat()}
            elif r["status"] == "done" and done_row is None:
                done_row = r
        report = None
        if done_row:
            counts_row = await self.repo.get_report_pair_counts(
                done_row["id"], thresholds=correlation_config.thresholds,
            )
            report = {
                "id": done_row["id"], "status": "done",
                "period_start": str(done_row["period_start"]), "period_end": str(done_row["period_end"]),
                "created_at": done_row["created_at"].isoformat(),
                "counts": {k: counts_row[k] for k in ("total", "sig_strong", "sig_medium", "sig_weak", "maybe", "insig")},
            }
        return {"running": running, "report": report}

    async def get_pairs(
        self, report_id: int, category: str, offset: int, limit: int,
        metric_ids_str: str | None, privacy_mode: bool,
    ) -> dict:
        report_row = await self.repo.get_report_owned(report_id)
        if not report_row:
            return {"pairs": [], "total": 0, "has_more": False}

        cat_filter = PairFormatter.category_filter_sql(category, correlation_config.thresholds)
        metric_filter = ""
        args_base: list = [report_id]
        if metric_ids_str:
            ids_list = [int(x) for x in metric_ids_str.split(",") if x.strip()]
            if ids_list:
                idx = len(args_base) + 1
                metric_filter = f" AND cp.metric_a_id = ANY(${idx}::int[]) AND cp.metric_b_id = ANY(${idx}::int[])"
                args_base.append(ids_list)

        total = await self.repo.count_pairs(report_id, cat_filter, metric_filter, args_base)
        pairs = await self.repo.fetch_pairs_page(report_id, cat_filter, metric_filter, args_base, limit, offset)

        all_parent_ids, all_enum_ids = self._collect_source_key_ids(pairs)
        metric_icons, parent_names = await self._batch_load_parents(all_parent_ids)
        enum_labels = await self.repo.get_enum_labels(list(all_enum_ids))

        all_mids: set[int] = set()
        for p in pairs:
            for mid in (p["metric_a_id"], p["metric_b_id"]):
                if mid is not None:
                    all_mids.add(mid)
        mws = await self.repo.get_metrics_with_multiple_slots(list(all_mids))

        # Load slot labels and ordering for delta display labels
        slot_labels, slot_ordering = await self._load_slot_info(list(all_mids | all_parent_ids))

        return {
            "pairs": [PairFormatter(
                metric_icons=metric_icons, enum_labels=enum_labels,
                parent_names=parent_names, privacy_mode=privacy_mode,
                metrics_with_slots=mws,
                slot_labels=slot_labels, slot_ordering=slot_ordering,
            ).format_pair(p) for p in pairs],
            "total": total, "has_more": offset + limit < total,
        }

    async def pair_chart(self, pair_id: int, privacy_mode: bool) -> dict:
        row = await self.repo.get_pair_with_report(pair_id)
        if not row or row["user_id"] != self.user_id:
            return {"dates": [], "values_a": [], "values_b": []}

        priv_a = await self.repo.get_metric_privacy(row["metric_a_id"]) if row["metric_a_id"] else False
        priv_b = await self.repo.get_metric_privacy(row["metric_b_id"]) if row["metric_b_id"] else False
        blocked_a, blocked_b = is_blocked(priv_a, privacy_mode), is_blocked(priv_b, privacy_mode)

        recon = SourceReconstructor(self.repo)
        data_a = await recon.reconstruct(row["source_key_a"], row["type_a"], row["period_start"], row["period_end"], self.user_id)
        data_b = await recon.reconstruct(row["source_key_b"], row["type_b"], row["period_start"], row["period_end"], self.user_id)

        lag = row["lag_days"] or 0
        if lag > 0:
            data_b = TimeSeriesTransform.shift_dates(data_b, lag)
        common = sorted(set(data_a) & set(data_b))

        type_a, type_b = row["type_a"], row["type_b"]
        if type_a == MetricType.computed and row["metric_a_id"]:
            rt = await self.repo.get_computed_result_type(row["metric_a_id"])
            if rt:
                type_a = rt
        if type_b == MetricType.computed and row["metric_b_id"]:
            rt = await self.repo.get_computed_result_type(row["metric_b_id"])
            if rt:
                type_b = rt

        original_dates_b = [str(date_type.fromisoformat(d) - timedelta(days=lag)) for d in common] if lag > 0 else None

        sk_a, sk_b = SourceKey.parse(row["source_key_a"]), SourceKey.parse(row["source_key_b"])
        parent_ids = {mid for mid in (sk_a.auto_parent_metric_id, sk_b.auto_parent_metric_id) if mid is not None}
        parent_names: dict[int, str] = {}
        if parent_ids:
            pm_rows = await self.repo.get_metric_names_icons(list(parent_ids))
            parent_names = {r["id"]: r["name"] for r in pm_rows}

        ma_name = await self.repo.get_metric_name(row["metric_a_id"]) if row["metric_a_id"] else None
        mb_name = await self.repo.get_metric_name(row["metric_b_id"]) if row["metric_b_id"] else None
        all_chart_mids = [mid for mid in (row["metric_a_id"], row["metric_b_id"]) if mid]
        all_chart_mids += list(parent_ids)
        chart_mws = await self.repo.get_metrics_with_multiple_slots(all_chart_mids)
        slot_labels, slot_ordering = await self._load_slot_info(all_chart_mids)

        label_a = PRIVATE_MASK if blocked_a else PairFormatter.build_display_label(
            row["source_key_a"], ma_name, parent_names.get(sk_a.auto_parent_metric_id),
            metric_type=type_a, has_slots=(row["metric_a_id"] in chart_mws if row["metric_a_id"] else False),
            slot_labels=slot_labels, slot_ordering=slot_ordering)
        label_b = PRIVATE_MASK if blocked_b else PairFormatter.build_display_label(
            row["source_key_b"], mb_name, parent_names.get(sk_b.auto_parent_metric_id),
            metric_type=type_b, has_slots=(row["metric_b_id"] in chart_mws if row["metric_b_id"] else False),
            slot_labels=slot_labels, slot_ordering=slot_ordering)

        return {
            "dates": common if not (blocked_a or blocked_b) else [],
            "values_a": [data_a[d] for d in common] if not blocked_a else [],
            "values_b": [data_b[d] for d in common] if not blocked_b else [],
            "type_a": type_a, "type_b": type_b, "label_a": label_a, "label_b": label_b,
            "correlation": row["correlation"], "lag_days": lag,
            "original_dates_b": original_dates_b if not (blocked_a or blocked_b) else None,
        }

    # ── Helpers ───────────────────────────────────────────────────

    async def _fetch_values(self, fetcher, metric, metric_id, start_date, end_date) -> dict:
        if metric["type"] == MetricType.computed:
            formula = ValueConverter.parse_formula(metric.get("formula"))
            ref_ids = get_referenced_metric_ids(formula)
            return await fetcher.values_by_date_for_computed(
                formula, metric.get("result_type") or "float", ref_ids, start_date, end_date, self.user_id)
        return await fetcher.values_by_date_for_slot(metric_id, metric["type"], start_date, end_date, self.user_id)

    @staticmethod
    def _collect_source_key_ids(pairs) -> tuple[set[int], set[int]]:
        parent_ids: set[int] = set()
        enum_ids: set[int] = set()
        for p in pairs:
            for key_col in ("source_key_a", "source_key_b"):
                sk = SourceKey.parse(p[key_col])
                if sk.auto_parent_metric_id is not None:
                    parent_ids.add(sk.auto_parent_metric_id)
                if sk.enum_option_id is not None:
                    enum_ids.add(sk.enum_option_id)
                if sk.auto_type in STREAK_TYPES and sk.auto_option_id is not None:
                    enum_ids.add(sk.auto_option_id)
        return parent_ids, enum_ids

    async def _load_slot_info(self, metric_ids: list[int]) -> tuple[dict[int, str], dict[int, list[int]]]:
        """Load slot labels and ordering for metrics (for delta display labels)."""
        if not metric_ids:
            return {}, {}
        rows = await self.conn.fetch(
            """SELECT ms.id, ms.label, ms.sort_order, msl.metric_id
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = ANY($1) AND msl.enabled = TRUE
               ORDER BY msl.metric_id, ms.sort_order""",
            list(set(metric_ids)),
        )
        labels: dict[int, str] = {}
        ordering: dict[int, list[int]] = {}
        for r in rows:
            labels[r["id"]] = r["label"]
            ordering.setdefault(r["metric_id"], []).append(r["id"])

        # Replace slot labels with interval labels for interval-bound metrics
        interval_mids = await self.conn.fetch(
            """SELECT id FROM metric_definitions
               WHERE id = ANY($1) AND interval_binding IN ('fixed', 'floating')""",
            list(set(metric_ids)),
        )
        if interval_mids:
            all_user_slots = await self.conn.fetch(
                "SELECT id, label, sort_order FROM measurement_slots WHERE user_id = $1 ORDER BY sort_order",
                self.user_id,
            )
            interval_labels = build_interval_label_map([dict(s) for s in all_user_slots])
            interval_mid_set = {r["id"] for r in interval_mids}
            for mid in interval_mid_set:
                for slot_id in ordering.get(mid, []):
                    if slot_id in interval_labels:
                        labels[slot_id] = interval_labels[slot_id]

        return labels, ordering

    async def _batch_load_parents(self, parent_ids: set[int]) -> tuple[dict, dict]:
        icons: dict[int, str] = {}
        names: dict[int, str] = {}
        if parent_ids:
            rows = await self.repo.get_metric_names_icons(list(parent_ids))
            for r in rows:
                names[r["id"]] = r["name"]
                if r["icon"]:
                    icons[r["id"]] = r["icon"]
        return icons, names


async def run_correlation_report(
    report_id: int, user_id: int, start: str, end: str,
    config: CorrelationConfig | None = None,
) -> None:
    """Top-level entry point for asyncio.create_task. Acquires connection and runs engine."""
    from app.analytics.correlation_engine import CorrelationEngine

    try:
        async with _db_module.pool.acquire() as conn:
            repo = CorrelationRepository(conn, user_id)
            engine = CorrelationEngine(
                repo, report_id,
                date_type.fromisoformat(start),
                date_type.fromisoformat(end),
                config=config,
            )
            await engine.run()
    except Exception:
        logger.exception("Error computing correlation report %s", report_id)
        try:
            async with _db_module.pool.acquire() as conn:
                repo = CorrelationRepository(conn, user_id)
                await repo.mark_report_error(report_id)
        except Exception:
            logger.exception("Failed to update report status to error")
