#!/usr/bin/env python3
"""Создание тестового пользователя с метриками всех типов и данными за 15 дней."""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


USERNAME = "testtest"
PASSWORD = "testtest"
SEED_DAYS = 15

STEPS_MIN = 3000
STEPS_MAX = 15000
SCALE_MOOD_MIN = 1
SCALE_MOOD_MAX = 5
SLEEP_MIN_MINUTES = 300
SLEEP_MAX_MINUTES = 540
WAKEUP_HOUR_MIN = 6
WAKEUP_HOUR_MAX = 9
ENERGY_SCALE_MIN = 1
ENERGY_SCALE_MAX = 10

DIARY_PHRASES: list[str] = [
    "Продуктивный день, много успел сделать.",
    "Чувствую усталость, нужно больше отдыхать.",
    "Отличная погода, гулял после работы.",
    "Сложный день на работе, но справился.",
    "Читал книгу вечером, очень увлекательно.",
    "Занимался спортом, чувствую прилив сил.",
    "Провёл время с друзьями, отличное настроение.",
    "Немного болит голова, лёг пораньше.",
    "Готовил новое блюдо, получилось вкусно.",
    "Работал из дома, было тихо и спокойно.",
    "Ходил на прогулку в парк, красивый закат.",
    "Много встреч сегодня, устал от общения.",
    "Начал новый проект, очень мотивирован.",
    "Ленивый день, смотрел фильмы.",
    "Медитировал утром, день прошёл спокойно.",
]


@dataclass
class MetricSpec:
    name: str
    icon: str
    type: str
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    enum_options: list[str] | None = None
    multi_select: bool | None = None
    checkpoint_labels: list[str] | None = None
    formula: list[dict[str, Any]] | None = None
    result_type: str | None = None


METRICS: list[MetricSpec] = [
    MetricSpec(name="Тренировка", icon="💪", type="bool"),
    MetricSpec(name="Шаги", icon="👣", type="number"),
    MetricSpec(
        name="Настроение", icon="😊", type="scale",
        scale_min=SCALE_MOOD_MIN, scale_max=SCALE_MOOD_MAX, scale_step=1,
    ),
    MetricSpec(name="Сон", icon="😴", type="duration"),
    MetricSpec(name="Подъём", icon="⏰", type="time"),
    MetricSpec(
        name="Погода", icon="🌤", type="enum",
        enum_options=["Солнечно", "Облачно", "Дождь", "Снег"],
        multi_select=False,
    ),
    MetricSpec(
        name="Симптомы", icon="🤒", type="enum",
        enum_options=["Головная боль", "Усталость", "Насморк", "Кашель", "Боль в горле"],
        multi_select=True,
    ),
    MetricSpec(
        name="Энергия", icon="⚡", type="scale",
        scale_min=ENERGY_SCALE_MIN, scale_max=ENERGY_SCALE_MAX, scale_step=1,
        checkpoint_labels=["Утро", "День", "Вечер"],
    ),
    MetricSpec(name="Дневник", icon="📝", type="text"),
]

COMPUTED_SPEC = MetricSpec(
    name="Дефицит сна", icon="🧮", type="computed",
    result_type="int",
)


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}")


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None

    def set_token(self, token: str) -> None:
        self._token = token

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body)

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode() if body else None
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode()) from e


class ValueGenerator:
    @staticmethod
    def bool_value() -> bool:
        return random.random() < 0.6

    @staticmethod
    def number_value() -> int:
        return random.randint(STEPS_MIN, STEPS_MAX)

    @staticmethod
    def scale_value(low: int, high: int) -> int:
        return random.randint(low, high)

    @staticmethod
    def duration_value() -> int:
        return random.randint(SLEEP_MIN_MINUTES, SLEEP_MAX_MINUTES)

    @staticmethod
    def time_value() -> str:
        hour = random.randint(WAKEUP_HOUR_MIN, WAKEUP_HOUR_MAX)
        minute = random.choice([0, 15, 30, 45])
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def enum_single(option_ids: list[int]) -> list[int]:
        return [random.choice(option_ids)]

    @staticmethod
    def enum_multi(option_ids: list[int]) -> list[int]:
        count = random.randint(1, min(3, len(option_ids)))
        return random.sample(option_ids, count)

    @staticmethod
    def diary_text(day_index: int) -> str:
        return DIARY_PHRASES[day_index % len(DIARY_PHRASES)]


class Seeder:
    def __init__(self, api: ApiClient) -> None:
        self._api = api
        self._gen = ValueGenerator()
        self._metrics: dict[str, dict[str, Any]] = {}

    def run(self) -> None:
        self._check_environment()
        self._authenticate()
        self._create_metrics()
        self._load_existing_metrics()
        self._fill_entries()
        self._fill_notes()
        print("Готово!")

    def _check_environment(self) -> None:
        health = self._api.get("/api/health")
        env = health.get("env", "unknown")
        if env == "prod":
            print(f"Отказ: окружение = {env}. Скрипт нельзя запускать на prod.")
            sys.exit(1)
        print(f"Окружение: {env}")

    def _authenticate(self) -> None:
        body = {"username": USERNAME, "password": PASSWORD}
        try:
            resp = self._api.post("/api/auth/register", body)
            print(f"Пользователь {USERNAME} создан.")
        except ApiError as e:
            if e.status == 409:
                resp = self._api.post("/api/auth/login", body)
                self._api.set_token(resp["access_token"])
                print(f"Пользователь {USERNAME} уже существует, удаляю...")
                self._api.delete("/api/auth/account")
                resp = self._api.post("/api/auth/register", body)
                print(f"Пользователь {USERNAME} пересоздан.")
            else:
                raise
        self._api.set_token(resp["access_token"])

    def _create_metrics(self) -> None:
        for spec in METRICS:
            self._create_one_metric(spec)

    def _create_one_metric(self, spec: MetricSpec) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "name": spec.name,
            "icon": spec.icon,
            "type": spec.type,
        }
        if spec.scale_min is not None:
            body["scale_min"] = spec.scale_min
            body["scale_max"] = spec.scale_max
            body["scale_step"] = spec.scale_step
        if spec.enum_options is not None:
            body["enum_options"] = spec.enum_options
        if spec.multi_select is not None:
            body["multi_select"] = spec.multi_select
        if spec.checkpoint_labels is not None:
            body["checkpoint_labels"] = spec.checkpoint_labels
        if spec.formula is not None:
            body["formula"] = spec.formula
        if spec.result_type is not None:
            body["result_type"] = spec.result_type
        try:
            result = self._api.post("/api/metrics", body)
            print(f"  + {spec.type:10s} {spec.name}")
            return result
        except ApiError as e:
            if e.status == 409:
                print(f"  ~ {spec.type:10s} {spec.name} (уже есть)")
                return None
            raise

    def _create_computed_metric(self) -> None:
        sleep_metric = self._metrics.get("Сон")
        if not sleep_metric:
            print("  ! Метрика 'Сон' не найдена, computed не создана.")
            return
        spec = MetricSpec(
            name=COMPUTED_SPEC.name,
            icon=COMPUTED_SPEC.icon,
            type="computed",
            formula=[
                {"type": "metric", "id": sleep_metric["id"]},
                {"type": "op", "value": "-"},
                {"type": "number", "value": 480},
            ],
            result_type="int",
        )
        self._create_one_metric(spec)

    def _load_existing_metrics(self) -> None:
        metrics_list: list[dict[str, Any]] = self._api.get("/api/metrics")
        self._metrics = {m["name"]: m for m in metrics_list}
        print(f"Загружено {len(self._metrics)} метрик.")
        self._create_computed_metric()

    def _fill_entries(self) -> None:
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(SEED_DAYS - 1, -1, -1)]
        filled = 0
        skipped = 0

        for d in dates:
            date_str = d.isoformat()
            for name, metric in self._metrics.items():
                mt = metric["type"]
                mid = metric["id"]

                if mt == "text" or mt == "computed" or mt == "integration":
                    continue

                checkpoints = metric.get("checkpoints") or []
                if checkpoints:
                    for cp in checkpoints:
                        value = self._generate_value(metric)
                        ok = self._post_entry(mid, date_str, value, cp["id"])
                        if ok:
                            filled += 1
                        else:
                            skipped += 1
                else:
                    value = self._generate_value(metric)
                    if value is None:
                        continue
                    ok = self._post_entry(mid, date_str, value, None)
                    if ok:
                        filled += 1
                    else:
                        skipped += 1

        print(f"Entries: {filled} создано, {skipped} пропущено (уже есть).")

    def _generate_value(self, metric: dict[str, Any]) -> Any:
        mt = metric["type"]
        if mt == "bool":
            return self._gen.bool_value()
        if mt == "number":
            return self._gen.number_value()
        if mt == "scale":
            low = metric.get("scale_min") or 1
            high = metric.get("scale_max") or 5
            return self._gen.scale_value(low, high)
        if mt == "duration":
            return self._gen.duration_value()
        if mt == "time":
            return self._gen.time_value()
        if mt == "enum":
            options = metric.get("enum_options") or []
            option_ids = [o["id"] for o in options if o.get("enabled", True)]
            if not option_ids:
                return None
            if metric.get("multi_select"):
                return self._gen.enum_multi(option_ids)
            return self._gen.enum_single(option_ids)
        return None

    def _post_entry(self, metric_id: int, date_str: str, value: Any, checkpoint_id: int | None) -> bool:
        body: dict[str, Any] = {
            "metric_id": metric_id,
            "date": date_str,
            "value": value,
        }
        if checkpoint_id is not None:
            body["checkpoint_id"] = checkpoint_id
        try:
            self._api.post("/api/entries", body)
            return True
        except ApiError as e:
            if e.status == 409:
                return False
            raise

    def _fill_notes(self) -> None:
        diary = self._metrics.get("Дневник")
        if not diary:
            print("Метрика 'Дневник' не найдена, notes пропущены.")
            return

        today = date.today()
        dates = [today - timedelta(days=i) for i in range(SEED_DAYS - 1, -1, -1)]
        created = 0
        skipped = 0

        for i, d in enumerate(dates):
            date_str = d.isoformat()
            existing = self._api.get(
                f"/api/notes?metric_id={diary['id']}&start={date_str}&end={date_str}"
            )
            if existing:
                skipped += 1
                continue
            text = self._gen.diary_text(i)
            self._api.post("/api/notes", {
                "metric_id": diary["id"],
                "date": date_str,
                "text": text,
            })
            created += 1

        print(f"Notes: {created} создано, {skipped} пропущено (уже есть).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed test user with sample data")
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    api = ApiClient(args.base_url)
    seeder = Seeder(api)
    seeder.run()


if __name__ == "__main__":
    main()
