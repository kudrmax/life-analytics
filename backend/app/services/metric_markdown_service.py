"""Markdown export formatting for metrics — extracted for 300-line rule."""

from app.domain.enums import MetricType
from app.schemas import MetricDefinitionOut

_TYPE_LABELS: dict[str, str] = {
    "bool": "Да/Нет", "number": "Число", "scale": "Шкала", "enum": "Варианты",
    "time": "Время", "duration": "Длительность", "computed": "Формула",
    "integration": "Интеграция", "text": "Заметка",
}

_RESULT_TYPE_LABELS: dict[str, str] = {
    "float": "число", "int": "целое", "bool": "да/нет", "time": "время", "duration": "длительность",
}


def build_markdown_table(metrics: list[MetricDefinitionOut], cat_rows: list) -> str:
    """Build a Markdown table string from metrics and category rows."""
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
        slots = _esc_md(", ".join(s.label for s in (m.slots or [])))
        details = _esc_md(_get_details(m, metric_name_by_id))
        status = "" if m.enabled else "❌ архив"
        lines.append(f"| {icon} | {name} | {desc} | {type_label} | {cat} | {slots} | {details} | {status} |")

    return "\n".join(lines)


def _esc_md(s: str) -> str:
    return s.replace("|", "\\|")


def _get_cat_path(category_id: int | None, cat_by_id: dict[int, dict]) -> str:
    if not category_id:
        return ""
    cat = cat_by_id.get(category_id)
    if not cat:
        return ""
    parent_name = cat.get("_parent_name")
    return f"{parent_name} / {cat['name']}" if parent_name else cat["name"]


def _get_details(m: MetricDefinitionOut, metric_name_by_id: dict[int, str]) -> str:
    if m.type == MetricType.scale:
        smin = m.scale_min if m.scale_min is not None else 1
        smax = m.scale_max if m.scale_max is not None else 10
        sstep = m.scale_step if m.scale_step is not None else 1
        return f"{smin}–{smax}, шаг {sstep}"
    if m.type == MetricType.enum:
        opts = ", ".join(o["label"] for o in (m.enum_options or []) if o.get("enabled") is not False)
        return opts + (" (мультивыбор)" if m.multi_select else "")
    if m.type == MetricType.computed and m.formula:
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
    if m.type == MetricType.integration:
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
