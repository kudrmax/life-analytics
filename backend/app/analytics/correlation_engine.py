from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type, timedelta
from statistics import variance

from app.analytics.correlation_math import (
    CorrelationCalculator, p_value_from_r, confidence_interval_from_r,
    fisher_exact_p, BINARY_TYPES,
)
from app.domain.constants import (
    CONFIDENCE_INTERVAL_WIDTH_THRESHOLD,
    P_VALUE_SIGNIFICANCE_THRESHOLD,
    SECONDS_PER_HOUR,
)
from app.analytics.quality import QualityAssessor
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
    slot_a_id: int | None
    slot_b_id: int | None
    source_key_a: str
    source_key_b: str
    type_a: str
    type_b: str
    correlation: float
    data_points: int
    lag_days: int
    p_value: float
    quality_issue: str | None


class CorrelationEngine:
    """Вычисляет корреляционный отчёт: загрузка, построение источников, расчёт пар."""

    _SLOT_MINMAX_TYPES = {"number", "scale", "duration", "time"}
    _ROLLING_AVG_ELIGIBLE_TYPES = {"number", "scale", "duration", "time"}
    _BINARY_VAR_THRESHOLD = 0.10
    _ZERO_VAR_EPS = 1e-9
    _MIN_BINARY_GROUP_SIZE = 5

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
        self._analytics_repo = AnalyticsRepository(repo.conn, repo.user_id)
        self._fetcher = ValueFetcher(self._analytics_repo)
        self._quality = QualityAssessor(config=self._config)
        self._qt = QueryTimer(f"correlation-report/{report_id}")

        # Internal state populated during run()
        self._metrics_rows: list = []
        self._slots_by_metric: dict[int, list] = defaultdict(list)
        self._computed_cfgs: dict = {}
        self._enum_opts_by_metric: dict[int, list] = defaultdict(list)
        self._single_select_metric_ids: set[int] = set()
        self._sources: list[tuple[SourceKey, str]] = []
        self._source_data: dict[int, dict[str, float]] = {}
        self._aggregate_indices: dict[int, int] = {}
        self._computed_source_indices: dict[int, int] = {}
        self._slot_source_indices_by_metric: dict[int, list[int]] = defaultdict(list)
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

        # Load slots
        slots_rows = await repo.load_slots_for_metrics(metric_ids)
        self._qt.mark("load_slots")
        for s in slots_rows:
            self._slots_by_metric[s["metric_id"]].append(s)

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
            if mt == MetricType.enum:
                opts = self._enum_opts_by_metric.get(mid, [])
                metric_slots = self._slots_by_metric.get(mid, [])
                for opt in opts:
                    self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"]), "enum_bool"))
                    if metric_slots:
                        for s in metric_slots:
                            self._sources.append((SourceKey(metric_id=mid, enum_option_id=opt["id"], slot_id=s["id"]), "enum_bool"))
                continue
            metric_slots = self._slots_by_metric.get(mid, [])
            if metric_slots:
                self._sources.append((SourceKey(metric_id=mid), mt))
                for s in metric_slots:
                    self._sources.append((SourceKey(metric_id=mid, slot_id=s["id"]), mt))
            else:
                self._sources.append((SourceKey(metric_id=mid), mt))

    # ─── Phase 3: Fetch data for each source ───────────────────────

    async def _fetch_source_data(self) -> None:
        for i, (sk, mt) in enumerate(self._sources):
            if sk.enum_option_id is not None:
                self._source_data[i] = await self._fetcher.values_by_date_for_enum_option(
                    sk.metric_id, sk.enum_option_id, self._start_date, self._end_date, self._user_id, slot_id=sk.slot_id,
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
            else:
                self._source_data[i] = await self._fetcher.values_by_date_for_slot(
                    sk.metric_id, mt, self._start_date, self._end_date, self._user_id, slot_id=sk.slot_id,
                )
        self._qt.mark(f"fetch_{len(self._sources)}_sources")

    # ─── Phase 4: Auto sources ─────────────────────────────────────

    async def _compute_auto_sources(self) -> None:
        # Build index maps
        for i, (sk, mt) in enumerate(self._sources):
            if sk.slot_id is None and mt != MetricType.computed and sk.metric_id is not None:
                self._aggregate_indices[sk.metric_id] = i
            if mt == MetricType.computed and sk.metric_id is not None and not sk.is_auto:
                self._computed_source_indices[sk.metric_id] = i
            if sk.slot_id is not None and sk.metric_id is not None and not sk.is_auto:
                self._slot_source_indices_by_metric[sk.metric_id].append(i)

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
            if m["type"] in self._SLOT_MINMAX_TYPES and mid in self._slot_source_indices_by_metric:
                if _auto.slot_max:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.SLOT_MAX, auto_parent_metric_id=mid), m["type"]))
                if _auto.slot_min:
                    self._sources.append((SourceKey(auto_type=AutoSourceType.SLOT_MIN, auto_parent_metric_id=mid), m["type"]))

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
                if sk.is_auto or sk.slot_id is not None:
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
        _auto = self._config.auto_sources

        # AW screen time
        aw_rows = [] if not _auto.aw_active else await self._analytics_repo.get_aw_active_seconds(
            self._start_date, self._end_date,
        )
        if aw_rows:
            for idx, (sk, _) in enumerate(self._sources):
                if sk.auto_type == AutoSourceType.AW_ACTIVE:
                    self._source_data[idx] = {str(r["date"]): r["active_seconds"] / SECONDS_PER_HOUR for r in aw_rows}
                    break

        all_dates = [str(self._start_date + timedelta(days=i)) for i in range((self._end_date - self._start_date).days + 1)]

        for idx, (sk, _mt) in enumerate(self._sources):
            if not sk.is_auto or idx in self._source_data:
                continue
            if sk.auto_type == AutoSourceType.NONZERO:
                parent_data = self._source_data[self._aggregate_indices[sk.auto_parent_metric_id]]
                self._source_data[idx] = {d: (1.0 if v > 0 else 0.0) for d, v in parent_data.items()}
            elif sk.auto_type == AutoSourceType.NOTE_COUNT:
                self._source_data[idx] = await self._fetcher.fetch_note_counts(
                    sk.auto_parent_metric_id, self._user_id, self._start_date, self._end_date,
                )
            elif sk.auto_type == AutoSourceType.DAY_OF_WEEK and sk.auto_option_id is not None:
                self._source_data[idx] = {d: (1.0 if date_type.fromisoformat(d).isoweekday() == sk.auto_option_id else 0.0) for d in all_dates}
            elif sk.auto_type == AutoSourceType.MONTH and sk.auto_option_id is not None:
                self._source_data[idx] = {d: (1.0 if date_type.fromisoformat(d).month == sk.auto_option_id else 0.0) for d in all_dates}
            elif sk.auto_type == AutoSourceType.IS_WORKDAY and sk.auto_option_id is not None:
                if sk.auto_option_id == 1:
                    self._source_data[idx] = {d: (1.0 if date_type.fromisoformat(d).isoweekday() <= 5 else 0.0) for d in all_dates}
                else:
                    self._source_data[idx] = {d: (1.0 if date_type.fromisoformat(d).isoweekday() > 5 else 0.0) for d in all_dates}
            elif sk.auto_type in (AutoSourceType.SLOT_MAX, AutoSourceType.SLOT_MIN):
                slot_indices = self._slot_source_indices_by_metric.get(sk.auto_parent_metric_id, [])
                agg_fn = max if sk.auto_type == AutoSourceType.SLOT_MAX else min
                self._source_data[idx] = TimeSeriesTransform.slot_agg(slot_indices, self._source_data, agg_fn) if slot_indices else {}
            elif sk.auto_type == AutoSourceType.ROLLING_AVG and sk.auto_option_id is not None:
                parent_idx = self._aggregate_indices.get(sk.auto_parent_metric_id)
                if parent_idx is None:
                    parent_idx = self._computed_source_indices.get(sk.auto_parent_metric_id)
                self._source_data[idx] = TimeSeriesTransform.rolling_avg(
                    self._source_data.get(parent_idx, {}), sk.auto_option_id,
                ) if parent_idx is not None else {}
            elif sk.auto_type in STREAK_TYPES:
                if sk.auto_option_id is not None:
                    parent_idx = None
                    for pi, (psk, pmt) in enumerate(self._sources):
                        if (psk.metric_id == sk.auto_parent_metric_id
                                and psk.enum_option_id == sk.auto_option_id
                                and psk.slot_id is None
                                and not psk.is_auto):
                            parent_idx = pi
                            break
                else:
                    parent_idx = self._aggregate_indices.get(sk.auto_parent_metric_id)
                if parent_idx is not None:
                    parent_data = self._source_data.get(parent_idx, {})
                    target = sk.auto_type == AutoSourceType.STREAK_TRUE
                    self._source_data[idx] = TimeSeriesTransform.streak(parent_data, all_dates, target)
                else:
                    self._source_data[idx] = {}

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
            if var < self._ZERO_VAR_EPS:
                self._low_var_sources.add(idx)
                continue
            is_binary = all(v == 0.0 or v == 1.0 for v in vals)
            if is_binary and var <= self._BINARY_VAR_THRESHOLD:
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
        calc = CorrelationCalculator(data_a, data_b)
        r, n = calc.pearson()
        if r is None:
            return None
        small_group = self._check_small_binary_group(data_a, data_b, idx_a, idx_b)
        p_val = round(p_value_from_r(r, n), 4)
        ci = confidence_interval_from_r(r, n)
        wide_ci = ci is not None and (ci[1] - ci[0]) > CONFIDENCE_INTERVAL_WIDTH_THRESHOLD
        fisher_hp = both_binary and fisher_exact_p(data_a, data_b) >= P_VALUE_SIGNIFICANCE_THRESHOLD
        streak_reset = self._check_low_streak_resets(data_a, data_b, idx_a, idx_b)
        qi = self._quality.determine_issue(n, p_val, low_variance=low_var, small_binary_group=small_group, wide_ci=wide_ci, fisher_high_p=fisher_hp, low_streak_resets=streak_reset)
        return CorrelationPairResult(
            report_id=self._report_id,
            metric_a_id=sk_a.metric_id, metric_b_id=sk_b.metric_id,
            slot_a_id=sk_a.slot_id, slot_b_id=sk_b.slot_id,
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
            if min(count_true, count_false) < self._MIN_BINARY_GROUP_SIZE:
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

    # ─── Phase 7: Insert pairs ─────────────────────────────────────

    async def _insert_pairs(self, pairs: list[CorrelationPairResult]) -> None:
        await self._repo.insert_pairs(pairs)
        self._qt.mark("insert_pairs")

    # ─── Phase 8: Finalize ─────────────────────────────────────────

    async def _finalize(self) -> None:
        await self._repo.finalize_report(self._report_id)
        self._qt.log()


