import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

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
from app.repositories.metric_repository import MetricRepository
from app.repositories.metric_config_repository import MetricConfigRepository
from app.repositories.metric_conversion_repository import MetricConversionRepository


def _generate_slug(name: str) -> str:
    """Generate a slug from metric name: lowercase, spaces to underscores, strip special chars."""
    slug = name.lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_а-яё]", "", slug)
    return slug or f"metric_{int(__import__('time').time())}"


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


_TYPE_LABELS: dict[str, str] = {
    "bool": "Да/Нет",
    "number": "Число",
    "scale": "Шкала",
    "enum": "Варианты",
    "time": "Время",
    "duration": "Длительность",
    "computed": "Формула",
    "integration": "Интеграция",
    "text": "Заметка",
}

_RESULT_TYPE_LABELS: dict[str, str] = {
    "float": "число",
    "int": "целое",
    "bool": "да/нет",
    "time": "время",
    "duration": "длительность",
}


def _esc_md(s: str) -> str:
    """Escape pipe characters for Markdown table cells."""
    return s.replace("|", "\\|")


def _get_details(m: MetricDefinitionOut, metric_name_by_id: dict[int, str]) -> str:
    if m.type == "scale":
        smin = m.scale_min if m.scale_min is not None else 1
        smax = m.scale_max if m.scale_max is not None else 10
        sstep = m.scale_step if m.scale_step is not None else 1
        return f"{smin}–{smax}, шаг {sstep}"
    if m.type == "enum":
        opts = ", ".join(
            o["label"] for o in (m.enum_options or []) if o.get("enabled") is not False
        )
        return opts + (" (мультивыбор)" if m.multi_select else "")
    if m.type == "computed" and m.formula:
        parts: list[str] = []
        for t in m.formula:
            tt = t.get("type", "") if isinstance(t, dict) else ""
            if tt == "metric":
                parts.append(metric_name_by_id.get(t["id"], f"#{t['id']}"))
            elif tt == "op":
                parts.append(t["value"])
            elif tt == "number":
                parts.append(str(t["value"]))
            elif tt == "lparen":
                parts.append("(")
            elif tt == "rparen":
                parts.append(")")
        rt = _RESULT_TYPE_LABELS.get(m.result_type or "", m.result_type or "число")
        return f"{' '.join(parts)} → {rt}"
    if m.type == "integration":
        prov = "ActivityWatch" if m.provider == "activitywatch" else "Todoist"
        detail = f"{prov}: {m.metric_key or '?'}"
        if m.filter_name:
            detail += f" ({m.filter_name})"
        elif m.filter_query:
            detail += f" ({m.filter_query})"
        elif m.config_app_name:
            detail += f" ({m.config_app_name})"
        return detail
    return ""


def _get_cat_path(category_id: int | None, cat_by_id: dict[int, dict]) -> str:
    if not category_id:
        return ""
    cat = cat_by_id.get(category_id)
    if not cat:
        return ""
    parent_name = cat.get("_parent_name")
    return f"{parent_name} / {cat['name']}" if parent_name else cat["name"]


def _get_slots(m: MetricDefinitionOut) -> str:
    return ", ".join(s.label for s in (m.slots or []))


@router.get("/export/markdown")
async def export_metrics_markdown(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> Response:
    """Return all user metrics as a Markdown table."""
    repo = MetricRepository(db, current_user["id"])
    rows = await repo.get_all_with_config()
    metric_ids = [r["id"] for r in rows]
    slots_map = await get_metric_slots(db, metric_ids) if metric_ids else {}
    enum_opts_map = await get_enum_options(db, metric_ids) if metric_ids else {}

    metrics = [
        await build_metric_out(r, slots_map.get(r["id"]), enum_opts_map.get(r["id"]), False)
        for r in rows
    ]

    cat_rows = await repo.get_all_categories()
    cat_by_id: dict[int, dict] = {}
    for cr in cat_rows:
        cat_by_id[cr["id"]] = {"name": cr["name"], "parent_id": cr["parent_id"]}
    for cid, cat in cat_by_id.items():
        pid = cat["parent_id"]
        if pid and pid in cat_by_id:
            cat["_parent_name"] = cat_by_id[pid]["name"]

    metric_name_by_id = {m.id: m.name for m in metrics}
    sorted_metrics = [m for m in metrics if m.enabled] + [m for m in metrics if not m.enabled]

    lines = [
        "| Иконка | Название | Описание | Тип | Категория | Слоты | Детали | Статус |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m in sorted_metrics:
        icon = _esc_md(m.icon or "")
        name = _esc_md(m.name)
        desc = _esc_md(m.description or "")
        type_label = _esc_md(_TYPE_LABELS.get(m.type, m.type))
        cat = _esc_md(_get_cat_path(m.category_id, cat_by_id))
        slots = _esc_md(_get_slots(m))
        details = _esc_md(_get_details(m, metric_name_by_id))
        status = "" if m.enabled else "❌ архив"
        lines.append(f"| {icon} | {name} | {desc} | {type_label} | {cat} | {slots} | {details} | {status} |")

    text = "\n".join(lines)
    return Response(content=text, media_type="text/markdown")


@router.get("", response_model=list[MetricDefinitionOut])
async def list_metrics(
    enabled_only: bool = False,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    repo = MetricRepository(db, current_user["id"])
    rows = await repo.get_all_with_config(enabled_only)

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
    repo = MetricRepository(db, current_user["id"])
    await repo.reorder(items)
    return {"ok": True}


@router.get("/{metric_id}", response_model=MetricDefinitionOut)
async def get_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    repo = MetricRepository(db, current_user["id"])
    row = await repo.get_one_with_config(metric_id)

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
    repo = MetricRepository(db, current_user["id"])
    cfg_repo = MetricConfigRepository(db, current_user["id"])

    if data.type == MetricType.integration:
        if not data.provider:
            raise HTTPException(400, "provider is required for integration metrics")
        if not data.metric_key:
            raise HTTPException(400, "metric_key is required for integration metrics")
        if data.provider == "todoist":
            if data.metric_key not in TODOIST_METRICS:
                raise HTTPException(400, f"Unknown metric_key: {data.metric_key}")
            if not await repo.check_todoist_connected():
                raise HTTPException(400, "Todoist is not connected")
            if data.metric_key == "filter_tasks_count":
                if not data.filter_name or not data.filter_name.strip():
                    raise HTTPException(400, "filter_name is required for filter_tasks_count")
            elif data.metric_key == "query_tasks_count":
                if not data.filter_query or not data.filter_query.strip():
                    raise HTTPException(400, "filter_query is required for query_tasks_count")
        elif data.provider == "activitywatch":
            if data.metric_key not in ACTIVITYWATCH_METRICS:
                raise HTTPException(400, f"Unknown metric_key: {data.metric_key}")
            if not await repo.check_aw_enabled():
                raise HTTPException(400, "ActivityWatch is not enabled")
            if data.metric_key == "category_time":
                if not data.activitywatch_category_id:
                    raise HTTPException(400, "activitywatch_category_id is required for category_time")
                if not await repo.check_aw_category(data.activitywatch_category_id):
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

    if data.slug:
        if await repo.slug_exists(data.slug):
            raise HTTPException(409, "Metric with this slug already exists")
        slug = data.slug
    else:
        base_slug = _generate_slug(data.name)
        slug = await repo.unique_slug(base_slug)

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

    cat_id = data.category_id
    if data.new_category_name:
        cat_id = await cfg_repo.create_inline_category(data.new_category_name.strip(), data.new_category_parent_id)

    metric_id = await repo.create_metric(
        slug, data.name, cat_id, icon, data.type.value,
        data.enabled, data.sort_order, data.private, data.description, data.hide_in_cards,
    )

    if data.type == MetricType.integration:
        if data.provider == "activitywatch":
            value_type = ACTIVITYWATCH_METRICS[data.metric_key]["value_type"]
        else:
            value_type = TODOIST_METRICS[data.metric_key]["value_type"]
        await cfg_repo.insert_integration_config(metric_id, data.provider, data.metric_key, value_type)
        if data.metric_key == "filter_tasks_count":
            await cfg_repo.insert_integration_filter_config(metric_id, data.filter_name.strip())
        elif data.metric_key == "query_tasks_count":
            await cfg_repo.insert_integration_query_config(metric_id, data.filter_query.strip())
        elif data.metric_key == "category_time":
            await cfg_repo.insert_integration_category_config(metric_id, data.activitywatch_category_id)
        elif data.metric_key == "app_time":
            await cfg_repo.insert_integration_app_config(metric_id, data.app_name.strip())

    if data.type == MetricType.scale:
        labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
        await cfg_repo.insert_scale_config(metric_id, s_min, s_max, s_step, labels_json)

    if data.type == MetricType.enum:
        multi = data.multi_select if data.multi_select is not None else False
        await cfg_repo.insert_enum_config(metric_id, multi)
        for i, label in enumerate(data.enum_options):
            await cfg_repo.insert_enum_option(metric_id, i, label)

    if data.type == MetricType.computed:
        if not data.formula:
            raise HTTPException(400, "formula is required for computed metrics")
        if data.result_type not in ("bool", "int", "float", "time", "duration"):
            raise HTTPException(400, "result_type must be one of: bool, int, float, time, duration")
        ref_ids = get_referenced_metric_ids(data.formula)
        if ref_ids:
            source_rows = await repo.get_types_by_ids(ref_ids)
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
        await cfg_repo.insert_computed_config(metric_id, data.formula, data.result_type)

    # Link measurement slots if 2+ slot_configs provided
    if data.type not in (MetricType.computed, MetricType.integration, MetricType.text):
        if data.slot_configs and len(data.slot_configs) >= 2:
            for i, cfg in enumerate(data.slot_configs):
                slot_id = cfg.get("slot_id")
                if slot_id is None:
                    raise HTTPException(400, "slot_id is required in slot_configs")
                if not await cfg_repo.check_slot_ownership(slot_id):
                    raise HTTPException(400, f"Slot {slot_id} not found")
                slot_cat_id = cfg.get("category_id")
                if slot_cat_id is not None:
                    if not await cfg_repo.check_category_ownership(slot_cat_id):
                        raise HTTPException(400, f"Category {slot_cat_id} not found")
                await cfg_repo.insert_metric_slot(metric_id, slot_id, i, slot_cat_id)
            await cfg_repo.clear_metric_category(metric_id)

    # Condition
    if data.condition_metric_id is not None and data.condition_type is not None:
        if data.condition_type not in ('filled', 'equals', 'not_equals'):
            raise HTTPException(400, "condition_type must be 'filled', 'equals', or 'not_equals'")
        if data.condition_metric_id == metric_id:
            raise HTTPException(400, "Metric cannot depend on itself")
        try:
            await repo.get_by_id_columns(data.condition_metric_id, "id")
        except Exception:
            raise HTTPException(400, "Dependency metric not found")
        if data.condition_type in ('equals', 'not_equals') and data.condition_value is None:
            raise HTTPException(400, "condition_value is required for equals/not_equals")
        cycle_check = await cfg_repo.get_condition_dependency(data.condition_metric_id)
        if cycle_check == metric_id:
            raise HTTPException(400, "Circular dependency detected")
        await cfg_repo.insert_or_update_condition(
            metric_id, data.condition_metric_id, data.condition_type, data.condition_value,
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
    repo = MetricRepository(db, current_user["id"])
    cfg_repo = MetricConfigRepository(db, current_user["id"])
    row = await repo.get_by_id(metric_id)

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
        await repo.update_fields(metric_id, updates)

    # Update scale_config
    if row["type"] == "scale" and any(
        getattr(data, f) is not None for f in ("scale_min", "scale_max", "scale_step", "scale_labels")
    ):
        cfg = await cfg_repo.get_scale_config(metric_id)
        s_min = data.scale_min if data.scale_min is not None else (cfg["scale_min"] if cfg else 1)
        s_max = data.scale_max if data.scale_max is not None else (cfg["scale_max"] if cfg else 5)
        s_step = data.scale_step if data.scale_step is not None else (cfg["scale_step"] if cfg else 1)
        if s_min >= s_max:
            raise HTTPException(400, "scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")
        if data.scale_labels is not None:
            labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
        else:
            labels_json = cfg["labels"] if cfg else None
        await cfg_repo.upsert_scale_config(metric_id, s_min, s_max, s_step, labels_json, cfg is not None)

    # Update computed_config
    if row["type"] == "computed" and (data.formula is not None or data.result_type is not None):
        cfg = await cfg_repo.get_computed_config(metric_id)
        new_formula = data.formula if data.formula is not None else (json.loads(cfg["formula"]) if cfg and cfg["formula"] else [])
        new_result_type = data.result_type if data.result_type is not None else (cfg["result_type"] if cfg else "float")
        if new_result_type not in ("bool", "int", "float", "time"):
            raise HTTPException(400, "result_type must be one of: bool, int, float, time, duration")
        ref_ids = get_referenced_metric_ids(new_formula)
        if ref_ids:
            source_rows = await repo.get_types_by_ids(ref_ids)
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
        await cfg_repo.upsert_computed_config(metric_id, new_formula, new_result_type, cfg is not None)

    # Update enum config
    if row["type"] == "enum":
        if data.multi_select is not None:
            cfg = await cfg_repo.get_enum_config(metric_id)
            await cfg_repo.upsert_enum_config_multi_select(metric_id, data.multi_select, cfg is not None)

        if data.enum_options is not None:
            new_opts = data.enum_options
            labels = [o["label"] for o in new_opts if o.get("label")]
            if len(labels) < 2:
                raise HTTPException(400, "Enum metrics need at least 2 options")
            if len(set(labels)) != len(labels):
                raise HTTPException(400, "Enum option labels must be unique")

            existing_opts = await cfg_repo.get_enum_options(metric_id)
            existing_ids = {o["id"] for o in existing_opts}
            seen_ids = set()

            for i, opt in enumerate(new_opts):
                opt_id = opt.get("id")
                label = opt["label"]
                if opt_id and opt_id in existing_ids:
                    seen_ids.add(opt_id)
                    await cfg_repo.update_enum_option(opt_id, label, i)
                else:
                    await cfg_repo.insert_enum_option(metric_id, i, label)

            for o in existing_opts:
                if o["id"] not in seen_ids:
                    await cfg_repo.disable_enum_option(o["id"])

    # Update metric slots
    if data.slot_configs is not None:
        existing_slots = await cfg_repo.get_metric_slots(metric_id)
        has_existing_slots = len(existing_slots) > 0

        if len(data.slot_configs) < 2:
            if has_existing_slots:
                raise HTTPException(400, "Cannot reduce to fewer than 2 slots once configured")
        else:
            for cfg in data.slot_configs:
                sid = cfg.get("slot_id")
                if sid is None:
                    raise HTTPException(400, "slot_id is required in slot_configs")
                if not await cfg_repo.check_slot_ownership(sid):
                    raise HTTPException(400, f"Slot {sid} not found")
                slot_cat_id = cfg.get("category_id")
                if slot_cat_id is not None:
                    if not await cfg_repo.check_category_ownership(slot_cat_id):
                        raise HTTPException(400, f"Category {slot_cat_id} not found")

            if not has_existing_slots:
                first_slot_id = None
                for i, cfg in enumerate(data.slot_configs):
                    sid = cfg["slot_id"]
                    await cfg_repo.insert_metric_slot(metric_id, sid, i, cfg.get("category_id"))
                    if i == 0:
                        first_slot_id = sid
                if first_slot_id:
                    await cfg_repo.migrate_null_slot_entries(metric_id, first_slot_id)
            else:
                existing_by_slot_id = {s["slot_id"]: s for s in existing_slots}
                seen_slot_ids: set[int] = set()

                for i, cfg in enumerate(data.slot_configs):
                    sid = cfg["slot_id"]
                    seen_slot_ids.add(sid)
                    if sid in existing_by_slot_id:
                        await cfg_repo.update_metric_slot(metric_id, sid, cfg.get("category_id"), i)
                    else:
                        await cfg_repo.insert_metric_slot(metric_id, sid, i, cfg.get("category_id"))
                for s in existing_slots:
                    if s["slot_id"] not in seen_slot_ids:
                        await cfg_repo.disable_metric_slot(metric_id, s["slot_id"])

            await cfg_repo.clear_metric_category(metric_id)

    # Update condition
    if data.remove_condition:
        await cfg_repo.delete_condition(metric_id)
    elif data.condition_metric_id is not None and data.condition_type is not None:
        if data.condition_type not in ('filled', 'equals', 'not_equals'):
            raise HTTPException(400, "condition_type must be 'filled', 'equals', or 'not_equals'")
        if data.condition_metric_id == metric_id:
            raise HTTPException(400, "Metric cannot depend on itself")
        try:
            await repo.get_by_id_columns(data.condition_metric_id, "id")
        except Exception:
            raise HTTPException(400, "Dependency metric not found")
        if data.condition_type in ('equals', 'not_equals') and data.condition_value is None:
            raise HTTPException(400, "condition_value is required for equals/not_equals")
        cycle_check = await cfg_repo.get_condition_dependency(data.condition_metric_id)
        if cycle_check == metric_id:
            raise HTTPException(400, "Circular dependency detected")
        await cfg_repo.insert_or_update_condition(
            metric_id, data.condition_metric_id, data.condition_type, data.condition_value,
        )

    return await get_metric(metric_id, db, current_user, privacy_mode)


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = MetricRepository(db, current_user["id"])
    await repo.delete_metric(metric_id)


# ── Metric conversion ──────────────────────────────────────────────

ALLOWED_CONVERSIONS: dict[str, list[str]] = {
    "scale": ["scale"],
    "bool": ["enum"],
    "enum": ["scale"],
}


@router.get("/{metric_id}/convert/preview", response_model=ConversionPreview)
async def convert_preview(
    metric_id: int,
    target_type: MetricType,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = MetricRepository(db, current_user["id"])
    conv = MetricConversionRepository(db, current_user["id"])
    row = await repo.get_by_id_columns(metric_id, "id, type")

    source_type = row["type"]
    allowed = ALLOWED_CONVERSIONS.get(source_type, [])
    if target_type.value not in allowed:
        raise HTTPException(400, f"Conversion from {source_type} to {target_type.value} is not supported")

    entries_by_value: list[dict] = []
    total = 0

    if source_type == "scale":
        rows = await conv.get_scale_value_distribution(metric_id)
        for r in rows:
            entries_by_value.append({"value": str(r["value"]), "display": str(r["value"]), "count": r["cnt"]})
            total += r["cnt"]

    elif source_type == "bool":
        rows = await conv.get_bool_value_distribution(metric_id)
        for r in rows:
            display = "Да" if r["value"] else "Нет"
            entries_by_value.append({"value": str(r["value"]).lower(), "display": display, "count": r["cnt"]})
            total += r["cnt"]

    elif source_type == "enum":
        if await conv.get_enum_multi_select(metric_id):
            raise HTTPException(400, "Cannot convert multi-select enum to scale")

        opts = await conv.get_all_enum_options(metric_id)
        opt_labels = {r["id"]: r["label"] for r in opts}

        rows = await conv.get_enum_value_distribution(metric_id)
        for r in rows:
            option_ids = r["selected_option_ids"]
            if option_ids and len(option_ids) == 1:
                oid = option_ids[0]
                label = opt_labels.get(oid, str(oid))
                entries_by_value.append({"value": str(oid), "display": label, "count": r["cnt"]})
                total += r["cnt"]

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
    repo = MetricRepository(db, current_user["id"])
    cfg_repo = MetricConfigRepository(db, current_user["id"])
    conv = MetricConversionRepository(db, current_user["id"])

    async with db.transaction():
        row = await repo.get_by_id_for_update(metric_id)

        source_type = row["type"]
        target_type = data.target_type.value
        allowed = ALLOWED_CONVERSIONS.get(source_type, [])
        if target_type not in allowed:
            raise HTTPException(400, f"Conversion from {source_type} to {target_type} is not supported")

        converted = 0
        deleted = 0

        if source_type == "scale" and target_type == "scale":
            converted, deleted = await _convert_scale_to_scale(cfg_repo, conv, metric_id, data)
        elif source_type == "bool" and target_type == "enum":
            converted, deleted = await _convert_bool_to_enum(cfg_repo, conv, metric_id, data)
        elif source_type == "enum" and target_type == "scale":
            converted, deleted = await _convert_enum_to_scale(cfg_repo, conv, metric_id, data)

    return MetricConvertResponse(converted=converted, deleted=deleted)


async def _convert_scale_to_scale(
    cfg_repo: MetricConfigRepository, conv: MetricConversionRepository,
    metric_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    if data.scale_min is None or data.scale_max is None or data.scale_step is None:
        raise HTTPException(400, "scale_min, scale_max, scale_step are required for scale→scale conversion")
    if data.scale_min >= data.scale_max:
        raise HTTPException(400, "scale_min must be less than scale_max")
    if data.scale_step < 1 or data.scale_step > (data.scale_max - data.scale_min):
        raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    valid_new_values = set()
    v = data.scale_min
    while v <= data.scale_max:
        valid_new_values.add(v)
        v += data.scale_step

    actual_values = await conv.get_distinct_scale_values(metric_id)
    actual_set = {str(r["value"]) for r in actual_values}

    mapped_keys = set(data.value_mapping.keys())
    missing = actual_set - mapped_keys
    if missing:
        raise HTTPException(400, f"Mapping is incomplete — missing values: {', '.join(sorted(missing))}")

    for old_str, new_str in data.value_mapping.items():
        if new_str is not None:
            try:
                new_val = int(new_str)
            except ValueError:
                raise HTTPException(400, f"Invalid new value: {new_str}")
            if new_val not in valid_new_values:
                raise HTTPException(400, f"New value {new_val} is not in valid range [{data.scale_min}..{data.scale_max}] step {data.scale_step}")

    values_to_delete = [int(k) for k, v in data.value_mapping.items() if v is None and k in actual_set]
    deleted = 0
    if values_to_delete:
        deleted = await conv.delete_entries_by_scale_values(metric_id, values_to_delete)

    converted = 0
    mapping = {int(k): int(v) for k, v in data.value_mapping.items() if v is not None}
    if mapping:
        converted = await conv.remap_scale_values(metric_id, mapping, data.scale_min, data.scale_max, data.scale_step)

    await conv.update_scale_config_values(metric_id, data.scale_min, data.scale_max, data.scale_step)

    return converted, deleted


async def _convert_bool_to_enum(
    cfg_repo: MetricConfigRepository, conv: MetricConversionRepository,
    metric_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    if not data.enum_options or len(data.enum_options) < 2:
        raise HTTPException(400, "At least 2 enum_options are required for bool→enum conversion")
    if len(set(data.enum_options)) != len(data.enum_options):
        raise HTTPException(400, "Enum option labels must be unique")

    valid_bool_keys = {"true", "false"}
    for k in data.value_mapping:
        if k not in valid_bool_keys:
            raise HTTPException(400, f"Invalid bool value in mapping: {k}")

    await cfg_repo.insert_enum_config(metric_id, data.multi_select)
    option_label_to_id: dict[str, int] = {}
    for i, label in enumerate(data.enum_options):
        opt_id = await cfg_repo.insert_enum_option(metric_id, i, label)
        option_label_to_id[label] = opt_id

    bool_to_option: dict[str, int | None] = {}
    for bool_str, target_label in data.value_mapping.items():
        if target_label is None:
            bool_to_option[bool_str] = None
        else:
            if target_label not in option_label_to_id:
                raise HTTPException(400, f"Mapping target '{target_label}' is not in enum_options")
            bool_to_option[bool_str] = option_label_to_id[target_label]

    actual_values = await conv.get_distinct_bool_values(metric_id)
    for r in actual_values:
        key = str(r["value"]).lower()
        if key not in data.value_mapping:
            raise HTTPException(400, f"Mapping is incomplete — missing value: {key}")

    deleted = 0
    for bool_str, opt_id in bool_to_option.items():
        if opt_id is not None:
            continue
        bool_val = bool_str == "true"
        deleted += await conv.delete_entries_by_bool_value(metric_id, bool_val)

    converted = 0
    for bool_str, opt_id in bool_to_option.items():
        if opt_id is None:
            continue
        bool_val = bool_str == "true"
        converted += await conv.convert_bool_to_enum_values(metric_id, opt_id, bool_val)

    await conv.delete_all_bool_values(metric_id)
    await cfg_repo.update_metric_type(metric_id, "enum")

    return converted, deleted


async def _convert_enum_to_scale(
    cfg_repo: MetricConfigRepository, conv: MetricConversionRepository,
    metric_id: int, data: MetricConvertRequest,
) -> tuple[int, int]:
    if data.scale_min is None or data.scale_max is None or data.scale_step is None:
        raise HTTPException(400, "scale_min, scale_max, scale_step are required for enum→scale conversion")
    if data.scale_min >= data.scale_max:
        raise HTTPException(400, "scale_min must be less than scale_max")
    if data.scale_step < 1 or data.scale_step > (data.scale_max - data.scale_min):
        raise HTTPException(400, "scale_step must be >= 1 and <= (max - min)")

    if await conv.get_enum_multi_select(metric_id):
        raise HTTPException(400, "Cannot convert multi-select enum to scale")

    valid_new_values = set()
    v = data.scale_min
    while v <= data.scale_max:
        valid_new_values.add(v)
        v += data.scale_step

    actual_options = await conv.get_distinct_enum_option_ids(metric_id)
    actual_set = {str(r["option_id"]) for r in actual_options}

    mapped_keys = set(data.value_mapping.keys())
    missing = actual_set - mapped_keys
    if missing:
        raise HTTPException(400, f"Mapping is incomplete — missing values: {', '.join(sorted(missing))}")

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

    deleted = 0
    for old_str, new_str in data.value_mapping.items():
        if new_str is not None:
            continue
        deleted += await conv.delete_entries_by_enum_option(metric_id, int(old_str))

    converted = 0
    for old_str, new_str in data.value_mapping.items():
        if new_str is None:
            continue
        converted += await conv.convert_enum_to_scale_values(
            metric_id, int(old_str), int(new_str),
            data.scale_min, data.scale_max, data.scale_step,
        )

    await conv.delete_all_enum_values(metric_id)
    await conv.delete_enum_options(metric_id)
    await conv.delete_enum_config(metric_id)
    await conv.insert_scale_config_with_labels(metric_id, data.scale_min, data.scale_max, data.scale_step, data.scale_labels)
    await cfg_repo.update_metric_type(metric_id, "scale")

    return converted, deleted
