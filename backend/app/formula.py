"""
Formula engine for computed metrics.

Token format (JSONB):
  {"type": "metric", "id": 5, "slug": "steps"}
  {"type": "op",     "value": "+"|"-"|"*"|"/"|">"|"<"}
  {"type": "number", "value": 2.5}
  {"type": "lparen"}
  {"type": "rparen"}

Evaluation uses recursive descent with standard operator precedence:
  comparison = expr (('>' | '<') expr)?
  expr       = term (('+' | '-') term)*
  term       = factor (('*' | '/') factor)*
  factor     = '(' expr ')' | metric_ref | number
"""


class _MissingValue(Exception):
    pass


def get_referenced_metric_ids(tokens: list[dict]) -> list[int]:
    return [t["id"] for t in tokens if t.get("type") == "metric"]


def validate_formula(
    tokens: list[dict],
    source_metrics: dict[int, str],
) -> str | None:
    if not tokens:
        return "Формула пуста"

    # Check balanced parentheses
    depth = 0
    for t in tokens:
        if t.get("type") == "lparen":
            depth += 1
        elif t.get("type") == "rparen":
            depth -= 1
            if depth < 0:
                return "Лишняя закрывающая скобка"
    if depth != 0:
        return "Незакрытая скобка"

    # Check comparison operators: max 1, not inside parentheses
    comparison_count = sum(
        1 for t in tokens if t.get("type") == "op" and t.get("value") in (">", "<")
    )
    if comparison_count > 1:
        return "В формуле допустимо не более одного оператора сравнения"
    if comparison_count == 1:
        depth = 0
        for t in tokens:
            if t.get("type") == "lparen":
                depth += 1
            elif t.get("type") == "rparen":
                depth -= 1
            elif t.get("type") == "op" and t.get("value") in (">", "<") and depth > 0:
                return "Оператор сравнения нельзя использовать внутри скобок"

    # Check all metric references exist and are not computed
    has_time = False
    has_duration = False
    has_other_numeric = False
    for t in tokens:
        if t.get("type") == "metric":
            mid = t.get("id")
            if mid not in source_metrics:
                return f"Метрика с id={mid} не найдена"
            mt = source_metrics[mid]
            if mt == "computed":
                return "Нельзя ссылаться на другие вычисляемые метрики"
            if mt == "time":
                has_time = True
            elif mt == "duration":
                has_duration = True
            else:
                has_other_numeric = True

    # Check time compatibility: time + duration OK, time + number/scale/bool = error
    if has_time and has_other_numeric:
        return "Нельзя смешивать время с числовыми типами в одной формуле"

    # Check operators for time formulas
    if has_time:
        for t in tokens:
            if t.get("type") == "op" and t.get("value") in ("*", "/"):
                return "Для времени допустимы только +, −, > и <"
            if t.get("type") == "number":
                return "Нельзя использовать числовые константы в формуле с временем"

    # Check token sequence validity
    prev_type = None
    for t in tokens:
        tt = t.get("type")
        if tt == "op":
            if prev_type is None or prev_type in ("op", "lparen"):
                return "Оператор в неожиданной позиции"
        elif tt in ("metric", "number"):
            if prev_type in ("metric", "number", "rparen"):
                return "Два значения подряд без оператора"
        elif tt == "lparen":
            if prev_type in ("metric", "number", "rparen"):
                return "Скобка после значения без оператора"
        elif tt == "rparen":
            if prev_type in ("op", "lparen", None):
                return "Закрывающая скобка в неожиданной позиции"
        prev_type = tt

    # Last token should be value or rparen
    if prev_type in ("op", "lparen"):
        return "Формула не может заканчиваться оператором или открывающей скобкой"

    return None


def convert_metric_value(
    raw_value,
    metric_type: str,
    scale_min: int | None = None,
    scale_max: int | None = None,
) -> float | None:
    if raw_value is None:
        return None
    if metric_type == "bool":
        return 1.0 if raw_value else 0.0
    if metric_type == "number":
        return float(raw_value)
    if metric_type == "scale":
        v = float(raw_value)
        s_min = float(scale_min) if scale_min is not None else 1.0
        s_max = float(scale_max) if scale_max is not None else 5.0
        if s_max == s_min:
            return 0.0
        return (v - s_min) / (s_max - s_min)
    if metric_type == "duration":
        return float(raw_value)
    if metric_type == "time":
        # raw_value is "HH:MM" string
        if isinstance(raw_value, str) and ":" in raw_value:
            parts = raw_value.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        return None
    return None


def evaluate_formula(
    tokens: list[dict],
    values_by_id: dict[int, float | None],
    result_type: str,
) -> bool | int | float | str | None:
    if not tokens:
        return None
    try:
        val, pos = _parse_comparison(tokens, 0, values_by_id)
        return _format_result(val, result_type)
    except (ZeroDivisionError, _MissingValue):
        return None


def _format_result(value: float, result_type: str):
    if result_type == "bool":
        return value > 0
    if result_type == "int":
        return round(value)
    if result_type == "float":
        return round(value, 4)
    if result_type == "time":
        minutes = int(value) % 1440
        if minutes < 0:
            minutes += 1440
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if result_type == "duration":
        total = max(0, int(round(value)))
        h, m = divmod(total, 60)
        return f"{h}ч {m}м"
    return round(value, 4)


def _parse_comparison(tokens, pos, values):
    left, pos = _parse_expr(tokens, pos, values)
    if pos < len(tokens):
        t = tokens[pos]
        if t.get("type") == "op" and t.get("value") in (">", "<"):
            op = t["value"]
            pos += 1
            right, pos = _parse_expr(tokens, pos, values)
            left = 1.0 if (left > right if op == ">" else left < right) else 0.0
    return left, pos


def _parse_expr(tokens, pos, values):
    left, pos = _parse_term(tokens, pos, values)
    while pos < len(tokens):
        t = tokens[pos]
        if t.get("type") == "op" and t.get("value") in ("+", "-"):
            op = t["value"]
            pos += 1
            right, pos = _parse_term(tokens, pos, values)
            if op == "+":
                left = left + right
            else:
                left = left - right
        else:
            break
    return left, pos


def _parse_term(tokens, pos, values):
    left, pos = _parse_factor(tokens, pos, values)
    while pos < len(tokens):
        t = tokens[pos]
        if t.get("type") == "op" and t.get("value") in ("*", "/"):
            op = t["value"]
            pos += 1
            right, pos = _parse_factor(tokens, pos, values)
            if op == "*":
                left = left * right
            else:
                if right == 0:
                    raise ZeroDivisionError()
                left = left / right
        else:
            break
    return left, pos


def _parse_factor(tokens, pos, values):
    if pos >= len(tokens):
        raise _MissingValue()
    t = tokens[pos]
    tt = t.get("type")
    if tt == "lparen":
        pos += 1
        val, pos = _parse_expr(tokens, pos, values)
        if pos < len(tokens) and tokens[pos].get("type") == "rparen":
            pos += 1
        return val, pos
    if tt == "number":
        return float(t["value"]), pos + 1
    if tt == "metric":
        mid = t["id"]
        v = values.get(mid)
        if v is None:
            raise _MissingValue()
        return float(v), pos + 1
    raise _MissingValue()
