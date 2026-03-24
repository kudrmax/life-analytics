"""Metric type conversion logic — extracted from MetricsService for 300-line rule."""

from app.domain.exceptions import InvalidOperationError
from app.repositories.metric_config_repository import MetricConfigRepository
from app.repositories.metric_conversion_repository import MetricConversionRepository
from app.domain.enums import MetricType
from app.schemas import MetricConvertRequest, ConversionPreview, MetricConvertResponse

ALLOWED_CONVERSIONS: dict[MetricType, list[MetricType]] = {
    MetricType.scale: [MetricType.scale],
    MetricType.bool: [MetricType.enum],
    MetricType.enum: [MetricType.scale],
}


class MetricConversionService:
    def __init__(
        self, cfg_repo: MetricConfigRepository, conn,
    ) -> None:
        self.cfg_repo = cfg_repo
        self.conn = conn

    async def preview(
        self, metric_id: int, source_type: MetricType, target_type: MetricType,
    ) -> ConversionPreview:
        conv = MetricConversionRepository(self.conn, self.cfg_repo.user_id)
        allowed = ALLOWED_CONVERSIONS.get(source_type, [])
        if target_type not in allowed:
            raise InvalidOperationError(f"Conversion from {source_type} to {target_type} is not supported")

        entries_by_value: list[dict] = []
        total = 0

        if source_type == MetricType.scale:
            rows = await conv.get_scale_value_distribution(metric_id)
            for r in rows:
                entries_by_value.append({"value": str(r["value"]), "display": str(r["value"]), "count": r["cnt"]})
                total += r["cnt"]
        elif source_type == MetricType.bool:
            rows = await conv.get_bool_value_distribution(metric_id)
            for r in rows:
                display = "Да" if r["value"] else "Нет"
                entries_by_value.append({"value": str(r["value"]).lower(), "display": display, "count": r["cnt"]})
                total += r["cnt"]
        elif source_type == MetricType.enum:
            if await conv.get_enum_multi_select(metric_id):
                raise InvalidOperationError("Cannot convert multi-select enum to scale")
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

    async def convert(
        self, metric_id: int, source_type: MetricType, data: MetricConvertRequest,
    ) -> MetricConvertResponse:
        conv = MetricConversionRepository(self.conn, self.cfg_repo.user_id)
        target_type = data.target_type
        allowed = ALLOWED_CONVERSIONS.get(source_type, [])
        if target_type not in allowed:
            raise InvalidOperationError(f"Conversion from {source_type} to {target_type} is not supported")

        converted = 0
        deleted = 0
        if source_type == MetricType.scale and target_type == MetricType.scale:
            converted, deleted = await self._scale_to_scale(conv, metric_id, data)
        elif source_type == MetricType.bool and target_type == MetricType.enum:
            converted, deleted = await self._bool_to_enum(conv, metric_id, data)
        elif source_type == MetricType.enum and target_type == MetricType.scale:
            converted, deleted = await self._enum_to_scale(conv, metric_id, data)

        return MetricConvertResponse(converted=converted, deleted=deleted)

    async def _scale_to_scale(
        self, conv: MetricConversionRepository, metric_id: int, data: MetricConvertRequest,
    ) -> tuple[int, int]:
        _validate_scale_params(data.scale_min, data.scale_max, data.scale_step)
        valid_new_values = _build_valid_values(data.scale_min, data.scale_max, data.scale_step)

        actual_values = await conv.get_distinct_scale_values(metric_id)
        actual_set = {str(r["value"]) for r in actual_values}
        _check_mapping_complete(actual_set, data.value_mapping)
        _validate_mapping_values(data.value_mapping, valid_new_values, data.scale_min, data.scale_max, data.scale_step)

        values_to_delete = [int(k) for k, v in data.value_mapping.items() if v is None and k in actual_set]
        deleted = await conv.delete_entries_by_scale_values(metric_id, values_to_delete) if values_to_delete else 0
        mapping = {int(k): int(v) for k, v in data.value_mapping.items() if v is not None}
        converted = await conv.remap_scale_values(metric_id, mapping, data.scale_min, data.scale_max, data.scale_step) if mapping else 0
        await conv.update_scale_config_values(metric_id, data.scale_min, data.scale_max, data.scale_step)
        return converted, deleted

    async def _bool_to_enum(
        self, conv: MetricConversionRepository, metric_id: int, data: MetricConvertRequest,
    ) -> tuple[int, int]:
        if not data.enum_options or len(data.enum_options) < 2:
            raise InvalidOperationError("At least 2 enum_options are required for bool→enum conversion")
        if len(set(data.enum_options)) != len(data.enum_options):
            raise InvalidOperationError("Enum option labels must be unique")
        for k in data.value_mapping:
            if k not in {"true", "false"}:
                raise InvalidOperationError(f"Invalid bool value in mapping: {k}")

        await self.cfg_repo.insert_enum_config(metric_id, data.multi_select)
        option_label_to_id: dict[str, int] = {}
        for i, label in enumerate(data.enum_options):
            opt_id = await self.cfg_repo.insert_enum_option(metric_id, i, label)
            option_label_to_id[label] = opt_id

        bool_to_option: dict[str, int | None] = {}
        for bool_str, target_label in data.value_mapping.items():
            if target_label is None:
                bool_to_option[bool_str] = None
            else:
                if target_label not in option_label_to_id:
                    raise InvalidOperationError(f"Mapping target '{target_label}' is not in enum_options")
                bool_to_option[bool_str] = option_label_to_id[target_label]

        actual_values = await conv.get_distinct_bool_values(metric_id)
        for r in actual_values:
            key = str(r["value"]).lower()
            if key not in data.value_mapping:
                raise InvalidOperationError(f"Mapping is incomplete — missing value: {key}")

        deleted = 0
        for bool_str, opt_id in bool_to_option.items():
            if opt_id is None:
                deleted += await conv.delete_entries_by_bool_value(metric_id, bool_str == "true")
        converted = 0
        for bool_str, opt_id in bool_to_option.items():
            if opt_id is not None:
                converted += await conv.convert_bool_to_enum_values(metric_id, opt_id, bool_str == "true")

        await conv.delete_all_bool_values(metric_id)
        await self.cfg_repo.update_metric_type(metric_id, MetricType.enum.value)
        return converted, deleted

    async def _enum_to_scale(
        self, conv: MetricConversionRepository, metric_id: int, data: MetricConvertRequest,
    ) -> tuple[int, int]:
        _validate_scale_params(data.scale_min, data.scale_max, data.scale_step)
        if await conv.get_enum_multi_select(metric_id):
            raise InvalidOperationError("Cannot convert multi-select enum to scale")

        valid_new_values = _build_valid_values(data.scale_min, data.scale_max, data.scale_step)
        actual_options = await conv.get_distinct_enum_option_ids(metric_id)
        actual_set = {str(r["option_id"]) for r in actual_options}
        _check_mapping_complete(actual_set, data.value_mapping)
        _validate_mapping_values(data.value_mapping, valid_new_values, data.scale_min, data.scale_max, data.scale_step)

        deleted = 0
        for old_str, new_str in data.value_mapping.items():
            if new_str is None:
                deleted += await conv.delete_entries_by_enum_option(metric_id, int(old_str))
        converted = 0
        for old_str, new_str in data.value_mapping.items():
            if new_str is not None:
                converted += await conv.convert_enum_to_scale_values(
                    metric_id, int(old_str), int(new_str), data.scale_min, data.scale_max, data.scale_step,
                )

        await conv.delete_all_enum_values(metric_id)
        await conv.delete_enum_options(metric_id)
        await conv.delete_enum_config(metric_id)
        await conv.insert_scale_config_with_labels(metric_id, data.scale_min, data.scale_max, data.scale_step, data.scale_labels)
        await self.cfg_repo.update_metric_type(metric_id, MetricType.scale.value)
        return converted, deleted


def _validate_scale_params(s_min, s_max, s_step) -> None:
    if s_min is None or s_max is None or s_step is None:
        raise InvalidOperationError("scale_min, scale_max, scale_step are required")
    if s_min >= s_max:
        raise InvalidOperationError("scale_min must be less than scale_max")
    if s_step < 1 or s_step > (s_max - s_min):
        raise InvalidOperationError("scale_step must be >= 1 and <= (max - min)")


def _build_valid_values(s_min: int, s_max: int, s_step: int) -> set[int]:
    result: set[int] = set()
    v = s_min
    while v <= s_max:
        result.add(v)
        v += s_step
    return result


def _check_mapping_complete(actual_set: set[str], mapping: dict) -> None:
    missing = actual_set - set(mapping.keys())
    if missing:
        raise InvalidOperationError(f"Mapping is incomplete — missing values: {', '.join(sorted(missing))}")


def _validate_mapping_values(mapping: dict, valid: set[int], s_min: int, s_max: int, s_step: int) -> None:
    for old_str, new_str in mapping.items():
        if new_str is not None:
            try:
                new_val = int(new_str)
            except ValueError:
                raise InvalidOperationError(f"Invalid new value: {new_str}")
            if new_val not in valid:
                raise InvalidOperationError(
                    f"New value {new_val} is not in valid range [{s_min}..{s_max}] step {s_step}",
                )
