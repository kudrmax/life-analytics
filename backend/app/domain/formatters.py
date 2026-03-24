"""Domain formatters — human-readable display of metric values.

Pure functions without framework dependencies.
"""

from app.domain.enums import MetricType, ComputedResultType


def format_display_value(
    value: bool | str | int | list[int] | float | None,
    metric_type: str,
    result_type: str | None = None,
    enum_options: list[dict] | None = None,
    scale_labels: dict[str, str] | None = None,
) -> str:
    """Format a raw metric value into a human-readable display string."""
    if value is None:
        return "—"

    if metric_type == MetricType.enum:
        if not isinstance(value, list):
            return "—"
        if enum_options:
            id_to_label = {opt["id"]: opt["label"] for opt in enum_options}
            return ", ".join(id_to_label.get(oid, str(oid)) for oid in value)
        return ", ".join(str(v) for v in value)

    if metric_type == MetricType.computed:
        rt = result_type or ComputedResultType.FLOAT
        if rt == ComputedResultType.BOOL:
            return "Да" if value else "Нет"
        if rt in (ComputedResultType.TIME, ComputedResultType.DURATION):
            return str(value)
        if rt == ComputedResultType.INT:
            return str(round(value)) if isinstance(value, (int, float)) else str(value)
        # float
        return f"{value:.2f}" if isinstance(value, float) else str(value)

    if metric_type == MetricType.integration:
        return str(value)

    if metric_type == MetricType.duration:
        minutes = int(value)
        h, m = divmod(minutes, 60)
        if h > 0:
            return f"{h}ч {m}м"
        return f"{m}м"

    if metric_type == MetricType.time:
        return str(value) if value else "—"

    if metric_type in (MetricType.number, MetricType.scale):
        if metric_type == MetricType.scale and scale_labels and str(value) in scale_labels:
            return scale_labels[str(value)]
        return str(value) if value is not None else "—"

    # bool
    return "Да" if value else "Нет"
