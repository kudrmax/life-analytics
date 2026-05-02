from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date as date_type, timedelta
from statistics import variance

from app.analytics.correlation_math import (
    CorrelationMethodResult, PearsonMethod,
    fisher_exact_p, BINARY_TYPES,
)
from app.domain.constants import SECONDS_PER_HOUR
from app.analytics.quality import QualityAssessor, QualityIssue
from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
from app.analytics.time_series import TimeSeriesTransform
from app.analytics.value_converter import ValueConverter
from app.analytics.value_fetcher import ValueFetcher
from app.correlation_blacklist import should_skip_pair
from app.domain.enums import MetricType
from app.correlation_config import CorrelationConfig, correlation_config
from app.formula import get_referenced_metric_ids
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.correlation_repository import CorrelationRepository
from app.source_key import (
    AutoSourceType, SourceKey, CALENDAR_OPTION_LABELS, STREAK_TYPES,
)
from app.timing import QueryTimer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CorrelationPairResult:
    """Result of evaluating a single correlation pair — maps 1:1 to correlation_pairs columns."""

    report_id: int
    metric_a_id: int | None
    metric_b_id: int | None
    checkpoint_a_id: int | None
    checkpoint_b_id: int | None
    interval_a_id: int | None
    interval_b_id: int | None
    source_key_a: str
    source_key_b: str
    type_a: str
    type_b: str
    correlation: float
    data_points: int
    lag_days: int
    p_value: float
    quality_issue: str | None
    adjusted_p_value: float | None = None


class CorrelationEngine:
    """Вычисляет корреляционный отчёт: загрузка, построение источников, расчёт пар."""

    _CHECKPOINT_MINMAX_TYPES = {"number", "scale", "duration", "time"}
    _ROLLING_AVG_ELIGIBLE_TYPES = {"number", "scale", "duration", "time"}
    _DELTA_ELIGIBLE_TYPES = {"number", "scale", "duration", "bool"}

    def __init__(
        self,
        repo: CorrelationRepository,
        report_id: int,
        start_date: date_type,
        end_date: date_type,
        config: CorrelationConfig | None = None,
    ) -> None:
        self._repo = repo
        self._report_id = report_id
        self._user_id = repo.user_id
        self._start_date = start_date
        self._end_date = end_date
        self._config = config or correlation_config
        self._method = PearsonMethod()
        self._analytics_repo = AnalyticsRepository(repo.conn, repo.user_id)
        self._fetcher = ValueFetcher(self._analytics_repo)
        self._quality = QualityAssessor(config=self._config)
        self._qt = QueryTimer(f"correlation-report/{report_id}")

        # Internal state populated during run()
        self._metrics_rows: list = []
        self._checkpoints_by_metric: dict[int, list] = defaultdict(list)
        self._intervals_by_metric: dict[int, list] = defaultdict(list)
        self._computed_cfgs: dict = {}
        self._enum_opts_by_metric: dict[int, list] = defaultdict(list)
        self._single_select_metric_ids: set[int] = set()
        self._sources: list[tuple[SourceKey, str]] = []
        self._source_data: dict[int, dict[str, float]] = {}
        self._aggregate_indices: dict[int, int] = {}
        self._computed_source_indices: dict[int, int] = {}
        self._checkpoint_source_indices_by_metric: dict[int, list[int]] = defaultdict(list)
        self._interval_source_indices_by_metric: dict[int, list[int]] = defaultdict(list)
        self._low_var_sources: set[int] = set()
        self._binary_sources: set[int] = set()
        self._streak_sources: set[int] = set()
        self._rolling_avg_sources: set[int] = set()

    async def run(self) -> None:
        """Full pipeline: load → build → fetch → auto → quality → pairs → insert → finalize."""
        await self._load_metrics_and_configs()
        self._build_sources()
        await self._fetch_source_data()
        await self._compute_auto_sources()
        self._precompute_quality_flags()
        pairs = self._evaluate_all_pairs()
        pairs = self._apply_bh_correction(pairs)
        await self._insert_pairs(pairs)
        await self._finalize()

    # ─── Phase 1: Load metrics and configs ─────────────────────────

    async def _load_metrics_and_configs(self) -> None:
        repo = self._repo

        self._metrics_rows = list(await repo.load_enabled_metrics())
        self._qt.mark("load_metrics")

        # Resolve integration types
        for i, m in enumerate(self._metrics_rows):
            if m["type"] == MetricType.integration:
                self._metrics_rows[i] = dict(m)
                self._metrics_rows[i]["type"] = m["ic_value_type"] or MetricType.number

        metric_ids = [m["id"] for m in self._metrics_rows]
        self._metrics_by_id: dict[int, dict] = {m["id"]: m for m in self._metrics_rows}

        # Load checkpoints and intervals
        checkpoint_rows = await repo.load_checkpoints_for_metrics(metric_ids)
        self._qt.mark("load_checkpoints")
        for s in checkpoint_rows:
            self._checkpoints_by_metric[s["metric_id"]].append(s)

        interval_rows = await repo.load_intervals_for_metrics(metric_ids)
        self._qt.mark("load_intervals")
        for s in interval_rows:
            self._intervals_by_metric[s["metric_id"]].append(s)

        # Load computed configs
        computed_ids = [m["id"] for m in self._metrics_rows if m["type"] == MetricType.computed]
        self._computed_cfgs = await repo.load_computed_configs(computed_ids)
        self._qt.mark("load_computed_cfg")

        # Load enum options
        enum_metric_ids = [m["id"] for m in self._metrics_rows if m["type"] == MetricType.enum]
        self._enum_opts_by_metric = await repo.load_enum_options(enum_metric_ids)

        # Identify single-select enums
        ec_by_metric = await repo.load_enum_configs(enum_metric_ids)
        for mid in enum_metric_ids:
            if not ec_by_metric.get(mid, False):
                self._single_select_metric_ids.add(mid)

    # ─── Phase 2: Build sources ────────────────────────────────────

    def _build_sources(self) -> None:
        for m in self._metrics_rows:
            mid = m["id"]
            mt = m["type"]
            if mt == MetricType.text:
                continue
            if mt == MetricType.computed:
                self._sources.append((SourceKey(metric_id=mid), mt))
                continue
            is_checkpoint = bool(m.get("is_checkpoint"))
            metric_checkpoints = self._checkpoints_by_metric.get(mid, [])
            metric_intervals = self._intervals_by_metric.get(mid, [])
            binding = m.get("interval_binding", "all_day")
            if binding in ("free_intervals", "free_checkpoints"):
                metric_intervals = []
                metric_checkpoints = []
            if mt == MetricType.enum:
                opts = self._enum_opts_by_metric.get(mid, [])
                for opt in opts:
                    if is_checkpoint:
                        if len(metric_checkpoints) > 1:
                            self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"]), "enum_bool"))
                        if metric_checkpoints:
                            for s in metric_checkpoints:
                                self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"], checkpoint_id=s["id"]), "enum_bool"))
                        else:
                            self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"]), "enum_bool"))
                    elif metric_intervals:
                        if len(metric_intervals) > 1:
                            self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"]), "enum_bool"))
                        for iv in metric_intervals:
                            self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"], interval_id=iv["id"]), "enum_bool"))
                    else:
                        self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"]), "enum_bool"))
                continue
            if is_checkpoint:
                if metric_checkpoints:
                    if len(metric_checkpoints) > 1:
                        self._sources.append((SourceKey(metric_id=mid), mt))
                    for s in metric_checkpoints:
                        self._sources.append((SourceKey(metric_id=mid, checkpoint_id=s["id"]), mt))
                else:
                    self._sources.append((SourceKey(metric_id=mid), mt))
            elif metric_intervals:
                if len(metric_intervals) > 1:
                    self._sources.append((SourceKey(metric_id=mid), mt))
                for iv in metric_intervals:
                    self._sources.append((SourceKey(metric_id=mid, interval_id=iv["id"]), mt))
            else:
                self._sources.append((SourceKey(metric_id=mid), mt))

    # ─── Phase 3: Fetch data for each source ───────────────────────

    async def _fetch_source_data(self) -> None:
        for i, (sk, mt) in enumerate(self._sources):
            if sk.enum_option_id is not None:
                if sk.interval_id is not None:
                    self._source_data[i] = await self._fetcher.values_by_date_for_enum_option_interval(
                        sk.metric_id, sk.enum_option_id, self._start_date, self._end_date, self._user_id, interval_id=sk.interval_id,
                    )
                else:
                    self._source_data[i] = await self._fetcher.values_by_date_for_enum_option(
                        sk.metric_id, sk.enum_option_id, self._start_date, self._end_date, self._user_id, checkpoint_id=sk.checkpoint_id,
                    )
            elif mt == MetricType.computed:
                cfg = self._computed_cfgs.get(sk.metric_id)
                if cfg and cfg["formula"]:
                    formula = ValueConverter.parse_formula(cfg["formula"])
                    rt = cfg["result_type"] or "float"
                    ref_ids = get_referenced_metric_ids(formula)
                    self._source_data[i] = await self._fetcher.values_by_date_for_computed(
                        formula, rt, ref_ids, self._start_date, self._end_date, self._user_id,
                    )
                else:
                    self._source_data[i] = {}
            elif sk.interval_id is not None:
                self._source_data[i] = await self._fetcher.values_by_date_for_interval(
                    sk.metric_id, mt, self._start_date, self._end_date, self._user_id, interval_id=sk.interval_id,
                )
            else:
                m = self._metrics_by_id.get(sk.metric_id, {})
                fio = m.get("interval_binding") == "free_intervals"
                self._source_data[i] = await self._fetcher.values_by_date_for_checkpoint(
                    sk.metric_id, mt, self._start_date, self._end_date, self._user_id, checkpoint_id=sk.checkpoint_id,
                    free_interval_only=fio,
                )
        self._qt.mark(f"fetch_{len(self._sources)}_sources")

    # ─── Phase 4: Auto sources ─────────────────────────────────────

    async def _compute_auto_sources(self) -> None:
        # Build index maps
        for i, (sk, mt) in enumerate(self._sources):
            if sk.checkpoint_id is None and sk.interval_id is None and mt != MetricType.computed and sk.metric_id is not None:
                self._aggregate_indices[sk.metric_id] = i
            if mt == MetricType.computed and sk.metric_id is not None and not sk.is_auto:
                self._computed_source_indices[sk.metric_id] = i
            if sk.checkpoint_id is not None and sk.metric_id is not None and not sk.is_auto:
                self._checkpoint_source_indices_by_metric[sk.metric_id].append(i)

        # Single-checkpoint metrics: treat per-checkpoint as aggregate for auto-source generation
        for mid, indices in self._checkpoint_source_indices_by_metric.items():
            if len(indices) == 1 and mid not in self._aggregate_indices:
                self._aggregate_indices[mid] = indices[0]

        # Single-interval metrics: treat per-interval as aggregate for auto-source generation
        for i, (sk, mt) in enumerate(self._sources):
            if sk.interval_id is not None and sk.metric_id is not None and not sk.is_auto:
                self._interval_source_indices_by_metric[sk.metric_id].append(i)
        for mid, indices in self._interval_source_indices_by_metric.items():
            if len(indices) == 1 and mid not in self._aggregate_indices:
                self._aggregate_indices[mid] = indices[0]

        self._add_auto_source_definitions()
        await self._compute_auto_source_data()

    def _add_auto_source_definitions(self) -> None:
        _auto = self._config.auto_sources
        for m in self._metrics_rows:
            if m["type"] == MetricType.computed:
                continue
            mid = m["id"]
            if mid not in self._aggregate_indices:
                continue
            if _auto.nonzero and m["type"] in (MetricType.number, MetricType.duration):
                self._sources.append((SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=mid), MetricType.bool))
            has_per_binding_sources = mid in self._checkpoint_source_indices_by_metric or mid in self._interval_source_indices_by_metric
            if m["type"] in self._CHECKPOINT_MINMAX_TYPES and has_per_binding_sources:
                if _auto.checkpoint_max:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=mid), m["type"]))
                if _auto.checkpoint_min:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=mid), m["type"]))

        # Delta, trend, range — only for checkpoint metrics with delta-eligible types
        for m in self._metrics_rows:
            mid = m["id"]
            if not m.get("is_checkpoint"):
                continue
            if m["type"] not in self._DELTA_ELIGIBLE_TYPES:
                continue
            if mid not in self._checkpoint_source_indices_by_metric:
                continue
            sorted_checkpoints = sorted(self._checkpoints_by_metric[mid], key=lambda s: s["sort_order"])
            if _auto.delta:
                for i_cp in range(len(sorted_checkpoints) - 1):
                    self._sources.append((
                        SourceKey(auto_type=AutoSourceType.DELTA, auto_parent_metric_id=mid, auto_option_id=sorted_checkpoints[i_cp]["id"]),
                        m["type"],
                    ))
            if len(sorted_checkpoints) >= 2:
                if _auto.trend:
                    self._sources.append((
                        SourceKey(auto_type=AutoSourceType.TREND, auto_parent_metric_id=mid),
                        m["type"],
                    ))
                if _auto.range:
                    self._sources.append((
                        SourceKey(auto_type=AutoSourceType.RANGE, auto_parent_metric_id=mid),
                        m["type"],
                    ))

        # Free checkpoint auto-sources (max, min, range)
        for m in self._metrics_rows:
            mid = m["id"]
            if m.get("interval_binding") != "free_checkpoints":
                continue
            if mid not in self._aggregate_indices:
                continue
            if m["type"] in self._CHECKPOINT_MINMAX_TYPES:
                if _auto.free_cp_max:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_CP_MAX, auto_parent_metric_id=mid), m["type"]))
                if _auto.free_cp_min:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_CP_MIN, auto_parent_metric_id=mid), m["type"]))
            if m["type"] in self._DELTA_ELIGIBLE_TYPES:
                if _auto.free_cp_range:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_CP_RANGE, auto_parent_metric_id=mid), m["type"]))

        # Free interval auto-sources (max, min, range, count, duration-based)
        for m in self._metrics_rows:
            mid = m["id"]
            if m.get("interval_binding") != "free_intervals":
                continue
            if mid not in self._aggregate_indices:
                continue
            # value-based: max, min
            if m["type"] in self._CHECKPOINT_MINMAX_TYPES:
                if _auto.free_iv_max:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_MAX, auto_parent_metric_id=mid), m["type"]))
                if _auto.free_iv_min:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_MIN, auto_parent_metric_id=mid), m["type"]))
            # range
            if m["type"] in self._DELTA_ELIGIBLE_TYPES:
                if _auto.free_iv_range:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_RANGE, auto_parent_metric_id=mid), m["type"]))
            # count
            if _auto.free_iv_count:
                self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_COUNT, auto_parent_metric_id=mid), MetricType.number))
            # duration-based
            if _auto.free_iv_avg_dur:
                self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_AVG_DUR, auto_parent_metric_id=mid), MetricType.duration))
            if _auto.free_iv_max_dur:
                self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_MAX_DUR, auto_parent_metric_id=mid), MetricType.duration))
            if _auto.free_iv_min_dur:
                self._sources.append((SourceKey(auto_type=AutoSourceType.FREE_IV_MIN_DUR, auto_parent_metric_id=mid), MetricType.duration))

        if _auto.note_count:
            for m in self._metrics_rows:
                if m["type"] == MetricType.text:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=m["id"]), MetricType.number))

        if _auto.rolling_avg:
            _ra_windows = _auto.rolling_avg_windows
            for m in self._metrics_rows:
                mid = m["id"]
                mt = m["type"]
                if mt == MetricType.computed:
                    cfg = self._computed_cfgs.get(mid)
                    if not cfg:
                        continue
                    rt = cfg["result_type"] or "float"
                    if rt in ("float", "int"):
                        resolved = MetricType.number
                    elif rt in (MetricType.time, MetricType.duration):
                        resolved = rt
                    else:
                        continue
                    for w in _ra_windows:
                        self._sources.append((
                            SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=mid, auto_option_id=w),
                            resolved,
                        ))
                elif mt in self._ROLLING_AVG_ELIGIBLE_TYPES and mid in self._aggregate_indices:
                    for w in _ra_windows:
                        self._sources.append((
                            SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=mid, auto_option_id=w),
                            mt,
                        ))

        if _auto.streak:
            for src_idx, (sk, mt) in list(enumerate(self._sources)):
                if mt not in BINARY_TYPES:
                    continue
                if sk.is_auto or sk.checkpoint_id is not None or sk.interval_id is not None:
                    continue
                parent_mid = sk.metric_id
                opt_id = sk.enum_option_id
                self._sources.append((
                    SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=parent_mid, auto_option_id=opt_id),
                    "number",
                ))
                self._sources.append((
                    SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=parent_mid, auto_option_id=opt_id),
                    "number",
                ))

        _CALENDAR_ENABLED = {
            AutoSourceType.DAY_OF_WEEK: _auto.day_of_week,
            AutoSourceType.MONTH: _auto.month,
            AutoSourceType.IS_WORKDAY: _auto.is_workday,
        }
        for cal_type, options in CALENDAR_OPTION_LABELS.items():
            if not _CALENDAR_ENABLED.get(cal_type, True):
                continue
            for opt_id in options:
                self._sources.append((SourceKey(auto_type=cal_type, auto_option_id=opt_id), "enum_bool"))

    async def _compute_auto_source_data(self) -> None:
        all_dates = [str(self._start_date + timedelta(days=i)) for i in range((self._end_date - self._start_date).days + 1)]

        # Pre-fetch DB-dependent auto source data
        _auto = self._config.auto_sources
        aw_data: dict[str, float] | None = None
        if _auto.aw_active:
            aw_rows = await self._analytics_repo.get_aw_active_seconds(self._start_date, self._end_date)
            if aw_rows:
                aw_data = {str(r["date"]): r["active_seconds"] / SECONDS_PER_HOUR for r in aw_rows}

        for idx, (sk, _mt) in enumerate(self._sources):
            if not sk.is_auto or idx in self._source_data:
                continue

            # Delta: special handling with start/end checkpoint data
            if sk.auto_type == AutoSourceType.DELTA:
                start_data = self._get_checkpoint_source_data(sk.auto_parent_metric_id, sk.auto_option_id)
                end_checkpoint_id = self._get_next_checkpoint_id(sk.auto_parent_metric_id, sk.auto_option_id)
                end_data = self._get_checkpoint_source_data(sk.auto_parent_metric_id, end_checkpoint_id) if end_checkpoint_id else {}
                inp = AutoSourceInput(all_dates=all_dates, start_slot_data=start_data, end_slot_data=end_data)
                self._source_data[idx] = compute_auto_source(sk.auto_type, inp)
                continue

            # Free checkpoint auto-sources: load raw values per day
            if sk.auto_type in (AutoSourceType.FREE_CP_MAX, AutoSourceType.FREE_CP_MIN, AutoSourceType.FREE_CP_RANGE):
                mid = sk.auto_parent_metric_id
                if mid is not None:
                    mt = self._metrics_by_id[mid]["type"] if mid in self._metrics_by_id else MetricType.number
                    raw = await self._fetcher.values_list_by_date(mid, mt, self._start_date, self._end_date)
                    inp = AutoSourceInput(all_dates=all_dates, raw_data=raw)
                    self._source_data[idx] = compute_auto_source(sk.auto_type, inp)
                continue

            # Free interval auto-sources: value-based and duration-based
            if sk.auto_type in (
                AutoSourceType.FREE_IV_MAX, AutoSourceType.FREE_IV_MIN,
                AutoSourceType.FREE_IV_RANGE, AutoSourceType.FREE_IV_COUNT,
                AutoSourceType.FREE_IV_AVG_DUR, AutoSourceType.FREE_IV_MAX_DUR,
                AutoSourceType.FREE_IV_MIN_DUR,
            ):
                mid = sk.auto_parent_metric_id
                if mid is not None:
                    mt = self._metrics_by_id[mid]["type"] if mid in self._metrics_by_id else MetricType.number
                    raw = await self._fetcher.values_list_by_date(mid, mt, self._start_date, self._end_date, free_interval_only=True)
                    dur_data: dict[str, list[float]] | None = None
                    if sk.auto_type in (
                        AutoSourceType.FREE_IV_AVG_DUR,
                        AutoSourceType.FREE_IV_MAX_DUR,
                        AutoSourceType.FREE_IV_MIN_DUR,
                    ):
                        dur_data = await self._fetcher.time_ranges_by_date(
                            mid, self._start_date, self._end_date,
                        )
                    inp = AutoSourceInput(all_dates=all_dates, raw_data=raw, duration_data=dur_data)
                    self._source_data[idx] = compute_auto_source(sk.auto_type, inp)
                continue

            # Trend/Range: use ordered checkpoint data
            if sk.auto_type in (AutoSourceType.TREND, AutoSourceType.RANGE):
                checkpoint_data = self._resolve_ordered_checkpoint_data(sk)
                inp = AutoSourceInput(all_dates=all_dates, slot_data=checkpoint_data)
                self._source_data[idx] = compute_auto_source(sk.auto_type, inp)
                continue

            # Prepare input based on auto source type
            parent_data = self._resolve_parent_data(sk, all_dates)
            checkpoint_data = self._resolve_checkpoint_data(sk)

            # DB-dependent sources: use pre-fetched data
            if sk.auto_type == AutoSourceType.NOTE_COUNT:
                parent_data = await self._fetcher.fetch_note_counts(
                    sk.auto_parent_metric_id, self._user_id, self._start_date, self._end_date,
                )
            elif sk.auto_type == AutoSourceType.AW_ACTIVE:
                parent_data = aw_data

            inp = AutoSourceInput(
                all_dates=all_dates,
                parent_data=parent_data,
                slot_data=checkpoint_data,
                option_id=sk.auto_option_id,
            )
            self._source_data[idx] = compute_auto_source(sk.auto_type, inp)

    def _resolve_parent_data(self, sk: SourceKey, all_dates: list[str]) -> dict[str, float] | None:
        """Resolve parent time-series data from engine cache for an auto source."""
        if sk.auto_parent_metric_id is None:
            return None
        if sk.auto_type in STREAK_TYPES and sk.auto_option_id is not None:
            # Streak for enum option — find parent by metric_id + enum_option_id
            for pi, (psk, _) in enumerate(self._sources):
                if (psk.metric_id == sk.auto_parent_metric_id
                        and psk.enum_option_id == sk.auto_option_id
                        and psk.checkpoint_id is None
                        and psk.interval_id is None
                        and not psk.is_auto):
                    return self._source_data.get(pi, {})
            return None
        parent_idx = self._aggregate_indices.get(sk.auto_parent_metric_id)
        if parent_idx is None:
            parent_idx = self._computed_source_indices.get(sk.auto_parent_metric_id)
        if parent_idx is not None:
            return self._source_data.get(parent_idx, {})
        return None

    def _resolve_checkpoint_data(self, sk: SourceKey) -> list[dict[str, float]] | None:
        """Resolve checkpoint time-series data from engine cache for checkpoint_max/checkpoint_min."""
        if sk.auto_type not in (AutoSourceType.CHECKPOINT_MAX, AutoSourceType.CHECKPOINT_MIN):
            return None
        binding_indices = (
            self._checkpoint_source_indices_by_metric.get(sk.auto_parent_metric_id, [])
            or self._interval_source_indices_by_metric.get(sk.auto_parent_metric_id, [])
        )
        if not binding_indices:
            return None
        return [self._source_data.get(si, {}) for si in binding_indices]

    def _get_checkpoint_source_data(self, metric_id: int | None, checkpoint_id: int | None) -> dict[str, float]:
        """Find source_data for a specific checkpoint of a metric."""
        if metric_id is None or checkpoint_id is None:
            return {}
        for si in self._checkpoint_source_indices_by_metric.get(metric_id, []):
            sk, _ = self._sources[si]
            if sk.checkpoint_id == checkpoint_id:
                return self._source_data.get(si, {})
        return {}

    def _get_next_checkpoint_id(self, metric_id: int | None, start_checkpoint_id: int | None) -> int | None:
        """Find checkpoint_id of the next checkpoint after start_checkpoint_id."""
        if metric_id is None or start_checkpoint_id is None:
            return None
        sorted_checkpoints = sorted(self._checkpoints_by_metric[metric_id], key=lambda s: s["sort_order"])
        for i, s in enumerate(sorted_checkpoints):
            if s["id"] == start_checkpoint_id and i + 1 < len(sorted_checkpoints):
                return sorted_checkpoints[i + 1]["id"]
        return None

    def _resolve_ordered_checkpoint_data(self, sk: SourceKey) -> list[dict[str, float]] | None:
        """Resolve checkpoint data ordered by checkpoint sort_order."""
        if sk.auto_parent_metric_id is None:
            return None
        sorted_checkpoints = sorted(self._checkpoints_by_metric[sk.auto_parent_metric_id], key=lambda s: s["sort_order"])
        result = []
        for s in sorted_checkpoints:
            data = self._get_checkpoint_source_data(sk.auto_parent_metric_id, s["id"])
            result.append(data)
        return result if result else None

    # ─── Phase 5: Pre-compute quality flags ────────────────────────

    def _precompute_quality_flags(self) -> None:
        self._streak_sources = {
            idx for idx, (sk, _) in enumerate(self._sources) if sk.auto_type in STREAK_TYPES
        }
        self._rolling_avg_sources = {
            idx for idx, (sk, _) in enumerate(self._sources) if sk.auto_type == AutoSourceType.ROLLING_AVG
        }

        for idx in range(len(self._sources)):
            data = self._source_data.get(idx)
            if not data:
                continue
            vals = list(data.values())
            if len(vals) < 2:
                self._low_var_sources.add(idx)
                continue
            var = variance(vals)
            if var < self._config.thresholds.zero_var_eps:
                self._low_var_sources.add(idx)
                continue
            is_binary = all(v == 0.0 or v == 1.0 for v in vals)
            if is_binary and var <= self._config.thresholds.binary_var_threshold:
                self._low_var_sources.add(idx)

        for idx in range(len(self._sources)):
            if idx in self._low_var_sources:
                continue
            data = self._source_data.get(idx)
            if not data:
                continue
            vals = list(data.values())
            if all(v == 0.0 or v == 1.0 for v in vals):
                self._binary_sources.add(idx)

    # ─── Phase 6: Evaluate all pairs ───────────────────────────────

    def _evaluate_all_pairs(self) -> list[CorrelationPairResult]:
        pairs: list[CorrelationPairResult] = []
        for i in range(len(self._sources)):
            for j in range(i + 1, len(self._sources)):
                sk_i, mt_i = self._sources[i]
                sk_j, mt_j = self._sources[j]
                if should_skip_pair(sk_i, sk_j, self._single_select_metric_ids):
                    continue

                low_var = (i in self._low_var_sources) or (j in self._low_var_sources)
                data_i = self._source_data.get(i, {})
                data_j = self._source_data.get(j, {})
                both_binary = mt_i in BINARY_TYPES and mt_j in BINARY_TYPES

                has_rolling = i in self._rolling_avg_sources or j in self._rolling_avg_sources
                lag_variations: list[tuple] = [(data_i, data_j, sk_i, sk_j, mt_i, mt_j, i, j, 0)]
                if not has_rolling:
                    lag_variations.append((data_i, TimeSeriesTransform.shift_dates(data_j, 1), sk_i, sk_j, mt_i, mt_j, i, j, 1))
                    lag_variations.append((data_j, TimeSeriesTransform.shift_dates(data_i, 1), sk_j, sk_i, mt_j, mt_i, j, i, 1))

                for data_a, data_b, sk_a, sk_b, mt_a, mt_b, idx_a, idx_b, lag in lag_variations:
                    row = self._eval_single_pair(data_a, data_b, sk_a, sk_b, mt_a, mt_b, idx_a, idx_b, lag, low_var, both_binary)
                    if row:
                        pairs.append(row)

        self._qt.mark(f"compute_{len(pairs)}_pairs")
        return pairs

    def _eval_single_pair(
        self,
        data_a: dict[str, float], data_b: dict[str, float],
        sk_a: SourceKey, sk_b: SourceKey, mt_a: str, mt_b: str,
        idx_a: int, idx_b: int, lag: int,
        low_var: bool, both_binary: bool,
    ) -> CorrelationPairResult | None:
        result = self._method.compute(data_a, data_b)
        r, n = result.r, result.n
        if r is None:
            return None
        small_group = self._check_small_binary_group(data_a, data_b, idx_a, idx_b)
        p_val = round(result.p_value, 4)
        wide_ci = (result.ci_lower is not None and result.ci_upper is not None
                   and (result.ci_upper - result.ci_lower) > self._config.thresholds.ci_width)
        fisher_hp = both_binary and fisher_exact_p(data_a, data_b) >= self._config.thresholds.p_value_significance
        streak_reset = self._check_low_streak_resets(data_a, data_b, idx_a, idx_b)
        qi = self._quality.determine_issue(n, p_val, low_variance=low_var, small_binary_group=small_group, wide_ci=wide_ci, fisher_high_p=fisher_hp, low_streak_resets=streak_reset)
        return CorrelationPairResult(
            report_id=self._report_id,
            metric_a_id=sk_a.metric_id, metric_b_id=sk_b.metric_id,
            checkpoint_a_id=sk_a.checkpoint_id, checkpoint_b_id=sk_b.checkpoint_id,
            interval_a_id=sk_a.interval_id, interval_b_id=sk_b.interval_id,
            source_key_a=sk_a.to_str(), source_key_b=sk_b.to_str(),
            type_a=mt_a, type_b=mt_b,
            correlation=r, data_points=n, lag_days=lag, p_value=p_val,
            quality_issue=qi,
        )

    def _check_small_binary_group(
        self,
        data_a: dict[str, float], data_b: dict[str, float],
        idx_a: int, idx_b: int,
    ) -> bool:
        if idx_a not in self._binary_sources and idx_b not in self._binary_sources:
            return False
        common = set(data_a) & set(data_b)
        for idx, data in ((idx_a, data_a), (idx_b, data_b)):
            if idx not in self._binary_sources:
                continue
            count_true = sum(1 for d in common if data.get(d) == 1.0)
            count_false = len(common) - count_true
            if min(count_true, count_false) < self._config.thresholds.min_binary_group_size:
                return True
        return False

    def _check_low_streak_resets(
        self,
        data_a: dict[str, float], data_b: dict[str, float],
        idx_a: int, idx_b: int,
    ) -> bool:
        if idx_a not in self._streak_sources and idx_b not in self._streak_sources:
            return False
        common = sorted(set(data_a) & set(data_b))
        if len(common) < 2:
            return False
        min_resets = self._config.quality_filters.low_streak_resets_min_resets
        for idx, data in ((idx_a, data_a), (idx_b, data_b)):
            if idx not in self._streak_sources:
                continue
            vals = [data[d] for d in common]
            drops = sum(1 for i in range(len(vals) - 1) if vals[i] > vals[i + 1])
            if drops < min_resets:
                return True
        return False

    # ─── Phase 7: BH correction ────────────────────────────────────

    @staticmethod
    def _apply_bh_correction(pairs: list[CorrelationPairResult]) -> list[CorrelationPairResult]:
        """Вычислить adjusted p-value (Benjamini–Hochberg) и присвоить fdr_high_p_value."""
        m = len(pairs)
        if m == 0:
            return pairs
        indexed = sorted(enumerate(pairs), key=lambda x: x[1].p_value)
        result = list(pairs)
        _alpha = 0.05
        _fdr = QualityIssue.FDR_HIGH_P_VALUE.value
        _wide_ci = QualityIssue.WIDE_CI.value
        for rank, (orig_idx, _pr) in enumerate(indexed, start=1):
            pr = pairs[orig_idx]
            ap = round(min(pr.p_value * m / rank, 1.0), 4)
            if ap >= _alpha and pr.quality_issue in (None, _wide_ci):
                new_qi = _fdr
            else:
                new_qi = pr.quality_issue
            result[orig_idx] = replace(pr, adjusted_p_value=ap, quality_issue=new_qi)
        return result

    # ─── Phase 8: Insert pairs ─────────────────────────────────────

    async def _insert_pairs(self, pairs: list[CorrelationPairResult]) -> None:
        await self._repo.insert_pairs(pairs)
        self._qt.mark("insert_pairs")

    # ─── Phase 9: Finalize ─────────────────────────────────────────

    async def _finalize(self) -> None:
        await self._repo.finalize_report(self._report_id)
        self._qt.log()


