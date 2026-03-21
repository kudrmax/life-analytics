import json
import re

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.schemas import (
    MetricDefinitionCreate, MetricDefinitionUpdate, MetricDefinitionOut, MetricType,
    ConversionPreview, MetricConvertRequest, MetricConvertResponse,
)
from app.auth import get_current_user, get_privacy_mode
from app.metric_helpers import build_metric_out, get_metric_slots, get_enum_options
from app.formula import validate_formula, get_referenced_metric_ids
from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS, ACTIVITYWATCH_ICON


def _generate_slug(name: str) -> str:
    """Generate a slug from metric name: lowercase, spaces to underscores, strip special chars."""
    slug = name.lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_а-яё]", "", slug)
    return slug or f"metric_{int(__import__('time').time())}"


async def _unique_slug(db, user_id: int, base_slug: str) -> str:
    """Ensure slug is unique for the user, appending _2, _3... if needed."""
    slug = base_slug
    suffix = 1
    while True:
        existing = await db.fetchval(
            "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
            slug, user_id,
        )
        if not existing:
            return slug
        suffix += 1
        slug = f"{base_slug}_{suffix}"

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricDefinitionOut])
async def list_metrics(
    enabled_only: bool = False,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    query = """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step, sc.labels AS scale_labels,
                      cc.formula, cc.result_type,
                      ic.provider, ic.metric_key, ic.value_type,
                      ifc.filter_name, iqc.filter_query,
                      icatc.activitywatch_category_id, iapc.app_name AS config_app_name,
                      ec.multi_select,
                      mcond.depends_on_metric_id AS condition_metric_id,
                      mcond.condition_type, mcond.condition_value
               FROM metric_definitions md
               LEFT JOIN scale_config sc ON sc.metric_id = md.id
               LEFT JOIN computed_config cc ON cc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
               LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
               LEFT JOIN integration_category_config icatc ON icatc.metric_id = md.id
               LEFT JOIN integration_app_config iapc ON iapc.metric_id = md.id
               LEFT JOIN enum_config ec ON ec.metric_id = md.id
               LEFT JOIN metric_condition mcond ON mcond.metric_id = md.id
               WHERE md.user_id = $1"""
    params = [current_user["id"]]
    if enabled_only:
        query += " AND md.enabled = TRUE"
    query += " ORDER BY md.sort_order, md.id"
    rows = await db.fetch(query, *params)

    metric_ids = [r["id"] for r in rows]
    slots_map = await get_metric_slots(db, metric_ids) if metric_ids else {}
    enum_opts_map = await get_enum_options(db, metric_ids) if metric_ids else {}

    return [
        await build_metric_out(r, slots_map.get(r["id"]), enum_opts_map.get(r["id"]), privacy_mode)
        for r in rows
    ]


@router.post("/reorder")
async def reorder_metrics(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Bulk update sort_order and category_id for multiple metrics."""
    async with db.transaction():
        seen_metrics: set[int] = set()
        for item in items:
            metric_id: int = item["id"]
            slot_id: int | None = item.get("slot_id")
            cat_id: int | None = item.get("category_id")

            if slot_id:
                # Update category_id for this specific slot in junction table
                await db.execute(
                    "UPDATE metric_slots SET category_id = $1 WHERE slot_id = $2 AND metric_id = $3",
                    cat_id, slot_id, metric_id,
                )

            if metric_id not in seen_metrics:
                seen_metrics.add(metric_id)
                if slot_id:
                    # Slot row → update sort_order only, metric.category_id=NULL
                    await db.execute(
                        """UPDATE metric_definitions
                           SET sort_order = $1, category_id = NULL
                           WHERE id = $2 AND user_id = $3""",
                        item["sort_order"], metric_id, current_user["id"],
                    )
                else:
                    # Regular metric row → sort_order + category_id
                    await db.execute(
                        """UPDATE metric_definitions
                           SET sort_order = $1, category_id = $2
                           WHERE id = $3 AND user_id = $4""",
                        item["sort_order"], cat_id, metric_id, current_user["id"],
                    )
                    # Propagate category_id to all enabled slots in junction table
                    await db.execute(
                        "UPDATE metric_slots SET category_id = $1 WHERE metric_id = $2 AND enabled = TRUE",
                        cat_id, metric_id,
                    )
    return {"ok": True}


@router.get("/{metric_id}", response_model=MetricDefinitionOut)
async def get_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    row = await db.fetchrow(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step, sc.labels AS scale_labels,
                  cc.formula, cc.result_type,
                  ic.provider, ic.metric_key, ic.value_type,
                  ifc.filter_name, iqc.filter_query,
                  icatc.activitywatch_category_id, iapc.app_name AS config_app_name,
                  ec.multi_select,
                  mcond.depends_on_metric_id AS condition_metric_id,
                  mcond.condition_type, mcond.condition_value
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
           LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
           LEFT JOIN integration_category_config icatc ON icatc.metric_id = md.id
           LEFT JOIN integration_app_config iapc ON iapc.metric_id = md.id
           LEFT JOIN enum_config ec ON ec.metric_id = md.id
           LEFT JOIN metric_condition mcond ON mcond.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")

    slots_map = await get_metric_slots(db, [metric_id])
    enum_opts_map = await get_enum_options(db, [metric_id])
    return await build_metric_out(row, slots_map.get(metric_id), enum_opts_map.get(metric_id), privacy_mode)


@router.post("", response_model=MetricDefinitionOut, status_code=201)
async def create_metric(
    data: MetricDefinitionCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    if data.type == MetricType.integration:
        if not data.provider:
            raise HTTPException(400, "provider is required for integration metrics")
        if not data.metric_key:
            raise HTTPException(400, "metric_key is required for integration metrics")
        if data.provider == "todoist":
            if data.metric_key not in TODOIST_METRICS:
                raise HTTPException(400, f"Unknown metric_key: {data.metric_key}")
            integration_row = await db.fetchval(
                "SELECT id FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
                current_user["id"],
            )
            if not integration_row:
                raise HTTPException(400, "Todoist is not connected")
            # Validate config fields
            if data.metric_key == "filter_tasks_count":
                if not data.filter_name or not data.filter_name.strip():
                    raise HTTPException(400, "filter_name is required for filter_tasks_count")
            elif data.metric_key == "query_tasks_count":
                if not data.filter_query or not data.filter_query.strip():
                    raise HTTPException(400, "filter_query is required for query_tasks_count")
        elif data.provider == "activitywatch":
            if data.metric_key not in ACTIVITYWATCH_METRICS:
                raise HTTPException(400, f"Unknown metric_key: {data.metric_key}")
            aw_enabled = await db.fetchval(
                "SELECT enabled FROM activitywatch_settings WHERE user_id = $1",
                current_user["id"],
            )
            if not aw_enabled:
                raise HTTPException(400, "ActivityWatch is not enabled")
            if data.metric_key == "category_time":
                if not data.activitywatch_category_id:
                    raise HTTPException(400, "activitywatch_category_id is required for category_time")
                cat = await db.fetchrow(
                    "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
                    data.activitywatch_category_id, current_user["id"],
                )
                if not cat:
                    raise HTTPException(400, "Category not found")
            elif data.metric_key == "app_time":
                if not data.app_name or not data.app_name.strip():
                    raise HTTPException(400, "app_name is required for app_time")
        else:
            raise HTTPException(400, f"Unknown provider: {data.provider}")

    if data.type == MetricType.enum:
        if not data.enum_options or len(data.enum_options) < 2:
            raise HTTPException(400, "Enum metrics need at least 2 options")
        if len(set(data.enum_options)) != len(data.enum_options):
            raise HTTPException(400, "Enum option labels must be unique")

    # Generate slug from name if not provided
    if data.slug:
        existing = await db.fetchval(
            "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
            data.slug, current_user["id"],
        )
        if existing:
            raise HTTPException(409, "Metric with this slug already exists")
        slug = data.slug
    else:
        base_slug = _generate_slug(data.name)
        slug = await _unique_slug(db, current_user["id"], base_slug)

    if data.type == MetricType.scale:
        s_min = data.scale_min if data.scale_min is not None else 1
        s_max = data.scale_max if data.scale_max is not None else 5
        s_step = data.scale_step if data.scale_step is not None else 1
        if s_min >= s_max:
            raise HTTPException(400, "scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    if data.type == MetricType.integration:
        icon = ACTIVITYWATCH_ICON if data.provider == "activitywatch" else TODOIST_ICON
    else:
        icon = data.icon

    # Inline category creation
    cat_id = data.category_id
    if data.new_category_name:
        cat_id = await db.fetchval(
            """INSERT INTO categories (user_id, name, parent_id, sort_order)
               VALUES ($1, $2, $3, COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE user_id = $1), 0))
               RETURNING id""",
            current_user["id"], data.new_category_name.strip(), data.new_category_parent_id,
        )

    metric_id = await db.fetchval(
        """INSERT INTO metric_definitions
           (user_id, slug, name, category_id, icon, type, enabled, sort_order, private, description, hide_in_cards)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
           RETURNING id""",
        current_user["id"],
        slug,
        data.name,
        cat_id,
        icon,
        data.type.value,
        data.enabled,
        data.sort_order,
        data.private,
        data.description,
        data.hide_in_cards,
    )

    if data.type == MetricType.integration:
        if data.provider == "activitywatch":
            value_type = ACTIVITYWATCH_METRICS[data.metric_key]["value_type"]
        else:
            value_type = TODOIST_METRICS[data.metric_key]["value_type"]
        await db.execute(
            "INSERT INTO integration_config (metric_id, provider, metric_key, value_type) VALUES ($1, $2, $3, $4)",
            metric_id, data.provider, data.metric_key, value_type,
        )
        if data.metric_key == "filter_tasks_count":
            await db.execute(
                "INSERT INTO integration_filter_config (metric_id, filter_name) VALUES ($1, $2)",
                metric_id, data.filter_name.strip(),
            )
        elif data.metric_key == "query_tasks_count":
            await db.execute(
                "INSERT INTO integration_query_config (metric_id, filter_query) VALUES ($1, $2)",
                metric_id, data.filter_query.strip(),
            )
        elif data.metric_key == "category_time":
            await db.execute(
                "INSERT INTO integration_category_config (metric_id, activitywatch_category_id) VALUES ($1, $2)",
                metric_id, data.activitywatch_category_id,
            )
        elif data.metric_key == "app_time":
            await db.execute(
                "INSERT INTO integration_app_config (metric_id, app_name) VALUES ($1, $2)",
                metric_id, data.app_name.strip(),
            )

    if data.type == MetricType.scale:
        labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
        await db.execute(
            "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels) VALUES ($1, $2, $3, $4, $5::jsonb)",
            metric_id, s_min, s_max, s_step, labels_json,
        )

    if data.type == MetricType.enum:
        multi = data.multi_select if data.multi_select is not None else False
        await db.execute(
            "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
            metric_id, multi,
        )
        for i, label in enumerate(data.enum_options):
            await db.execute(
                "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                metric_id, i, label,
            )

    if data.type == MetricType.computed:
        if not data.formula:
            raise HTTPException(400, "formula is required for computed metrics")
        if data.result_type not in ("bool", "int", "float", "time", "duration"):
            raise HTTPException(400, "result_type must be one of: bool, int, float, time, duration")
        ref_ids = get_referenced_metric_ids(data.formula)
        if ref_ids:
            source_rows = await db.fetch(
                "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
                ref_ids, current_user["id"],
            )
            if len(source_rows) != len(set(ref_ids)):
                raise HTTPException(400, "Formula references unknown metrics")
            source_types = {r["id"]: r["type"] for r in source_rows}
            err = validate_formula(data.formula, source_types)
            if err:
                raise HTTPException(400, err)
        has_comparison = any(
            t.get("type") == "op" and t.get("value") in (">", "<") for t in data.formula
        )
        if has_comparison and data.result_type != "bool":
            raise HTTPException(400, "Формула со сравнением должна иметь тип результата bool")
        await db.execute(
            "INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1, $2::jsonb, $3)",
            metric_id, json.dumps(data.formula), data.result_type,
        )

    # Link measurement slots if 2+ slot_configs provided (skip for computed/integration/text)
    if data.type not in (MetricType.computed, MetricType.integration, MetricType.text):
        if data.slot_configs and len(data.slot_configs) >= 2:
            for i, cfg in enumerate(data.slot_configs):
                slot_id = cfg.get("slot_id")
                if slot_id is None:
                    raise HTTPException(400, "slot_id is required in slot_configs")
                # Validate slot ownership
                slot_ok = await db.fetchval(
                    "SELECT 1 FROM measurement_slots WHERE id = $1 AND user_id = $2",
                    slot_id, current_user["id"],
                )
                if not slot_ok:
                    raise HTTPException(400, f"Slot {slot_id} not found")
                slot_cat_id = cfg.get("category_id")
                if slot_cat_id is not None:
                    cat_ok = await db.fetchval(
                        "SELECT 1 FROM categories WHERE id = $1 AND user_id = $2",
                        slot_cat_id, current_user["id"],
                    )
                    if not cat_ok:
                        raise HTTPException(400, f"Category {slot_cat_id} not found")
                await db.execute(
                    "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4)",
                    metric_id, slot_id, i, slot_cat_id,
                )
            # Defensive rule: clear metric category_id — category now on slots
            await db.execute(
                "UPDATE metric_definitions SET category_id = NULL WHERE id = $1", metric_id,
            )

    # Condition (depends on another metric)
    if data.condition_metric_id is not None and data.condition_type is not None:
        if data.condition_type not in ('filled', 'equals', 'not_equals'):
            raise HTTPException(400, "condition_type must be 'filled', 'equals', or 'not_equals'")
        if data.condition_metric_id == metric_id:
            raise HTTPException(400, "Metric cannot depend on itself")
        dep = await db.fetchrow(
            "SELECT id FROM metric_definitions WHERE id = $1 AND user_id = $2",
            data.condition_metric_id, current_user["id"],
        )
        if not dep:
            raise HTTPException(400, "Dependency metric not found")
        if data.condition_type in ('equals', 'not_equals') and data.condition_value is None:
            raise HTTPException(400, "condition_value is required for equals/not_equals")
        # Check for cycles
        cycle_check = await db.fetchval(
            "SELECT depends_on_metric_id FROM metric_condition WHERE metric_id = $1",
            data.condition_metric_id,
        )
        if cycle_check == metric_id:
            raise HTTPException(400, "Circular dependency detected")
        cond_val = json.dumps(data.condition_value) if data.condition_value is not None else None
        await db.execute(
            "INSERT INTO metric_condition (metric_id, depends_on_metric_id, condition_type, condition_value) VALUES ($1, $2, $3, $4::jsonb)",
            metric_id, data.condition_metric_id, data.condition_type, cond_val,
        )

    return await get_metric(metric_id, db, current_user, privacy_mode)


@router.patch("/{metric_id}", response_model=MetricDefinitionOut)
async def update_metric(
    metric_id: int,
    data: MetricDefinitionUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    row = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")

    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.category_id is not None:
        updates["category_id"] = data.category_id if data.category_id != 0 else None
    if data.icon is not None and row["type"] != "integration":
        updates["icon"] = data.icon
    if data.enabled is not None:
        updates["enabled"] = data.enabled
    if data.sort_order is not None:
        updates["sort_order"] = data.sort_order
    if data.private is not None:
        updates["private"] = data.private
    if data.hide_in_cards is not None:
        updates["hide_in_cards"] = data.hide_in_cards
    if data.description is not None:
        updates["description"] = data.description or None

    if updates:
        set_parts = []
        values = []
        for i, (k, v) in enumerate(updates.items(), start=1):
            set_parts.append(f"{k} = ${i}")
            values.append(v)
        values.append(metric_id)
        values.append(current_user["id"])
        set_clause = ", ".join(set_parts)
        await db.execute(
            f"UPDATE metric_definitions SET {set_clause} WHERE id = ${len(values) - 1} AND user_id = ${len(values)}",
            *values,
        )

    # Update scale_config if this is a scale metric
    if row["type"] == "scale" and any(
        getattr(data, f) is not None for f in ("scale_min", "scale_max", "scale_step", "scale_labels")
    ):
        cfg = await db.fetchrow(
            "SELECT scale_min, scale_max, scale_step, labels FROM scale_config WHERE metric_id = $1",
            metric_id,
        )
        s_min = data.scale_min if data.scale_min is not None else (cfg["scale_min"] if cfg else 1)
        s_max = data.scale_max if data.scale_max is not None else (cfg["scale_max"] if cfg else 5)
        s_step = data.scale_step if data.scale_step is not None else (cfg["scale_step"] if cfg else 1)
        if s_min >= s_max:
            raise HTTPException(400, "scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")
        # scale_labels: explicit None in schema means "not sent", empty dict {} means "clear labels"
        if data.scale_labels is not None:
            labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
        else:
            labels_json = cfg["labels"] if cfg else None
        if cfg:
            await db.execute(
                "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3, labels = $4::jsonb WHERE metric_id = $5",
                s_min, s_max, s_step, labels_json, metric_id,
            )
        else:
            await db.execute(
                "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels) VALUES ($1, $2, $3, $4, $5::jsonb)",
                metric_id, s_min, s_max, s_step, labels_json,
            )

    # Update computed_config if this is a computed metric
    if row["type"] == "computed" and (data.formula is not None or data.result_type is not None):
        cfg = await db.fetchrow(
            "SELECT formula, result_type FROM computed_config WHERE metric_id = $1",
            metric_id,
        )
        new_formula = data.formula if data.formula is not None else (json.loads(cfg["formula"]) if cfg and cfg["formula"] else [])
        new_result_type = data.result_type if data.result_type is not None else (cfg["result_type"] if cfg else "float")
        if new_result_type not in ("bool", "int", "float", "time"):
            raise HTTPException(400, "result_type must be one of: bool, int, float, time, duration")
        ref_ids = get_referenced_metric_ids(new_formula)
        if ref_ids:
            source_rows = await db.fetch(
                "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
                ref_ids, current_user["id"],
            )
            if len(source_rows) != len(set(ref_ids)):
                raise HTTPException(400, "Formula references unknown metrics")
            source_types = {r["id"]: r["type"] for r in source_rows}
            err = validate_formula(new_formula, source_types)
            if err:
                raise HTTPException(400, err)
        has_comparison = any(
            t.get("type") == "op" and t.get("value") in (">", "<") for t in new_formula
        )
        if has_comparison and new_result_type != "bool":
            raise HTTPException(400, "Формула со сравнением должна иметь тип результата bool")
        if cfg:
            await db.execute(
                "UPDATE computed_config SET formula = $1::jsonb, result_type = $2 WHERE metric_id = $3",
                json.dumps(new_formula), new_result_type, metric_id,
            )
        else:
            await db.execute(
                "INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1, $2::jsonb, $3)",
                metric_id, json.dumps(new_formula), new_result_type,
            )

    # Update enum config
    if row["type"] == "enum":
        if data.multi_select is not None:
            cfg = await db.fetchrow(
                "SELECT metric_id FROM enum_config WHERE metric_id = $1", metric_id,
            )
            if cfg:
                await db.execute(
                    "UPDATE enum_config SET multi_select = $1 WHERE metric_id = $2",
                    data.multi_select, metric_id,
                )
            else:
                await db.execute(
                    "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
                    metric_id, data.multi_select,
                )

        if data.enum_options is not None:
            new_opts = data.enum_options  # list[dict] with optional id, required label
            labels = [o["label"] for o in new_opts if o.get("label")]
            if len(labels) < 2:
                raise HTTPException(400, "Enum metrics need at least 2 options")
            if len(set(labels)) != len(labels):
                raise HTTPException(400, "Enum option labels must be unique")

            existing_opts = await db.fetch(
                "SELECT * FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
                metric_id,
            )
            existing_ids = {o["id"] for o in existing_opts}
            seen_ids = set()

            for i, opt in enumerate(new_opts):
                opt_id = opt.get("id")
                label = opt["label"]
                if opt_id and opt_id in existing_ids:
                    # Update existing option (rename + reorder + re-enable)
                    seen_ids.add(opt_id)
                    await db.execute(
                        "UPDATE enum_options SET label = $1, sort_order = $2, enabled = TRUE WHERE id = $3",
                        label, i, opt_id,
                    )
                else:
                    # New option
                    await db.execute(
                        "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                        metric_id, i, label,
                    )

            # Disable options not in the new list
            for o in existing_opts:
                if o["id"] not in seen_ids:
                    await db.execute(
                        "UPDATE enum_options SET enabled = FALSE WHERE id = $1",
                        o["id"],
                    )

    # Update metric slots via junction table
    if data.slot_configs is not None:
        # Get ALL existing metric_slots (including disabled) sorted by sort_order
        existing_slots = await db.fetch(
            "SELECT * FROM metric_slots WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )
        has_existing_slots = len(existing_slots) > 0

        if len(data.slot_configs) < 2:
            # Trying to go to 0-1 slots
            if has_existing_slots:
                raise HTTPException(400, "Cannot reduce to fewer than 2 slots once configured")
            # No existing slots and 0-1 configs = no-op
        else:
            # Validate slot and category ownership
            for cfg in data.slot_configs:
                sid = cfg.get("slot_id")
                if sid is None:
                    raise HTTPException(400, "slot_id is required in slot_configs")
                slot_ok = await db.fetchval(
                    "SELECT 1 FROM measurement_slots WHERE id = $1 AND user_id = $2",
                    sid, current_user["id"],
                )
                if not slot_ok:
                    raise HTTPException(400, f"Slot {sid} not found")
                slot_cat_id = cfg.get("category_id")
                if slot_cat_id is not None:
                    cat_ok = await db.fetchval(
                        "SELECT 1 FROM categories WHERE id = $1 AND user_id = $2",
                        slot_cat_id, current_user["id"],
                    )
                    if not cat_ok:
                        raise HTTPException(400, f"Category {slot_cat_id} not found")

            if not has_existing_slots:
                # First time creating slots — create junction rows and migrate NULL entries
                first_slot_id = None
                for i, cfg in enumerate(data.slot_configs):
                    sid = cfg["slot_id"]
                    await db.execute(
                        "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4)",
                        metric_id, sid, i, cfg.get("category_id"),
                    )
                    if i == 0:
                        first_slot_id = sid
                # Migrate existing NULL-slot entries to first slot
                if first_slot_id:
                    await db.execute(
                        "UPDATE entries SET slot_id = $1 WHERE metric_id = $2 AND slot_id IS NULL",
                        first_slot_id, metric_id,
                    )
            else:
                # Update existing — match by slot_id
                existing_by_slot_id = {s["slot_id"]: s for s in existing_slots}
                seen_slot_ids: set[int] = set()

                for i, cfg in enumerate(data.slot_configs):
                    sid = cfg["slot_id"]
                    seen_slot_ids.add(sid)
                    if sid in existing_by_slot_id:
                        await db.execute(
                            "UPDATE metric_slots SET enabled = TRUE, category_id = $1, sort_order = $2 WHERE metric_id = $3 AND slot_id = $4",
                            cfg.get("category_id"), i, metric_id, sid,
                        )
                    else:
                        await db.execute(
                            "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4)",
                            metric_id, sid, i, cfg.get("category_id"),
                        )
                # Disable slots not mentioned in new list
                for s in existing_slots:
                    if s["slot_id"] not in seen_slot_ids:
                        await db.execute(
                            "UPDATE metric_slots SET enabled = FALSE WHERE metric_id = $1 AND slot_id = $2",
                            metric_id, s["slot_id"],
                        )

            # Defensive rule: clear metric category_id — category now on slots
            await db.execute(
                "UPDATE metric_definitions SET category_id = NULL WHERE id = $1", metric_id,
            )

    # Update condition
    if data.remove_condition:
        await db.execute("DELETE FROM metric_condition WHERE metric_id = $1", metric_id)
    elif data.condition_metric_id is not None and data.condition_type is not None:
        if data.condition_type not in ('filled', 'equals', 'not_equals'):
            raise HTTPException(400, "condition_type must be 'filled', 'equals', or 'not_equals'")
        if data.condition_metric_id == metric_id:
            raise HTTPException(400, "Metric cannot depend on itself")
        dep = await db.fetchrow(
            "SELECT id FROM metric_definitions WHERE id = $1 AND user_id = $2",
            data.condition_metric_id, current_user["id"],
        )
        if not dep:
            raise HTTPException(400, "Dependency metric not found")
        if data.condition_type in ('equals', 'not_equals') and data.condition_value is None:
            raise HTTPException(400, "condition_value is required for equals/not_equals")
        # Check for cycles
        cycle_check = await db.fetchval(
            "SELECT depends_on_metric_id FROM metric_condition WHERE metric_id = $1",
            data.condition_metric_id,
        )
        if cycle_check == metric_id:
            raise HTTPException(400, "Circular dependency detected")
        cond_val = json.dumps(data.condition_value) if data.condition_value is not None else None
        await db.execute(
            """INSERT INTO metric_condition (metric_id, depends_on_metric_id, condition_type, condition_value)
               VALUES ($1, $2, $3, $4::jsonb)
               ON CONFLICT (metric_id) DO UPDATE
               SET depends_on_metric_id = EXCLUDED.depends_on_metric_id,
                   condition_type = EXCLUDED.condition_type,
                   condition_value = EXCLUDED.condition_value""",
            metric_id, data.condition_metric_id, data.condition_type, cond_val,
        )

    return await get_metric(metric_id, db, current_user, privacy_mode)


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")
    await db.execute(
        "DELETE FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )


# ── Metric conversion ──────────────────────────────────────────────

ALLOWED_CONVERSIONS: dict[str, list[str]] = {
    "scale": ["scale"],
    "bool": ["enum"],
    "enum": ["scale"],
}

VALUE_TABLE_MAP: dict[str, str] = {
    "bool": "values_bool",
    "scale": "values_scale",
    "number": "values_number",
    "time": "values_time",
    "duration": "values_duration",
    "enum": "values_enum",
}


@router.get("/{metric_id}/convert/preview", response_model=ConversionPreview)
async def convert_preview(
    metric_id: int,
    target_type: MetricType,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id, type FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")

    source_type = row["type"]
    allowed = ALLOWED_CONVERSIONS.get(source_type, [])
    if target_type.value not in allowed:
        raise HTTPException(400, f"Conversion from {source_type} to {target_type.value} is not supported")

    entries_by_value: list[dict] = []
    total = 0

    if source_type == "scale":
        rows = await db.fetch(
            """SELECT vs.value, COUNT(*) as cnt
               FROM values_scale vs
               JOIN entries e ON e.id = vs.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY vs.value ORDER BY vs.value""",
            metric_id, current_user["id"],
        )
        for r in rows:
            entries_by_value.append({"value": str(r["value"]), "display": str(r["value"]), "count": r["cnt"]})
            total += r["cnt"]

    elif source_type == "bool":
        rows = await db.fetch(
            """SELECT vb.value, COUNT(*) as cnt
               FROM values_bool vb
               JOIN entries e ON e.id = vb.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY vb.value ORDER BY vb.value""",
            metric_id, current_user["id"],
        )
        for r in rows:
            display = "Да" if r["value"] else "Нет"
            entries_by_value.append({"value": str(r["value"]).lower(), "display": display, "count": r["cnt"]})
            total += r["cnt"]

    elif source_type == "enum":
        # Check multi_select — only single-select enum can be converted
        ec = await db.fetchrow(
            "SELECT multi_select FROM enum_config WHERE metric_id = $1", metric_id,
        )
        if ec and ec["multi_select"]:
            raise HTTPException(400, "Cannot convert multi-select enum to scale")

        # Load ALL enum_options (including disabled) to show in preview
        opts = await db.fetch(
            "SELECT id, label FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )
        opt_labels = {r["id"]: r["label"] for r in opts}

        # Count entries per option
        rows = await db.fetch(
            """SELECT ve.selected_option_ids, COUNT(*) as cnt
               FROM values_enum ve
               JOIN entries e ON e.id = ve.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY ve.selected_option_ids""",
            metric_id, current_user["id"],
        )
        for r in rows:
            option_ids = r["selected_option_ids"]
            if option_ids and len(option_ids) == 1:
                oid = option_ids[0]
                label = opt_labels.get(oid, str(oid))
                entries_by_value.append({"value": str(oid), "display": label, "count": r["cnt"]})
                total += r["cnt"]

        # Add options with no entries (count=0)
        seen_ids = {int(item["value"]) for item in entries_by_value}
        for opt in opts:
            if opt["id"] not in seen_ids:
                entries_by_value.append({"value": str(opt["id"]), "display": opt["label"], "count": 0})

    return ConversionPreview(total_entries=total, entries_by_value=entries_by_value)


@router.post("/{metric_id}/convert", response_model=MetricConvertResponse)
async def convert_metric(
    metric_id: int,
    data: MetricConvertRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    async with db.transaction():
        # Lock the metric row to prevent concurrent modifications
        row = await db.fetchrow(
            "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2 FOR UPDATE",
            metric_id, current_user["id"],
        )
        if not row:
            raise HTTPException(404, "Metric not found")

        source_type = row["type"]
        target_type = data.target_type.value
        allowed = ALLOWED_CONVERSIONS.get(source_type, [])
        if target_type not in allowed:
            raise HTTPException(400, f"Conversion from {source_type} to {target_type} is not supported")

        converted = 0
        deleted = 0

        if source_type == "scale" and target_type == "scale":
            converted, deleted = await _convert_scale_to_scale(db, metric_id, current_user["id"], data)
        elif source_type == "bool" and target_type == "enum":
            converted, deleted = await _convert_bool_to_enum(db, metric_id, current_user["id"], data)
        elif source_type == "enum" and target_type == "scale":
            converted, deleted = await _convert_enum_to_scale(db, metric_id, current_user["id"], data)

    return MetricConvertResponse(converted=converted, deleted=deleted)


async def _convert_scale_to_scale(
    db, metric_id: int, user_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    """Remap scale values within a transaction (caller must hold FOR UPDATE lock)."""
    if data.scale_min is None or data.scale_max is None or data.scale_step is None:
        raise HTTPException(400, "scale_min, scale_max, scale_step are required for scale→scale conversion")
    if data.scale_min >= data.scale_max:
        raise HTTPException(400, "scale_min must be less than scale_max")
    if data.scale_step < 1 or data.scale_step > (data.scale_max - data.scale_min):
        raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    # Validate new values are in valid range
    valid_new_values = set()
    v = data.scale_min
    while v <= data.scale_max:
        valid_new_values.add(v)
        v += data.scale_step

    # Get actual unique values
    actual_values = await db.fetch(
        """SELECT DISTINCT vs.value FROM values_scale vs
           JOIN entries e ON e.id = vs.entry_id
           WHERE e.metric_id = $1 AND e.user_id = $2""",
        metric_id, user_id,
    )
    actual_set = {str(r["value"]) for r in actual_values}

    # Check mapping completeness
    mapped_keys = set(data.value_mapping.keys())
    missing = actual_set - mapped_keys
    if missing:
        raise HTTPException(400, f"Mapping is incomplete — missing values: {', '.join(sorted(missing))}")

    # Validate new values
    for old_str, new_str in data.value_mapping.items():
        if new_str is not None:
            try:
                new_val = int(new_str)
            except ValueError:
                raise HTTPException(400, f"Invalid new value: {new_str}")
            if new_val not in valid_new_values:
                raise HTTPException(400, f"New value {new_val} is not in valid range [{data.scale_min}..{data.scale_max}] step {data.scale_step}")

    # Batch DELETE entries mapped to null
    values_to_delete = [int(k) for k, v in data.value_mapping.items() if v is None and k in actual_set]
    deleted = 0
    if values_to_delete:
        deleted = await db.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_scale vs ON vs.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2
                    AND vs.value = ANY($3::int[])
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, user_id, values_to_delete,
        )

    # Atomic UPDATE with CASE WHEN to avoid cross-mapping conflicts
    converted = 0
    mapping = {int(k): int(v) for k, v in data.value_mapping.items() if v is not None}
    if mapping:
        old_values = list(mapping.keys())
        case_clauses = " ".join(
            f"WHEN {old_val} THEN {new_val}" for old_val, new_val in mapping.items()
        )
        cnt = await db.fetchval(
            f"""WITH updated AS (
                UPDATE values_scale vs
                SET value = CASE vs.value {case_clauses} END,
                    scale_min = $2, scale_max = $3, scale_step = $4
                FROM entries e
                WHERE vs.entry_id = e.id AND e.metric_id = $1 AND e.user_id = $5
                AND vs.value = ANY($6::int[])
                RETURNING 1
            ) SELECT COUNT(*) FROM updated""",
            metric_id, data.scale_min, data.scale_max, data.scale_step, user_id, old_values,
        )
        converted = cnt

    # Update scale_config (clear labels on conversion — old labels don't match new range)
    await db.execute(
        "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3, labels = NULL WHERE metric_id = $4",
        data.scale_min, data.scale_max, data.scale_step, metric_id,
    )

    return converted, deleted


async def _convert_bool_to_enum(
    db, metric_id: int, user_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    """Convert bool metric to enum within a transaction (caller must hold FOR UPDATE lock)."""
    if not data.enum_options or len(data.enum_options) < 2:
        raise HTTPException(400, "At least 2 enum_options are required for bool→enum conversion")
    if len(set(data.enum_options)) != len(data.enum_options):
        raise HTTPException(400, "Enum option labels must be unique")

    # Validate mapping keys
    valid_bool_keys = {"true", "false"}
    for k in data.value_mapping:
        if k not in valid_bool_keys:
            raise HTTPException(400, f"Invalid bool value in mapping: {k}")

    # Create enum_config + enum_options
    await db.execute(
        "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
        metric_id, data.multi_select,
    )
    option_label_to_id: dict[str, int] = {}
    for i, label in enumerate(data.enum_options):
        opt_id = await db.fetchval(
            "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3) RETURNING id",
            metric_id, i, label,
        )
        option_label_to_id[label] = opt_id

    # Build mapping: bool_value_str -> option_id or None
    bool_to_option: dict[str, int | None] = {}
    for bool_str, target_label in data.value_mapping.items():
        if target_label is None:
            bool_to_option[bool_str] = None
        else:
            if target_label not in option_label_to_id:
                raise HTTPException(400, f"Mapping target '{target_label}' is not in enum_options")
            bool_to_option[bool_str] = option_label_to_id[target_label]

    # Check mapping completeness against actual values
    actual_values = await db.fetch(
        """SELECT DISTINCT vb.value FROM values_bool vb
           JOIN entries e ON e.id = vb.entry_id
           WHERE e.metric_id = $1 AND e.user_id = $2""",
        metric_id, user_id,
    )
    for r in actual_values:
        key = str(r["value"]).lower()
        if key not in data.value_mapping:
            raise HTTPException(400, f"Mapping is incomplete — missing value: {key}")

    # Batch DELETE entries mapped to null
    deleted = 0
    for bool_str, opt_id in bool_to_option.items():
        if opt_id is not None:
            continue
        bool_val = bool_str == "true"
        cnt = await db.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_bool vb ON vb.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2 AND vb.value = $3
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, user_id, bool_val,
        )
        deleted += cnt

    # Batch INSERT into values_enum for each bool→option mapping
    converted = 0
    for bool_str, opt_id in bool_to_option.items():
        if opt_id is None:
            continue
        bool_val = bool_str == "true"
        cnt = await db.fetchval(
            """WITH inserted AS (
                INSERT INTO values_enum (entry_id, selected_option_ids)
                SELECT vb.entry_id, ARRAY[$3]::integer[]
                FROM values_bool vb
                JOIN entries e ON e.id = vb.entry_id
                WHERE e.metric_id = $1 AND e.user_id = $2 AND vb.value = $4
                RETURNING 1
            ) SELECT COUNT(*) FROM inserted""",
            metric_id, user_id, opt_id, bool_val,
        )
        converted += cnt

    # Delete ALL old bool values (including any concurrent inserts)
    await db.execute(
        """DELETE FROM values_bool WHERE entry_id IN (
            SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2
        )""",
        metric_id, user_id,
    )

    # Change metric type to enum
    await db.execute(
        "UPDATE metric_definitions SET type = 'enum' WHERE id = $1",
        metric_id,
    )

    return converted, deleted


async def _convert_enum_to_scale(
    db, metric_id: int, user_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    """Convert enum metric to scale within a transaction (caller must hold FOR UPDATE lock)."""
    if data.scale_min is None or data.scale_max is None or data.scale_step is None:
        raise HTTPException(400, "scale_min, scale_max, scale_step are required for enum→scale conversion")
    if data.scale_min >= data.scale_max:
        raise HTTPException(400, "scale_min must be less than scale_max")
    if data.scale_step < 1 or data.scale_step > (data.scale_max - data.scale_min):
        raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    # Check multi_select
    ec = await db.fetchrow(
        "SELECT multi_select FROM enum_config WHERE metric_id = $1", metric_id,
    )
    if ec and ec["multi_select"]:
        raise HTTPException(400, "Cannot convert multi-select enum to scale")

    # Generate valid scale values
    valid_new_values = set()
    v = data.scale_min
    while v <= data.scale_max:
        valid_new_values.add(v)
        v += data.scale_step

    # Get actual option IDs from values_enum
    actual_options = await db.fetch(
        """SELECT DISTINCT unnest(ve.selected_option_ids) as option_id
           FROM values_enum ve
           JOIN entries e ON e.id = ve.entry_id
           WHERE e.metric_id = $1 AND e.user_id = $2""",
        metric_id, user_id,
    )
    actual_set = {str(r["option_id"]) for r in actual_options}

    # Check mapping completeness
    mapped_keys = set(data.value_mapping.keys())
    missing = actual_set - mapped_keys
    if missing:
        raise HTTPException(400, f"Mapping is incomplete — missing values: {', '.join(sorted(missing))}")

    # Validate new values
    for old_str, new_str in data.value_mapping.items():
        if new_str is not None:
            try:
                new_val = int(new_str)
            except ValueError:
                raise HTTPException(400, f"Invalid new value: {new_str}")
            if new_val not in valid_new_values:
                raise HTTPException(
                    400,
                    f"New value {new_val} is not in valid range "
                    f"[{data.scale_min}..{data.scale_max}] step {data.scale_step}",
                )

    # DELETE entries mapped to None (by option_id in selected_option_ids)
    deleted = 0
    for old_str, new_str in data.value_mapping.items():
        if new_str is not None:
            continue
        oid = int(old_str)
        cnt = await db.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_enum ve ON ve.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2
                    AND ve.selected_option_ids = ARRAY[$3]::integer[]
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, user_id, oid,
        )
        deleted += cnt

    # INSERT values_scale from values_enum for each option_id → scale_value
    converted = 0
    for old_str, new_str in data.value_mapping.items():
        if new_str is None:
            continue
        oid = int(old_str)
        scale_val = int(new_str)
        cnt = await db.fetchval(
            """WITH inserted AS (
                INSERT INTO values_scale (entry_id, value, scale_min, scale_max, scale_step)
                SELECT ve.entry_id, $3, $4, $5, $6
                FROM values_enum ve
                JOIN entries e ON e.id = ve.entry_id
                WHERE e.metric_id = $1 AND e.user_id = $2
                AND ve.selected_option_ids = ARRAY[$7]::integer[]
                RETURNING 1
            ) SELECT COUNT(*) FROM inserted""",
            metric_id, user_id, scale_val, data.scale_min, data.scale_max, data.scale_step, oid,
        )
        converted += cnt

    # Delete ALL values_enum for this metric
    await db.execute(
        """DELETE FROM values_enum WHERE entry_id IN (
            SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2
        )""",
        metric_id, user_id,
    )

    # Delete enum_options, enum_config
    await db.execute("DELETE FROM enum_options WHERE metric_id = $1", metric_id)
    await db.execute("DELETE FROM enum_config WHERE metric_id = $1", metric_id)

    # Insert scale_config with labels
    labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
    await db.execute(
        """INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels)
           VALUES ($1, $2, $3, $4, $5::jsonb)""",
        metric_id, data.scale_min, data.scale_max, data.scale_step, labels_json,
    )

    # Change metric type to scale
    await db.execute(
        "UPDATE metric_definitions SET type = 'scale' WHERE id = $1",
        metric_id,
    )

    return converted, deleted
