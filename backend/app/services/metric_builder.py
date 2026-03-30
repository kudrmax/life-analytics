"""Metric builder — mapping DB row → MetricDefinitionOut."""

import json
from typing import Any, Mapping

from app.domain.privacy import mask_name, mask_icon
from app.schemas import MetricDefinitionOut, CheckpointOut, IntervalOut


async def build_metric_out(
    row: Mapping[str, Any],
    checkpoints: list[dict] | None = None,
    intervals: list[dict] | None = None,
    enum_opts: list | None = None,
    privacy_mode: bool = False,
) -> MetricDefinitionOut:
    formula_raw = row.get("formula")
    if isinstance(formula_raw, str):
        formula_raw = json.loads(formula_raw)
    is_private = row.get("private", False)
    return MetricDefinitionOut(
        id=row["id"],
        slug=row["slug"],
        name=mask_name(row["name"], is_private, privacy_mode),
        description=row.get("description"),
        category_id=row.get("category_id"),
        icon=mask_icon(row.get("icon", ""), is_private, privacy_mode),
        type=row["type"],
        enabled=row["enabled"],
        sort_order=row["sort_order"],
        scale_min=row.get("scale_min"),
        scale_max=row.get("scale_max"),
        scale_step=row.get("scale_step"),
        scale_labels=json.loads(row["scale_labels"]) if row.get("scale_labels") is not None else None,
        checkpoints=[CheckpointOut(**cp) for cp in checkpoints] if checkpoints else [],
        intervals=[
            IntervalOut(
                id=iv.get("id", 0),
                start_checkpoint_id=iv.get("start_checkpoint_id", 0),
                end_checkpoint_id=iv.get("end_checkpoint_id", 0),
                label=iv.get("label", ""),
            )
            for iv in intervals
        ] if intervals else [],
        formula=formula_raw,
        result_type=row.get("result_type"),
        provider=row.get("provider"),
        metric_key=row.get("metric_key"),
        value_type=row.get("value_type"),
        filter_name=row.get("filter_name"),
        filter_query=row.get("filter_query"),
        activitywatch_category_id=row.get("activitywatch_category_id"),
        config_app_name=row.get("config_app_name"),
        enum_options=enum_opts,
        multi_select=row.get("multi_select"),
        private=is_private,
        hide_in_cards=row.get("hide_in_cards", False),
        is_checkpoint=row.get("is_checkpoint", False),
        interval_binding=row.get("interval_binding", "all_day"),
        all_checkpoints=row.get("all_checkpoints", False),
        all_intervals=row.get("all_intervals", False),
        condition_metric_id=row.get("condition_metric_id"),
        condition_type=row.get("condition_type"),
        condition_value=json.loads(row["condition_value"]) if row.get("condition_value") is not None else None,
    )
