"""API integration tests for the daily router (GET /api/daily/{date})."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_slot

DATE = "2026-01-10"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_daily(client: AsyncClient, token: str, date: str = DATE) -> dict:
    resp = await client.get(
        f"/api/daily/{date}", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _find_metric(daily: dict, metric_id: int) -> dict | None:
    for m in daily["metrics"]:
        if m["metric_id"] == metric_id:
            return m
    return None


async def _create_enum_metric(
    client: AsyncClient, token: str, *, name: str = "Mood",
    options: list[str] | None = None,
) -> dict:
    opts = options or ["Good", "Bad", "Meh"]
    resp = await client.post(
        "/api/metrics",
        json={"name": name, "type": "enum", "enum_options": opts},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_text_metric(
    client: AsyncClient, token: str, *, name: str = "Journal",
) -> dict:
    resp = await client.post(
        "/api/metrics",
        json={"name": name, "type": "text"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_note(
    client: AsyncClient, token: str, metric_id: int, date: str, text: str,
) -> dict:
    resp = await client.post(
        "/api/notes",
        json={"metric_id": metric_id, "date": date, "text": text},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_computed_metric(
    client: AsyncClient, token: str, *,
    name: str, formula: list[dict], result_type: str = "float",
) -> dict:
    resp = await client.post(
        "/api/metrics",
        json={
            "name": name,
            "type": "computed",
            "formula": formula,
            "result_type": result_type,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_metric_with_condition(
    client: AsyncClient, token: str, *,
    name: str, metric_type: str,
    condition_metric_id: int, condition_type: str,
    condition_value: bool | int | list[int] | None = None,
) -> dict:
    payload: dict = {
        "name": name,
        "type": metric_type,
        "condition_metric_id": condition_metric_id,
        "condition_type": condition_type,
    }
    if condition_value is not None:
        payload["condition_value"] = condition_value
    resp = await client.post(
        "/api/metrics", json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_privacy_mode(
    client: AsyncClient, token: str, enabled: bool,
) -> None:
    resp = await client.put(
        "/api/auth/privacy-mode",
        json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


async def _disable_metric(
    client: AsyncClient, token: str, metric_id: int,
) -> None:
    resp = await client.patch(
        f"/api/metrics/{metric_id}",
        json={"enabled": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 1. Empty day
# ---------------------------------------------------------------------------

class TestEmptyDay:

    async def test_no_metrics_empty_list(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """No metrics created -- empty list, progress 0/0."""
        daily = await _get_daily(client, user_a["token"])

        assert daily["date"] == DATE
        assert daily["metrics"] == []
        assert daily["progress"]["filled"] == 0
        assert daily["progress"]["total"] == 0
        assert daily["progress"]["percent"] == 0


# ---------------------------------------------------------------------------
# 2-3. Bool metric
# ---------------------------------------------------------------------------

class TestBoolMetric:

    async def test_without_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric without entry -- entry is null."""
        metric = await create_metric(
            client, user_a["token"], name="Bool1", metric_type="bool",
        )
        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["type"] == "bool"
        assert item["entry"] is None

    async def test_with_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric with entry -- value=True, display_value='Да'."""
        metric = await create_metric(
            client, user_a["token"], name="Bool2", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, True)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"] is not None
        assert item["entry"]["value"] is True
        assert item["entry"]["display_value"] == "Да"


# ---------------------------------------------------------------------------
# 4. Number metric
# ---------------------------------------------------------------------------

class TestNumberMetric:

    async def test_with_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Steps", metric_type="number",
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, 42)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"]["value"] == 42
        assert item["entry"]["display_value"] == "42"


# ---------------------------------------------------------------------------
# 5. Scale metric
# ---------------------------------------------------------------------------

class TestScaleMetric:

    async def test_with_entry_scale_context(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Energy", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, 7)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"]["value"] == 7
        # Scale context from stored entry overrides current config
        assert item["scale_min"] == 1
        assert item["scale_max"] == 10
        assert item["scale_step"] == 1


# ---------------------------------------------------------------------------
# 6. Duration metric
# ---------------------------------------------------------------------------

class TestDurationMetric:

    async def test_with_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Sleep", metric_type="duration",
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, 90)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"]["value"] == 90
        assert item["entry"]["display_value"] == "1ч 30м"


# ---------------------------------------------------------------------------
# 7. Time metric
# ---------------------------------------------------------------------------

class TestTimeMetric:

    async def test_with_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="WakeUp", metric_type="time",
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, "07:30")

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"]["value"] == "07:30"
        assert item["entry"]["display_value"] == "07:30"


# ---------------------------------------------------------------------------
# 8. Enum metric
# ---------------------------------------------------------------------------

class TestEnumMetric:

    async def test_with_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await _create_enum_metric(client, user_a["token"])
        options = metric["enum_options"]
        option_id = options[0]["id"]

        await create_entry(
            client, user_a["token"], metric["id"], DATE, [option_id],
        )

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["enum_options"] is not None
        assert len(item["enum_options"]) == 3
        assert item["entry"] is not None
        assert isinstance(item["entry"]["value"], list)
        assert option_id in item["entry"]["value"]
        # display_value should be the label of the selected option
        assert item["entry"]["display_value"] == options[0]["label"]


# ---------------------------------------------------------------------------
# 9. Text metric (notes)
# ---------------------------------------------------------------------------

class TestTextMetric:

    async def test_with_note(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await _create_text_metric(client, user_a["token"])
        await _create_note(
            client, user_a["token"], metric["id"], DATE, "Hello world",
        )

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["type"] == "text"
        assert item["notes"] is not None
        assert len(item["notes"]) == 1
        assert item["notes"][0]["text"] == "Hello world"
        assert item["note_count"] == 1


# ---------------------------------------------------------------------------
# 10-11. Multi-slot metric
# ---------------------------------------------------------------------------

class TestMultiSlot:

    async def test_slots_with_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_am = await create_slot(client, user_a["token"], "AM")
        slot_pm = await create_slot(client, user_a["token"], "PM")
        metric = await create_metric(
            client, user_a["token"], name="SlotBool", metric_type="bool",
            slot_configs=[{"slot_id": slot_am["id"]}, {"slot_id": slot_pm["id"]}],
        )
        slots = metric["slots"]
        assert len(slots) == 2

        # Create entries for each slot
        await create_entry(
            client, user_a["token"], metric["id"], DATE, True,
            slot_id=slots[0]["id"],
        )
        await create_entry(
            client, user_a["token"], metric["id"], DATE, False,
            slot_id=slots[1]["id"],
        )

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["slots"] is not None
        assert len(item["slots"]) == 2

        slot_am = next(s for s in item["slots"] if s["label"] == "AM")
        slot_pm = next(s for s in item["slots"] if s["label"] == "PM")

        assert slot_am["entry"] is not None
        assert slot_am["entry"]["value"] is True

        assert slot_pm["entry"] is not None
        assert slot_pm["entry"]["value"] is False

    async def test_slots_structure(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Multi-slot metric returns slots array, main entry is null."""
        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        metric = await create_metric(
            client, user_a["token"], name="SlotNum", metric_type="number",
            slot_configs=[{"slot_id": slot_m["id"]}, {"slot_id": slot_e["id"]}],
        )
        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["entry"] is None
        assert item["slots"] is not None
        assert len(item["slots"]) == 2
        # Both slots have no entries yet
        for s in item["slots"]:
            assert s["entry"] is None
            assert "label" in s
            assert "slot_id" in s


# ---------------------------------------------------------------------------
# 12. Computed metric
# ---------------------------------------------------------------------------

class TestComputedMetric:

    async def test_formula_evaluation(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metric B = A + 1; A has value 10 -> B should be 11."""
        metric_a = await create_metric(
            client, user_a["token"], name="NumA", metric_type="number",
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, 10)

        formula = [
            {"type": "metric", "id": metric_a["id"]},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        metric_b = await _create_computed_metric(
            client, user_a["token"],
            name="Computed B", formula=formula, result_type="float",
        )

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric_b["id"])

        assert item is not None
        assert item["type"] == "computed"
        assert item["entry"] is not None
        assert item["entry"]["id"] is None  # computed entries have no DB id
        assert item["entry"]["value"] == 11.0


# ---------------------------------------------------------------------------
# 13-16. Conditions
# ---------------------------------------------------------------------------

class TestConditions:

    async def test_condition_filled_not_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """B depends on A (type='filled'), A not filled -> condition_met=False."""
        metric_a = await create_metric(
            client, user_a["token"], name="CondA", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="CondB", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="filled",
        )

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition"] is not None
        assert item_b["condition"]["type"] == "filled"
        assert item_b["condition_met"] is False

    async def test_condition_filled_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """B depends on A (type='filled'), A filled -> condition_met=True."""
        metric_a = await create_metric(
            client, user_a["token"], name="CondA2", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="CondB2", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="filled",
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, True)

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is True

    async def test_no_condition_always_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Metric without condition -> condition_met=True always."""
        metric = await create_metric(
            client, user_a["token"], name="NoCond", metric_type="bool",
        )
        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["condition"] is None
        assert item["condition_met"] is True


# ---------------------------------------------------------------------------
# 17. Privacy masking
# ---------------------------------------------------------------------------

class TestPrivacyMasking:

    async def test_private_metric_masked(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Private metric with privacy mode ON -> name='***', icon='lock', entry=null."""
        resp = await client.post(
            "/api/metrics",
            json={"name": "Secret", "type": "bool", "icon": "star", "private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()

        await create_entry(client, user_a["token"], metric["id"], DATE, True)
        await _set_privacy_mode(client, user_a["token"], True)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is not None
        assert item["name"] == "***"
        assert item["icon"] == "\U0001f512"  # lock emoji
        assert item["entry"] is None
        assert item["private"] is True


# ---------------------------------------------------------------------------
# 18. Disabled metric
# ---------------------------------------------------------------------------

class TestDisabledMetric:

    async def test_disabled_excluded(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Disabled metric is excluded from daily response."""
        metric = await create_metric(
            client, user_a["token"], name="ToDisable", metric_type="bool",
        )
        await _disable_metric(client, user_a["token"], metric["id"])

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])

        assert item is None


# ---------------------------------------------------------------------------
# 19-20. Progress
# ---------------------------------------------------------------------------

class TestProgress:

    async def test_progress_partial(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """1 filled of 3 total -> percent ~33."""
        m1 = await create_metric(
            client, user_a["token"], name="P1", metric_type="bool",
        )
        await create_metric(
            client, user_a["token"], name="P2", metric_type="number",
        )
        await create_metric(
            client, user_a["token"], name="P3", metric_type="duration",
        )
        await create_entry(client, user_a["token"], m1["id"], DATE, True)

        daily = await _get_daily(client, user_a["token"])

        assert daily["progress"]["filled"] == 1
        assert daily["progress"]["total"] == 3
        assert daily["progress"]["percent"] == 33

    async def test_computed_excluded_from_progress(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metrics do not count in progress."""
        metric_a = await create_metric(
            client, user_a["token"], name="BaseNum", metric_type="number",
        )
        formula = [
            {"type": "metric", "id": metric_a["id"]},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        await _create_computed_metric(
            client, user_a["token"],
            name="CompExcl", formula=formula, result_type="float",
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, 5)

        daily = await _get_daily(client, user_a["token"])

        # Only the number metric counts, not the computed one
        assert daily["progress"]["total"] == 1
        assert daily["progress"]["filled"] == 1
        assert daily["progress"]["percent"] == 100


# ---------------------------------------------------------------------------
# 21. Auto metrics (calendar)
# ---------------------------------------------------------------------------

class TestAutoMetrics:

    async def test_calendar_auto_metrics_present(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Calendar auto metrics always present: day_of_week, month, week_number."""
        daily = await _get_daily(client, user_a["token"])

        auto_types = {am["auto_type"] for am in daily["auto_metrics"]}
        assert "day_of_week" in auto_types
        assert "month" in auto_types
        assert "week_number" in auto_types

        # Verify values for 2026-01-10 (Saturday)
        dow = next(am for am in daily["auto_metrics"] if am["auto_type"] == "day_of_week")
        month = next(am for am in daily["auto_metrics"] if am["auto_type"] == "month")
        week = next(am for am in daily["auto_metrics"] if am["auto_type"] == "week_number")

        assert dow["value"] == 6  # Saturday = isoweekday 6
        assert dow["source_metric_id"] is None
        assert month["value"] == 1  # January
        assert week["value"] == 2  # ISO week 2


# ---------------------------------------------------------------------------
# 22. Condition equals (bool)
# ---------------------------------------------------------------------------

class TestConditionEquals:

    async def test_equals_true_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A=True, B has condition equals=true on A -> condition_met=True."""
        metric_a = await create_metric(
            client, user_a["token"], name="EqDepA", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="EqDepB", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="equals",
            condition_value=True,
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, True)

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition"]["type"] == "equals"
        assert item_b["condition_met"] is True

    async def test_equals_false_not_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A=False, B has condition equals=true on A -> condition_met=False."""
        metric_a = await create_metric(
            client, user_a["token"], name="EqDepA2", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="EqDepB2", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="equals",
            condition_value=True,
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, False)

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is False


# ---------------------------------------------------------------------------
# 23. Condition not_equals (bool)
# ---------------------------------------------------------------------------

class TestConditionNotEquals:

    async def test_not_equals_true_not_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A=True, B has condition not_equals=true -> condition_met=False."""
        metric_a = await create_metric(
            client, user_a["token"], name="NeqDepA", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="NeqDepB", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="not_equals",
            condition_value=True,
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, True)

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition"]["type"] == "not_equals"
        assert item_b["condition_met"] is False

    async def test_not_equals_false_met(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A=False, B has condition not_equals=true -> condition_met=True."""
        metric_a = await create_metric(
            client, user_a["token"], name="NeqDepA2", metric_type="bool",
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="NeqDepB2", metric_type="number",
            condition_metric_id=metric_a["id"],
            condition_type="not_equals",
            condition_value=True,
        )
        await create_entry(client, user_a["token"], metric_a["id"], DATE, False)

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is True


# ---------------------------------------------------------------------------
# 24. Condition equals (enum)
# ---------------------------------------------------------------------------

class TestConditionEqualsEnum:

    async def test_enum_equals_matching_option(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum dep with Good selected, condition equals=[good_id] -> met."""
        dep = await _create_enum_metric(
            client, user_a["token"], name="EnumDep",
            options=["Good", "Bad", "Meh"],
        )
        good_id = dep["enum_options"][0]["id"]

        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="EnumCondB", metric_type="number",
            condition_metric_id=dep["id"],
            condition_type="equals",
            condition_value=[good_id],
        )
        await create_entry(
            client, user_a["token"], dep["id"], DATE, [good_id],
        )

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is True

    async def test_enum_equals_non_matching_option(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum dep with Bad selected, condition equals=[good_id] -> not met."""
        dep = await _create_enum_metric(
            client, user_a["token"], name="EnumDep2",
            options=["Good", "Bad", "Meh"],
        )
        good_id = dep["enum_options"][0]["id"]
        bad_id = dep["enum_options"][1]["id"]

        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="EnumCondB2", metric_type="number",
            condition_metric_id=dep["id"],
            condition_type="equals",
            condition_value=[good_id],
        )
        await create_entry(
            client, user_a["token"], dep["id"], DATE, [bad_id],
        )

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is False


# ---------------------------------------------------------------------------
# 25. Slot category split
# ---------------------------------------------------------------------------

class TestSlotCategorySplit:

    async def test_split_by_slot_category(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Metric with slots in different categories splits into 2 items."""
        # Create two categories
        resp1 = await client.post(
            "/api/categories",
            json={"name": "Cat1"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp1.status_code == 201, resp1.text
        cat1_id = resp1.json()["id"]

        resp2 = await client.post(
            "/api/categories",
            json={"name": "Cat2"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp2.status_code == 201, resp2.text
        cat2_id = resp2.json()["id"]

        # Create global slots, then metric with slot_configs
        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "SplitSlots",
                "type": "bool",
                "slot_configs": [
                    {"slot_id": slot_m["id"], "category_id": cat1_id},
                    {"slot_id": slot_e["id"], "category_id": cat2_id},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201, resp.text
        metric = resp.json()

        daily = await _get_daily(client, user_a["token"])

        # Find all items for this metric_id
        items = [
            m for m in daily["metrics"]
            if m["metric_id"] == metric["id"]
        ]

        assert len(items) == 2

        cat_ids = {item["category_id"] for item in items}
        assert cat_ids == {cat1_id, cat2_id}

        for item in items:
            assert item["is_slot_split"] is True
            assert len(item["slots"]) == 1


# ---------------------------------------------------------------------------
# 26. Slot dep value extraction (filled condition on multi-slot metric)
# ---------------------------------------------------------------------------

class TestSlotDepValueExtraction:

    async def test_filled_condition_with_slotted_dep(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Multi-slot dep with one slot filled -> condition 'filled' is met."""
        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        dep = await create_metric(
            client, user_a["token"], name="SlotDep", metric_type="bool",
            slot_configs=[{"slot_id": slot_m["id"]}, {"slot_id": slot_e["id"]}],
        )
        slots = dep["slots"]
        assert len(slots) == 2

        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="DepOnSlot", metric_type="number",
            condition_metric_id=dep["id"],
            condition_type="filled",
        )

        # Fill only one slot of the dependency
        await create_entry(
            client, user_a["token"], dep["id"], DATE, True,
            slot_id=slots[0]["id"],
        )

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is True

    async def test_filled_condition_with_slotted_dep_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Multi-slot dep with no slots filled -> condition 'filled' not met."""
        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        dep = await create_metric(
            client, user_a["token"], name="SlotDep2", metric_type="bool",
            slot_configs=[{"slot_id": slot_m["id"]}, {"slot_id": slot_e["id"]}],
        )
        metric_b = await _create_metric_with_condition(
            client, user_a["token"],
            name="DepOnSlot2", metric_type="number",
            condition_metric_id=dep["id"],
            condition_type="filled",
        )

        daily = await _get_daily(client, user_a["token"])
        item_b = await _find_metric(daily, metric_b["id"])

        assert item_b is not None
        assert item_b["condition_met"] is False


# ---------------------------------------------------------------------------
# Scale Labels in Daily
# ---------------------------------------------------------------------------


class TestDailyScaleLabels:
    """GET /api/daily — scale_labels field and display_value with labels."""

    async def test_scale_labels_returned_in_daily(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Labeled Scale",
                "type": "scale",
                "scale_min": 0,
                "scale_max": 2,
                "scale_step": 1,
                "scale_labels": {"0": "нет", "1": "мало", "2": "достаточно"},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])
        assert item is not None
        assert item["scale_labels"] == {"0": "нет", "1": "мало", "2": "достаточно"}

    async def test_scale_display_value_uses_label(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Display Label",
                "type": "scale",
                "scale_min": 0,
                "scale_max": 2,
                "scale_step": 1,
                "scale_labels": {"0": "нет", "1": "мало", "2": "достаточно"},
            },
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()

        await create_entry(client, user_a["token"], metric["id"], DATE, 0)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])
        assert item["entry"] is not None
        assert item["entry"]["display_value"] == "нет"

    async def test_scale_display_value_without_labels(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"],
            name="No Labels", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], DATE, 3)

        daily = await _get_daily(client, user_a["token"])
        item = await _find_metric(daily, metric["id"])
        assert item["entry"]["display_value"] == "3"
        assert item["scale_labels"] is None
