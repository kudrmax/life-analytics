import json

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.schemas import MetricDefinitionCreate, MetricDefinitionUpdate, MetricDefinitionOut, MetricType
from app.auth import get_current_user
from app.metric_helpers import build_metric_out, get_metric_slots
from app.formula import validate_formula, get_referenced_metric_ids
from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricDefinitionOut])
async def list_metrics(
    enabled_only: bool = False,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query = """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                      cc.formula, cc.result_type,
                      ic.provider, ic.metric_key, ic.value_type
               FROM metric_definitions md
               LEFT JOIN scale_config sc ON sc.metric_id = md.id
               LEFT JOIN computed_config cc ON cc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               WHERE md.user_id = $1"""
    params = [current_user["id"]]
    if enabled_only:
        query += " AND md.enabled = TRUE"
    query += " ORDER BY md.sort_order, md.id"
    rows = await db.fetch(query, *params)

    metric_ids = [r["id"] for r in rows]
    slots_map = await get_metric_slots(db, metric_ids) if metric_ids else {}

    return [await build_metric_out(r, slots_map.get(r["id"])) for r in rows]


@router.get("/{metric_id}", response_model=MetricDefinitionOut)
async def get_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                  cc.formula, cc.result_type,
                  ic.provider, ic.metric_key, ic.value_type
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")

    slots_map = await get_metric_slots(db, [metric_id])
    return await build_metric_out(row, slots_map.get(metric_id))


@router.post("", response_model=MetricDefinitionOut, status_code=201)
async def create_metric(
    data: MetricDefinitionCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
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
        else:
            raise HTTPException(400, f"Unknown provider: {data.provider}")

    existing = await db.fetchval(
        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
        data.slug, current_user["id"],
    )
    if existing:
        raise HTTPException(409, "Metric with this slug already exists")

    if data.type == MetricType.scale:
        s_min = data.scale_min if data.scale_min is not None else 1
        s_max = data.scale_max if data.scale_max is not None else 5
        s_step = data.scale_step if data.scale_step is not None else 1
        if s_min >= s_max:
            raise HTTPException(400, "scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    icon = TODOIST_ICON if data.type == MetricType.integration else data.icon

    metric_id = await db.fetchval(
        """INSERT INTO metric_definitions
           (user_id, slug, name, category, icon, type, enabled, sort_order)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           RETURNING id""",
        current_user["id"],
        data.slug,
        data.name,
        data.category,
        icon,
        data.type.value,
        data.enabled,
        data.sort_order,
    )

    if data.type == MetricType.integration:
        value_type = TODOIST_METRICS[data.metric_key]["value_type"]
        await db.execute(
            "INSERT INTO integration_config (metric_id, provider, metric_key, value_type) VALUES ($1, $2, $3, $4)",
            metric_id, data.provider, data.metric_key, value_type,
        )

    if data.type == MetricType.scale:
        await db.execute(
            "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4)",
            metric_id, s_min, s_max, s_step,
        )

    if data.type == MetricType.computed:
        if not data.formula:
            raise HTTPException(400, "formula is required for computed metrics")
        if data.result_type not in ("bool", "int", "float", "time"):
            raise HTTPException(400, "result_type must be one of: bool, int, float, time")
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
        await db.execute(
            "INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1, $2::jsonb, $3)",
            metric_id, json.dumps(data.formula), data.result_type,
        )

    # Create measurement slots if 2+ labels provided (skip for computed/integration)
    labels = data.slot_labels or [] if data.type not in (MetricType.computed, MetricType.integration) else []
    if len(labels) >= 2:
        for i, label in enumerate(labels):
            await db.execute(
                "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                metric_id, i, label,
            )

    return await get_metric(metric_id, db, current_user)


@router.patch("/{metric_id}", response_model=MetricDefinitionOut)
async def update_metric(
    metric_id: int,
    data: MetricDefinitionUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
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
    if data.category is not None:
        updates["category"] = data.category
    if data.icon is not None and row["type"] != "integration":
        updates["icon"] = data.icon
    if data.enabled is not None:
        updates["enabled"] = data.enabled
    if data.sort_order is not None:
        updates["sort_order"] = data.sort_order

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
        getattr(data, f) is not None for f in ("scale_min", "scale_max", "scale_step")
    ):
        cfg = await db.fetchrow(
            "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
            metric_id,
        )
        s_min = data.scale_min if data.scale_min is not None else (cfg["scale_min"] if cfg else 1)
        s_max = data.scale_max if data.scale_max is not None else (cfg["scale_max"] if cfg else 5)
        s_step = data.scale_step if data.scale_step is not None else (cfg["scale_step"] if cfg else 1)
        if s_min >= s_max:
            raise HTTPException(400, "scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")
        if cfg:
            await db.execute(
                "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3 WHERE metric_id = $4",
                s_min, s_max, s_step, metric_id,
            )
        else:
            await db.execute(
                "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4)",
                metric_id, s_min, s_max, s_step,
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
            raise HTTPException(400, "result_type must be one of: bool, int, float, time")
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

    # Update measurement slots
    if data.slot_labels is not None:
        new_labels = data.slot_labels
        # Get ALL existing slots (including disabled) sorted by sort_order
        existing_slots = await db.fetch(
            "SELECT * FROM measurement_slots WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )
        has_existing_slots = len(existing_slots) > 0

        if len(new_labels) < 2:
            # Trying to go to 0-1 slots
            if has_existing_slots:
                raise HTTPException(400, "Cannot reduce to fewer than 2 slots once configured")
            # No existing slots and 0-1 labels = no-op
        else:
            # 2+ new labels
            if not has_existing_slots:
                # First time creating slots — create them and migrate NULL entries
                first_slot_id = None
                for i, label in enumerate(new_labels):
                    sid = await db.fetchval(
                        "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3) RETURNING id",
                        metric_id, i, label,
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
                # Update existing slots
                for i, label in enumerate(new_labels):
                    # Find existing slot with this sort_order
                    matching = [s for s in existing_slots if s["sort_order"] == i]
                    if matching:
                        await db.execute(
                            "UPDATE measurement_slots SET label = $1, enabled = TRUE WHERE id = $2",
                            label, matching[0]["id"],
                        )
                    else:
                        await db.execute(
                            "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                            metric_id, i, label,
                        )
                # Disable slots beyond new count
                for s in existing_slots:
                    if s["sort_order"] >= len(new_labels):
                        await db.execute(
                            "UPDATE measurement_slots SET enabled = FALSE WHERE id = $1",
                            s["id"],
                        )

    return await get_metric(metric_id, db, current_user)


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
