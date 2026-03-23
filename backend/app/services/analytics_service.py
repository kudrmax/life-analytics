"""Service layer for analytics — trends, stats, distribution, streaks."""

from datetime import date as date_type
from statistics import mean, median

from app.analytics.pair_formatter import PairFormatter
from app.analytics.value_converter import ValueConverter
from app.analytics.value_fetcher import ValueFetcher
from app.formula import get_referenced_metric_ids
from app.metric_helpers import mask_name, is_blocked, PRIVATE_MASK
from app.repositories.analytics_repository import AnalyticsRepository
from app.timing import QueryTimer


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository, conn) -> None:
        self.repo = repo
        self.conn = conn
        self.user_id = repo.user_id

    async def trends(self, metric_id: int, start: str, end: str, privacy_mode: bool) -> dict:
        qt = QueryTimer(f"trends/{metric_id}")
        metric = await self.repo.get_metric_with_config(metric_id)
        if not metric:
            return {"error": "Metric not found"}
        qt.mark("metric")
        if is_blocked(metric.get("private", False), privacy_mode):
            return {"metric_id": metric_id, "metric_name": PRIVATE_MASK, "start": start, "end": end, "points": [], "blocked": True}

        mt = metric["type"]
        if mt == "integration":
            mt = metric["ic_value_type"] or "number"
        start_d, end_d = date_type.fromisoformat(start), date_type.fromisoformat(end)

        if metric["type"] == "computed":
            formula = ValueConverter.parse_formula(metric.get("formula"))
            ref_ids = get_referenced_metric_ids(formula)
            aggregated = await ValueFetcher(self.conn).values_by_date_for_computed(
                formula, metric.get("result_type") or "float", ref_ids, start_d, end_d, self.user_id)
        elif mt == "text":
            rows = await self.repo.get_notes_by_date(metric_id, start_d, end_d)
            qt.mark("values"); qt.log()
            return {"metric_id": metric_id, "metric_name": metric["name"], "metric_type": "text",
                    "start": start, "end": end, "points": [{"date": str(r["date"]), "value": r["cnt"]} for r in rows]}
        elif mt == "enum":
            opts = await self.repo.get_enum_options_enabled(metric_id)
            option_series = {}
            for o in opts:
                series = await ValueFetcher(self.conn).values_by_date_for_enum_option(metric_id, o["id"], start_d, end_d, self.user_id)
                option_series[o["label"]] = [{"date": d, "value": v} for d, v in sorted(series.items())]
            qt.mark("values"); qt.log()
            return {"metric_id": metric_id, "metric_name": metric["name"], "metric_type": "enum",
                    "start": start, "end": end, "options": [{"id": o["id"], "label": o["label"]} for o in opts], "option_series": option_series}
        else:
            value_table, extra_cols = ValueConverter.get_value_table(mt)
            rows = await self.repo.get_entries_with_values(metric_id, value_table, extra_cols, start_d, end_d)
            aggregated = ValueConverter.aggregate_by_date(rows, mt)
        qt.mark("values")
        points = [{"date": d, "value": v} for d, v in sorted(aggregated.items())]
        display_name = metric["name"]
        if mt == "bool" and await self.repo.has_enabled_slots(metric_id):
            display_name = f"{display_name} (хоть раз)"
        qt.mark("display_name"); qt.log()
        return {"metric_id": metric_id, "metric_name": display_name, "start": start, "end": end, "points": points}

    async def metric_stats(self, metric_id: int, start: str, end: str, privacy_mode: bool) -> dict:
        qt = QueryTimer(f"metric-stats/{metric_id}")
        metric = await self.repo.get_metric_with_config(metric_id)
        if not metric:
            return {"error": "Metric not found"}
        if is_blocked(metric.get("private", False), privacy_mode):
            return {"blocked": True}
        qt.mark("metric")
        mt = metric["type"]
        if mt == "integration":
            mt = metric["ic_value_type"] or "number"
        start_date, end_date = date_type.fromisoformat(start), date_type.fromisoformat(end)
        total_days = (end_date - start_date).days + 1

        if metric["type"] == "computed":
            return await self._computed_stats(metric, start_date, end_date, total_days, metric_id)
        if mt == "text":
            return await self._text_stats(metric_id, start_date, end_date, total_days, qt)
        if mt == "enum":
            return await self._enum_stats(metric_id, start_date, end_date, total_days, qt)
        return await self._numeric_stats(metric, mt, metric_id, start_date, end_date, total_days, qt)

    async def metric_distribution(self, metric_id: int, start: str, end: str, privacy_mode: bool) -> dict:
        from app.distribution import compute_distribution
        qt = QueryTimer(f"distribution/{metric_id}")
        metric = await self.repo.get_metric_with_config(metric_id)
        if not metric:
            return {"error": "Metric not found"}
        if is_blocked(metric.get("private", False), privacy_mode):
            return {"blocked": True}
        qt.mark("metric")
        mt = metric["type"]
        if mt == "integration":
            mt = metric["ic_value_type"] or "number"
        if mt == "computed":
            mt = metric.get("result_type") or "float"
        if mt not in {"number", "duration", "scale", "time", "int", "float"}:
            return {"not_applicable": True, "reason": f"Type '{mt}' does not support distribution"}
        start_date, end_date = date_type.fromisoformat(start), date_type.fromisoformat(end)
        fetcher = ValueFetcher(self.conn)
        if metric["type"] == "computed":
            formula = ValueConverter.parse_formula(metric.get("formula"))
            ref_ids = get_referenced_metric_ids(formula)
            aggregated = await fetcher.values_by_date_for_computed(formula, metric.get("result_type") or "float", ref_ids, start_date, end_date, self.user_id)
        else:
            aggregated = await fetcher.values_by_date_for_slot(metric_id, mt, start_date, end_date, self.user_id)
        qt.mark("values")
        values = list(aggregated.values())
        if len(values) < 3:
            qt.log(); return {"insufficient_data": True, "n": len(values)}
        result = compute_distribution(values, mt)
        qt.log()
        return {
            "metric_id": metric_id, "metric_type": mt, "n": result.n,
            "bins": [{"bin_start": b.bin_start, "bin_end": b.bin_end, "count": b.count, "label": b.label} for b in result.bins],
            "kde_x": result.kde_x, "kde_y": result.kde_y,
            "stats": {"mean": result.stats.mean, "median": result.stats.median, "variance": result.stats.variance,
                      "std_dev": result.stats.std_dev, "skewness": result.stats.skewness, "kurtosis": result.stats.kurtosis},
            "display_stats": [{"label": ds.label, "value": ds.value} for ds in result.display_stats],
        }

    async def streaks(self, privacy_mode: bool) -> dict:
        metrics = await self.repo.get_enabled_bool_metrics()
        result = []
        for m in metrics:
            m_private = m.get("private", False)
            m_blocked = is_blocked(m_private, privacy_mode)
            rows = await self.repo.get_bool_streak_rows(m["id"])
            current_streak = 0
            for r in rows:
                if r["day_value"] is True:
                    current_streak += 1
                else:
                    break
            if current_streak > 0:
                result.append({"metric_id": m["id"], "metric_name": mask_name(m["name"], m_private, privacy_mode),
                               "current_streak": 0 if m_blocked else current_streak})
        return {"streaks": result}

    # ── Private stat helpers ──────────────────────────────────────

    async def _computed_stats(self, metric, start_date, end_date, total_days, metric_id) -> dict:
        formula = ValueConverter.parse_formula(metric.get("formula"))
        rt = metric.get("result_type") or "float"
        ref_ids = get_referenced_metric_ids(formula)
        aggregated = await ValueFetcher(self.conn).values_by_date_for_computed(formula, rt, ref_ids, start_date, end_date, self.user_id)
        te = len(aggregated)
        fr = round(te / total_days * 100, 1) if total_days > 0 else 0
        result: dict = {"metric_id": metric_id, "metric_type": "computed", "result_type": rt, "total_entries": te, "total_days": total_days, "fill_rate": fr}
        values = sorted(aggregated.values())
        if rt == "bool":
            yc = sum(1 for v in values if v == 1.0)
            result.update({"yes_percent": round(yc / te * 100, 1) if te else 0, "yes_count": yc, "no_count": te - yc})
        elif rt == "time" and values:
            avg = mean(values)
            result.update({"average": f"{int(avg)//60:02d}:{int(avg)%60:02d}", "earliest": f"{int(min(values))//60:02d}:{int(min(values))%60:02d}", "latest": f"{int(max(values))//60:02d}:{int(max(values))%60:02d}"})
        elif rt == "duration" and values:
            _f = lambda m: f"{int(round(m))//60}ч {int(round(m))%60}м"
            result.update({"average": _f(mean(values)), "min": _f(min(values)), "max": _f(max(values))})
        elif values:
            result.update({"average": round(mean(values), 2), "min": round(min(values), 2), "max": round(max(values), 2)})
        result["display_stats"] = PairFormatter.build_display_stats(result, "computed")
        return result

    async def _text_stats(self, metric_id, start_date, end_date, total_days, qt) -> dict:
        rows = await self.repo.get_notes_by_date(metric_id, start_date, end_date)
        qt.mark("values")
        tn = sum(r["cnt"] for r in rows); dwn = len(rows)
        fr = round(dwn / total_days * 100, 1) if total_days > 0 else 0
        counts = [r["cnt"] for r in rows]; qt.log()
        result = {"metric_id": metric_id, "metric_type": "text", "total_entries": dwn, "total_days": total_days, "fill_rate": fr,
                  "total_notes": tn, "average_per_day": round(tn / dwn, 1) if dwn > 0 else 0, "max_per_day": max(counts) if counts else 0}
        result["display_stats"] = PairFormatter.build_display_stats(result, "text")
        return result

    async def _enum_stats(self, metric_id, start_date, end_date, total_days, qt) -> dict:
        rows = await self.repo.get_enum_entries(metric_id, start_date, end_date)
        opts = await self.repo.get_enum_options_enabled(metric_id); qt.mark("values")
        dates_with = set(str(r["date"]) for r in rows); te = len(dates_with)
        fr = round(te / total_days * 100, 1) if total_days > 0 else 0
        oc = {o["id"]: 0 for o in opts}
        for r in rows:
            for oid in r["selected_option_ids"]:
                if oid in oc: oc[oid] += 1
        os_ = [{"label": o["label"], "count": oc[o["id"]], "percent": round(oc[o["id"]] / te * 100, 1) if te > 0 else 0} for o in opts]
        mc = max(os_, key=lambda x: x["count"])["label"] if os_ else "—"; qt.log()
        result = {"metric_id": metric_id, "metric_type": "enum", "total_entries": te, "total_days": total_days,
                  "fill_rate": fr, "option_stats": os_, "most_common": mc}
        result["display_stats"] = PairFormatter.build_display_stats(result, "enum")
        return result

    async def _numeric_stats(self, metric, mt, metric_id, start_date, end_date, total_days, qt) -> dict:
        vt, ec = ValueConverter.get_value_table(mt)
        rows = await self.repo.get_entries_with_values(metric_id, vt, ec, start_date, end_date)
        aggregated = ValueConverter.aggregate_by_date(rows, mt); qt.mark("values")
        te = len(aggregated); fr = round(te / total_days * 100, 1) if total_days > 0 else 0
        result: dict = {"metric_id": metric_id, "metric_type": mt, "total_entries": te, "total_days": total_days, "fill_rate": fr}
        values = sorted(aggregated.values())
        if mt == "bool":
            yc = sum(1 for v in aggregated.values() if v == 1.0); nc = te - yc
            yp = round(yc / te * 100, 1) if te > 0 else 0
            srows = await self.repo.get_bool_streak_rows(metric_id)
            cs = 0
            for r in srows:
                if r["day_value"] is True: cs += 1
                else: break
            ls = run = 0
            for r in reversed(srows):
                if r["day_value"] is True: run += 1; ls = max(ls, run)
                else: run = 0
            result.update({"yes_percent": yp, "yes_count": yc, "no_count": nc, "current_streak": cs, "longest_streak": ls})
        elif mt == "time":
            if values:
                am = mean(values)
                result.update({"average": f"{int(am)//60:02d}:{int(am)%60:02d}", "earliest": f"{int(min(values))//60:02d}:{int(min(values))%60:02d}", "latest": f"{int(max(values))//60:02d}:{int(max(values))%60:02d}"})
            else: result.update({"average": "--:--", "earliest": "--:--", "latest": "--:--"})
        elif mt == "duration":
            _f = lambda m: f"{int(round(m))//60}ч {int(round(m))%60}м"
            if values: result.update({"average": _f(mean(values)), "min": _f(min(values)), "max": _f(max(values)), "median": _f(median(values))})
            else: result.update({"average": "0ч 0м", "min": "0ч 0м", "max": "0ч 0м", "median": "0ч 0м"})
        elif mt in ("number", "scale"):
            if values: result.update({"average": round(mean(values), 1), "min": round(min(values), 1), "max": round(max(values), 1)} | ({"median": round(median(values), 1)} if mt == "number" else {}))
            else: result.update({"average": 0, "min": 0, "max": 0} | ({"median": 0} if mt == "number" else {}))
        result["display_stats"] = PairFormatter.build_display_stats(result, mt)
        qt.log()
        return result
