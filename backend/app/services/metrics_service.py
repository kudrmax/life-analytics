"""Service layer for metrics — CRUD, configuration, validation."""

import json
import re

from app.domain.exceptions import InvalidOperationError, ConflictError
from app.formula import validate_formula, get_referenced_metric_ids
from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS, ACTIVITYWATCH_ICON
from app.services.metric_builder import build_metric_out
from app.services.daily_helpers import build_interval_label_map
from app.repositories.metric_repository import MetricRepository
from app.repositories.metric_config_repository import MetricConfigRepository
from app.domain.enums import MetricType
from app.schemas import MetricDefinitionCreate, MetricDefinitionUpdate, MetricDefinitionOut
from app.services.metric_conversion_service import MetricConversionService, ALLOWED_CONVERSIONS


def _generate_slug(name: str) -> str:
    slug = name.lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_а-яё]", "", slug)
    return slug or f"metric_{int(__import__('time').time())}"


class MetricsService:
    def __init__(self, repo: MetricRepository, cfg_repo: MetricConfigRepository, conn) -> None:
        self.repo = repo
        self.cfg_repo = cfg_repo
        self.conn = conn

    async def list_all(self, enabled_only: bool, privacy_mode: bool) -> list[MetricDefinitionOut]:
        rows = await self.repo.get_all_with_config(enabled_only)
        metric_ids = [r["id"] for r in rows]
        slots_map = await self.repo.get_slots_for_metrics(metric_ids) if metric_ids else {}
        enum_opts_map = await self.repo.get_enum_options_for_metrics(metric_ids) if metric_ids else {}
        has_interval = any(r.get("interval_binding") in ("fixed", "floating") for r in rows)
        if has_interval:
            interval_labels = await self._load_interval_labels()
            self._apply_interval_labels(slots_map, rows, interval_labels)
        return [await build_metric_out(r, slots_map.get(r["id"]), enum_opts_map.get(r["id"]), privacy_mode) for r in rows]

    async def get_one(self, metric_id: int, privacy_mode: bool) -> MetricDefinitionOut:
        row = await self.repo.get_one_with_config(metric_id)
        slots_map = await self.repo.get_slots_for_metrics([metric_id])
        enum_opts_map = await self.repo.get_enum_options_for_metrics([metric_id])
        if row.get("interval_binding") in ("fixed", "floating"):
            interval_labels = await self._load_interval_labels()
            self._apply_interval_labels(slots_map, [row], interval_labels)
        return await build_metric_out(row, slots_map.get(metric_id), enum_opts_map.get(metric_id), privacy_mode)

    async def _load_interval_labels(self) -> dict[int, str]:
        user_slots = await self.repo.get_user_slots_ordered()
        return build_interval_label_map(user_slots)

    @staticmethod
    def _apply_interval_labels(slots_map: dict, rows: list, interval_labels: dict[int, str]) -> None:
        for r in rows:
            if r.get("interval_binding") not in ("fixed", "floating"):
                continue
            mid = r["id"]
            if mid not in slots_map:
                continue
            for slot in slots_map[mid]:
                new_label = interval_labels.get(slot["id"])
                if new_label:
                    slot["label"] = new_label

    async def reorder(self, items: list[dict]) -> None:
        await self.repo.reorder(items)

    async def create(self, data: MetricDefinitionCreate, privacy_mode: bool) -> MetricDefinitionOut:
        await self._validate_integration(data)
        self._validate_enum(data)
        slug = await self._resolve_slug(data)
        self._validate_scale(data)
        icon = _resolve_icon(data)
        cat_id = await self._resolve_category(data)

        metric_id = await self.repo.create_metric(
            slug, data.name, cat_id, icon, data.type.value,
            data.enabled, data.sort_order, data.private, data.description,
            data.hide_in_cards, data.is_checkpoint,
            data.interval_binding, data.interval_start_slot_id,
        )
        await self._create_type_config(metric_id, data)
        await self._create_slot_configs(metric_id, data)
        await self._create_interval_slots(metric_id, data.interval_binding, data.interval_start_slot_id)
        await self._create_condition(metric_id, data)
        return await self.get_one(metric_id, privacy_mode)

    async def update(self, metric_id: int, data: MetricDefinitionUpdate, privacy_mode: bool) -> MetricDefinitionOut:
        row = await self.repo.get_by_id(metric_id)
        await self._apply_field_updates(metric_id, row, data)
        await self._update_scale_config(metric_id, row, data)
        await self._update_computed_config(metric_id, row, data)
        await self._update_enum_config(metric_id, row, data)
        await self._update_slot_configs(metric_id, data)
        await self._update_interval_binding(metric_id, row, data)
        await self._update_condition(metric_id, data)
        return await self.get_one(metric_id, privacy_mode)

    async def delete(self, metric_id: int) -> None:
        await self.repo.delete_metric(metric_id)

    def conversion_service(self) -> MetricConversionService:
        return MetricConversionService(self.cfg_repo, self.conn)

    async def convert_preview(self, metric_id: int, target_type) -> dict:
        row = await self.repo.get_by_id_columns(metric_id, "id, type")
        return await self.conversion_service().preview(metric_id, row["type"], target_type)

    async def convert(self, metric_id: int, data) -> dict:
        async with self.repo.transaction():
            row = await self.repo.get_by_id_for_update(metric_id)
            return await self.conversion_service().convert(metric_id, row["type"], data)

    # ── Markdown export ───────────────────────────────────────────

    async def export_markdown(self) -> str:
        from app.services.metric_markdown_service import build_markdown_table
        rows = await self.repo.get_all_with_config()
        metric_ids = [r["id"] for r in rows]
        slots_map = await self.repo.get_slots_for_metrics(metric_ids) if metric_ids else {}
        enum_opts_map = await self.repo.get_enum_options_for_metrics(metric_ids) if metric_ids else {}
        metrics = [await build_metric_out(r, slots_map.get(r["id"]), enum_opts_map.get(r["id"]), False) for r in rows]
        cat_rows = await self.repo.get_all_categories()
        return build_markdown_table(metrics, cat_rows)

    # ── Validation helpers ────────────────────────────────────────

    async def _validate_integration(self, data: MetricDefinitionCreate) -> None:
        if data.type != MetricType.integration:
            return
        if not data.provider:
            raise InvalidOperationError("provider is required for integration metrics")
        if not data.metric_key:
            raise InvalidOperationError("metric_key is required for integration metrics")
        if data.provider == "todoist":
            if data.metric_key not in TODOIST_METRICS:
                raise InvalidOperationError(f"Unknown metric_key: {data.metric_key}")
            if not await self.repo.check_todoist_connected():
                raise InvalidOperationError("Todoist is not connected")
            if data.metric_key == "filter_tasks_count" and (not data.filter_name or not data.filter_name.strip()):
                raise InvalidOperationError("filter_name is required for filter_tasks_count")
            elif data.metric_key == "query_tasks_count" and (not data.filter_query or not data.filter_query.strip()):
                raise InvalidOperationError("filter_query is required for query_tasks_count")
        elif data.provider == "activitywatch":
            if data.metric_key not in ACTIVITYWATCH_METRICS:
                raise InvalidOperationError(f"Unknown metric_key: {data.metric_key}")
            if not await self.repo.check_aw_enabled():
                raise InvalidOperationError("ActivityWatch is not enabled")
            if data.metric_key == "category_time":
                if not data.activitywatch_category_id:
                    raise InvalidOperationError("activitywatch_category_id is required for category_time")
                if not await self.repo.check_aw_category(data.activitywatch_category_id):
                    raise InvalidOperationError("Category not found")
            elif data.metric_key == "app_time" and (not data.app_name or not data.app_name.strip()):
                raise InvalidOperationError("app_name is required for app_time")
        else:
            raise InvalidOperationError(f"Unknown provider: {data.provider}")

    @staticmethod
    def _validate_enum(data: MetricDefinitionCreate) -> None:
        if data.type != MetricType.enum:
            return
        if not data.enum_options or len(data.enum_options) < 2:
            raise InvalidOperationError("Enum metrics need at least 2 options")
        if len(set(data.enum_options)) != len(data.enum_options):
            raise InvalidOperationError("Enum option labels must be unique")

    async def _resolve_slug(self, data: MetricDefinitionCreate) -> str:
        if data.slug:
            if await self.repo.slug_exists(data.slug):
                raise ConflictError("Metric with this slug already exists")
            return data.slug
        return await self.repo.unique_slug(_generate_slug(data.name))

    @staticmethod
    def _validate_scale(data: MetricDefinitionCreate) -> None:
        if data.type != MetricType.scale:
            return
        s_min = data.scale_min if data.scale_min is not None else 1
        s_max = data.scale_max if data.scale_max is not None else 5
        s_step = data.scale_step if data.scale_step is not None else 1
        if s_min >= s_max:
            raise InvalidOperationError("scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise InvalidOperationError("scale_step must be >= 1 and <= (max - min)")

    async def _resolve_category(self, data: MetricDefinitionCreate) -> int | None:
        if data.new_category_name:
            return await self.cfg_repo.create_inline_category(data.new_category_name.strip(), data.new_category_parent_id)
        return data.category_id

    async def _create_type_config(self, metric_id: int, data: MetricDefinitionCreate) -> None:
        if data.type == MetricType.integration:
            vt = ACTIVITYWATCH_METRICS[data.metric_key]["value_type"] if data.provider == "activitywatch" else TODOIST_METRICS[data.metric_key]["value_type"]
            await self.cfg_repo.insert_integration_config(metric_id, data.provider, data.metric_key, vt)
            if data.metric_key == "filter_tasks_count":
                await self.cfg_repo.insert_integration_filter_config(metric_id, data.filter_name.strip())
            elif data.metric_key == "query_tasks_count":
                await self.cfg_repo.insert_integration_query_config(metric_id, data.filter_query.strip())
            elif data.metric_key == "category_time":
                await self.cfg_repo.insert_integration_category_config(metric_id, data.activitywatch_category_id)
            elif data.metric_key == "app_time":
                await self.cfg_repo.insert_integration_app_config(metric_id, data.app_name.strip())
        if data.type == MetricType.scale:
            s_min = data.scale_min if data.scale_min is not None else 1
            s_max = data.scale_max if data.scale_max is not None else 5
            s_step = data.scale_step if data.scale_step is not None else 1
            await self.cfg_repo.insert_scale_config(metric_id, s_min, s_max, s_step, json.dumps(data.scale_labels) if data.scale_labels else None)
        if data.type == MetricType.enum:
            await self.cfg_repo.insert_enum_config(metric_id, data.multi_select if data.multi_select is not None else False)
            for i, label in enumerate(data.enum_options):
                await self.cfg_repo.insert_enum_option(metric_id, i, label)
        if data.type == MetricType.computed:
            await self._validate_and_save_formula(metric_id, data.formula, data.result_type)

    async def _create_slot_configs(self, metric_id: int, data: MetricDefinitionCreate) -> None:
        if data.type in (MetricType.computed, MetricType.integration, MetricType.text):
            return
        if not data.slot_configs or len(data.slot_configs) < 2:
            return
        for i, cfg in enumerate(data.slot_configs):
            sid = cfg.get("slot_id")
            if sid is None:
                raise InvalidOperationError("slot_id is required in slot_configs")
            if not await self.cfg_repo.check_slot_ownership(sid):
                raise InvalidOperationError(f"Slot {sid} not found")
            await self.cfg_repo.insert_metric_slot(metric_id, sid, i, None)

    async def _create_condition(self, metric_id: int, data: MetricDefinitionCreate) -> None:
        if data.condition_metric_id is not None and data.condition_type is not None:
            await self._validate_and_save_condition(metric_id, data.condition_metric_id, data.condition_type, data.condition_value)

    async def _apply_field_updates(self, metric_id: int, row, data: MetricDefinitionUpdate) -> None:
        updates = {}
        for field in ("name", "enabled", "sort_order", "private", "hide_in_cards", "is_checkpoint", "interval_binding", "interval_start_slot_id"):
            val = getattr(data, field)
            if val is not None:
                updates[field] = val
        if data.category_id is not None:
            updates["category_id"] = data.category_id if data.category_id != 0 else None
        if data.icon is not None and row["type"] != "integration":
            updates["icon"] = data.icon
        if data.description is not None:
            updates["description"] = data.description or None
        if updates:
            await self.repo.update_fields(metric_id, updates)

    async def _update_scale_config(self, metric_id: int, row, data: MetricDefinitionUpdate) -> None:
        if row["type"] != "scale" or not any(getattr(data, f) is not None for f in ("scale_min", "scale_max", "scale_step", "scale_labels")):
            return
        cfg = await self.cfg_repo.get_scale_config(metric_id)
        s_min = data.scale_min if data.scale_min is not None else (cfg["scale_min"] if cfg else 1)
        s_max = data.scale_max if data.scale_max is not None else (cfg["scale_max"] if cfg else 5)
        s_step = data.scale_step if data.scale_step is not None else (cfg["scale_step"] if cfg else 1)
        if s_min >= s_max:
            raise InvalidOperationError("scale_min must be less than scale_max")
        if s_step < 1 or s_step > (s_max - s_min):
            raise InvalidOperationError("scale_step must be >= 1 and <= (max - min)")
        if data.scale_labels is not None:
            labels_json = json.dumps(data.scale_labels) if data.scale_labels else None
        else:
            labels_json = cfg["labels"] if cfg else None
        await self.cfg_repo.upsert_scale_config(metric_id, s_min, s_max, s_step, labels_json, cfg is not None)

    async def _update_computed_config(self, metric_id: int, row, data: MetricDefinitionUpdate) -> None:
        if row["type"] != "computed" or (data.formula is None and data.result_type is None):
            return
        cfg = await self.cfg_repo.get_computed_config(metric_id)
        new_formula = data.formula if data.formula is not None else (json.loads(cfg["formula"]) if cfg and cfg["formula"] else [])
        new_rt = data.result_type if data.result_type is not None else (cfg["result_type"] if cfg else "float")
        await self._validate_formula_logic(new_formula, new_rt)
        await self.cfg_repo.upsert_computed_config(metric_id, new_formula, new_rt, cfg is not None)

    async def _update_enum_config(self, metric_id: int, row, data: MetricDefinitionUpdate) -> None:
        if row["type"] != "enum":
            return
        if data.multi_select is not None:
            cfg = await self.cfg_repo.get_enum_config(metric_id)
            await self.cfg_repo.upsert_enum_config_multi_select(metric_id, data.multi_select, cfg is not None)
        if data.enum_options is not None:
            labels = [o["label"] for o in data.enum_options if o.get("label")]
            if len(labels) < 2:
                raise InvalidOperationError("Enum metrics need at least 2 options")
            if len(set(labels)) != len(labels):
                raise InvalidOperationError("Enum option labels must be unique")
            existing_opts = await self.cfg_repo.get_enum_options(metric_id)
            existing_ids = {o["id"] for o in existing_opts}
            seen_ids: set[int] = set()
            for i, opt in enumerate(data.enum_options):
                opt_id = opt.get("id")
                if opt_id and opt_id in existing_ids:
                    seen_ids.add(opt_id)
                    await self.cfg_repo.update_enum_option(opt_id, opt["label"], i)
                else:
                    await self.cfg_repo.insert_enum_option(metric_id, i, opt["label"])
            for o in existing_opts:
                if o["id"] not in seen_ids:
                    await self.cfg_repo.disable_enum_option(o["id"])

    async def _update_slot_configs(self, metric_id: int, data: MetricDefinitionUpdate) -> None:
        if data.slot_configs is None:
            return
        existing = await self.cfg_repo.get_metric_slots(metric_id)
        if len(data.slot_configs) < 2:
            if existing:
                raise InvalidOperationError("Cannot reduce to fewer than 2 slots once configured")
            return
        for cfg in data.slot_configs:
            sid = cfg.get("slot_id")
            if sid is None:
                raise InvalidOperationError("slot_id is required in slot_configs")
            if not await self.cfg_repo.check_slot_ownership(sid):
                raise InvalidOperationError(f"Slot {sid} not found")

        if not existing:
            first_slot_id = None
            for i, cfg in enumerate(data.slot_configs):
                await self.cfg_repo.insert_metric_slot(metric_id, cfg["slot_id"], i, None)
                if i == 0:
                    first_slot_id = cfg["slot_id"]
            if first_slot_id:
                await self.cfg_repo.migrate_null_slot_entries(metric_id, first_slot_id)
        else:
            existing_by_slot = {s["slot_id"]: s for s in existing}
            seen: set[int] = set()
            for i, cfg in enumerate(data.slot_configs):
                sid = cfg["slot_id"]
                seen.add(sid)
                if sid in existing_by_slot:
                    await self.cfg_repo.update_metric_slot(metric_id, sid, None, i)
                else:
                    await self.cfg_repo.insert_metric_slot(metric_id, sid, i, None)
            for s in existing:
                if s["slot_id"] not in seen:
                    await self.cfg_repo.disable_metric_slot(metric_id, s["slot_id"])

    async def _create_interval_slots(self, metric_id: int, binding: str, start_slot_id: int | None) -> None:
        """Auto-create metric_slots for interval-bound facts."""
        if binding == "daily":
            return
        if binding == "fixed" and start_slot_id is None:
            raise InvalidOperationError("interval_start_slot_id is required for fixed binding")
        user_slots = await self.repo.get_user_slots_ordered()
        if len(user_slots) < 2:
            return
        if binding == "floating":
            for i, slot in enumerate(user_slots[:-1]):
                await self.cfg_repo.insert_metric_slot(metric_id, slot["id"], i, None)
        elif binding == "fixed":
            await self.cfg_repo.insert_metric_slot(metric_id, start_slot_id, 0, None)

    async def _update_interval_binding(self, metric_id: int, row, data: MetricDefinitionUpdate) -> None:
        """Handle interval_binding changes — recreate metric_slots."""
        if data.interval_binding is None:
            return
        old_binding = row.get("interval_binding", "daily")
        if data.interval_binding == old_binding and data.interval_start_slot_id is None:
            return
        # Remove old interval slots
        if old_binding in ("floating", "fixed"):
            existing = await self.cfg_repo.get_metric_slots(metric_id)
            for s in existing:
                await self.cfg_repo.disable_metric_slot(metric_id, s["slot_id"])
        # Create new interval slots
        start_slot_id = data.interval_start_slot_id or row.get("interval_start_slot_id")
        await self._create_interval_slots(metric_id, data.interval_binding, start_slot_id)

    async def _update_condition(self, metric_id: int, data: MetricDefinitionUpdate) -> None:
        if data.remove_condition:
            await self.cfg_repo.delete_condition(metric_id)
        elif data.condition_metric_id is not None and data.condition_type is not None:
            await self._validate_and_save_condition(metric_id, data.condition_metric_id, data.condition_type, data.condition_value)

    async def _validate_and_save_condition(self, metric_id: int, dep_id: int, cond_type: str, cond_value) -> None:
        if cond_type not in ("filled", "equals", "not_equals"):
            raise InvalidOperationError("condition_type must be 'filled', 'equals', or 'not_equals'")
        if dep_id == metric_id:
            raise InvalidOperationError("Metric cannot depend on itself")
        try:
            await self.repo.get_by_id_columns(dep_id, "id")
        except Exception:
            raise InvalidOperationError("Dependency metric not found")
        if cond_type in ("equals", "not_equals") and cond_value is None:
            raise InvalidOperationError("condition_value is required for equals/not_equals")
        cycle_check = await self.cfg_repo.get_condition_dependency(dep_id)
        if cycle_check == metric_id:
            raise InvalidOperationError("Circular dependency detected")
        await self.cfg_repo.insert_or_update_condition(metric_id, dep_id, cond_type, cond_value)

    async def _validate_and_save_formula(self, metric_id: int, formula, result_type: str) -> None:
        if not formula:
            raise InvalidOperationError("formula is required for computed metrics")
        if result_type not in ("bool", "int", "float", "time", "duration"):
            raise InvalidOperationError("result_type must be one of: bool, int, float, time, duration")
        await self._validate_formula_logic(formula, result_type)
        await self.cfg_repo.insert_computed_config(metric_id, formula, result_type)

    async def _validate_formula_logic(self, formula, result_type: str) -> None:
        ref_ids = get_referenced_metric_ids(formula)
        if ref_ids:
            source_rows = await self.repo.get_types_by_ids(ref_ids)
            if len(source_rows) != len(set(ref_ids)):
                raise InvalidOperationError("Formula references unknown metrics")
            err = validate_formula(formula, {r["id"]: r["type"] for r in source_rows})
            if err:
                raise InvalidOperationError(err)
        if any(t.get("type") == "op" and t.get("value") in (">", "<") for t in formula) and result_type != "bool":
            raise InvalidOperationError("Формула со сравнением должна иметь тип результата bool")


def _resolve_icon(data: MetricDefinitionCreate) -> str | None:
    if data.type == MetricType.integration:
        return ACTIVITYWATCH_ICON if data.provider == "activitywatch" else TODOIST_ICON
    return data.icon
