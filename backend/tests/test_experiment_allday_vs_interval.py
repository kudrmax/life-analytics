"""
Experiment: compare correlation results between
- Scenario A: metric with interval_binding=all_day
- Scenario B: same metric with interval_binding=by_interval bound to ONE interval,
              with checkpoints NEVER filled.

Both scenarios get IDENTICAL values on IDENTICAL dates.
We compare the resulting correlation pairs.
"""
from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.conftest import (
    auth_headers, register_user, create_metric, create_entry, create_checkpoint,
)


async def _start_report(client: AsyncClient, token: str) -> dict:
    resp = await client.post(
        "/api/analytics/correlation-report",
        json={"start": "2026-01-01", "end": "2026-02-28"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wait_done(client: AsyncClient, token: str) -> dict:
    for _ in range(300):
        resp = await client.get(
            "/api/analytics/correlation-report",
            headers=auth_headers(token),
        )
        data = resp.json()
        if data.get("report") and data["report"]["status"] == "done":
            return data
        await asyncio.sleep(0.1)
    raise AssertionError("report did not finish")


async def _get_intervals(client: AsyncClient, token: str) -> list[dict]:
    resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()


async def _get_pairs(client: AsyncClient, token: str, report_id: int) -> list[dict]:
    all_pairs: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs"
            f"?limit=200&offset={offset}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        all_pairs.extend(data["pairs"])
        if not data.get("has_more"):
            break
        offset += 200
    return all_pairs


def _filter_kofe_x_son(pairs: list[dict]) -> list[dict]:
    """Только пары между Кофе и Сон (любые их auto-source производные)."""
    out = []
    for p in pairs:
        la = p.get("label_a") or ""
        lb = p.get("label_b") or ""
        if "Кофе" in la + lb and "Сон" in la + lb:
            out.append(p)
    return out


def _normalize_pair(p: dict) -> dict:
    """Strip binding labels so we can compare cross-scenario."""
    label_a = (p.get("label_a") or "").replace(" (Утро → День)", "")
    label_b = (p.get("label_b") or "").replace(" (Утро → День)", "")
    return {
        "key": tuple(sorted([label_a, label_b])),
        "correlation": round(p.get("correlation") or 0, 6),
        "data_points": p.get("data_points"),
        "lag_days": p.get("lag_days"),
        "p_value": round(p.get("p_value") or 0, 6) if p.get("p_value") is not None else None,
        "quality_issue": p.get("quality_issue"),
    }


async def _setup_user(
    client: AsyncClient, username: str, *, with_interval: bool,
) -> tuple[str, int]:
    """
    Create a user with two metrics (kofe + son) and 30 daily entries.

    If with_interval=True: 'kofe' is bound to ONE interval (Утро→День),
    checkpoints are NEVER filled.
    """
    user = await register_user(client, username)
    token = user["token"]

    interval_id: int | None = None
    if with_interval:
        # We need two checkpoints to define an interval, but we will NOT
        # write any entries for those checkpoints.
        await create_checkpoint(client, token, "Утро")
        await create_checkpoint(client, token, "День")
        intervals = await _get_intervals(client, token)
        assert len(intervals) >= 1, intervals
        interval_id = intervals[0]["id"]

    # Companion metric — always all_day, same in both scenarios.
    son = await create_metric(
        client, token, name="Сон", metric_type="number", slug="son",
    )

    # Subject metric — kofe.
    if with_interval:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Кофе", "type": "number", "slug": "kofe",
                "interval_binding": "by_interval",
                "interval_ids": [interval_id],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        kofe = resp.json()
    else:
        kofe = await create_metric(
            client, token, name="Кофе", metric_type="number", slug="kofe",
        )

    # Identical 30 daily entries for both metrics.
    for day in range(1, 31):
        date_str = f"2026-01-{day:02d}"
        # Some non-trivial pattern for correlation to compute.
        kofe_val = (day % 5) + 1            # 2,3,4,5,1,2,3,4,5,1,...
        son_val = 8 - ((day % 5))           # 8,7,6,5,4,8,7,6,5,4,...

        await create_entry(client, token, son["id"], date_str, son_val)

        if with_interval:
            await create_entry(
                client, token, kofe["id"], date_str, kofe_val,
                interval_id=interval_id,
            )
        else:
            await create_entry(
                client, token, kofe["id"], date_str, kofe_val,
            )

    return token, kofe["id"]


class TestAllDayVsIntervalEquivalence:
    async def test_compare_correlation_outputs(self, client: AsyncClient) -> None:
        # Scenario A — all_day
        token_a, _ = await _setup_user(client, "user_alpha", with_interval=False)
        # Scenario B — by_interval with empty checkpoints
        token_b, _ = await _setup_user(client, "user_beta", with_interval=True)

        report_a = await _start_report(client, token_a)
        report_b = await _start_report(client, token_b)
        await _wait_done(client, token_a)
        await _wait_done(client, token_b)

        pairs_a = await _get_pairs(client, token_a, report_a["report_id"])
        pairs_b = await _get_pairs(client, token_b, report_b["report_id"])

        # ---- ЧЕЛОВЕЧЕСКИЙ ОТЧЁТ: пары Кофе × Сон ----
        kofe_son_a = _filter_kofe_x_son(pairs_a)
        kofe_son_b = _filter_kofe_x_son(pairs_b)

        def _dump(label: str, items: list[dict]) -> None:
            print(f"\n>>> {label} — всего строк: {len(items)}")
            for p in items:
                print(
                    f"  '{p.get('label_a')}'  ×  '{p.get('label_b')}'  "
                    f"lag={p.get('lag_days')}  r={p.get('correlation'):+.4f}  "
                    f"n={p.get('data_points')}  "
                    f"q={p.get('quality_issue') or '-'}"
                )

        _dump("СЦЕНАРИЙ A (all_day)  пары Кофе × Сон", kofe_son_a)
        _dump("СЦЕНАРИЙ B (by_interval, ЧП пусты)  пары Кофе × Сон", kofe_son_b)

        # Подсчитаем уникальные внутренние source_key для метрики Кофе.
        def _kofe_source_keys(pairs: list[dict]) -> set[str]:
            keys = set()
            for p in pairs:
                for side in ("a", "b"):
                    sk = p.get(f"source_key_{side}") or ""
                    lab = p.get(f"label_{side}") or ""
                    if "Кофе" in lab and not lab.startswith("auto:"):
                        keys.add(sk)
            return keys

        keys_kofe_a = _kofe_source_keys(pairs_a)
        keys_kofe_b = _kofe_source_keys(pairs_b)
        print(f"\n>>> Сколько разных внутренних 'версий' метрики Кофе:")
        print(f"  A: {len(keys_kofe_a)} штук — {sorted(keys_kofe_a)}")
        print(f"  B: {len(keys_kofe_b)} штук — {sorted(keys_kofe_b)}")

        norm_a = sorted(
            [_normalize_pair(p) for p in pairs_a],
            key=lambda x: (x["key"], x["lag_days"]),
        )
        norm_b = sorted(
            [_normalize_pair(p) for p in pairs_b],
            key=lambda x: (x["key"], x["lag_days"]),
        )

        # Print a side-by-side dump for inspection.
        print("\n========= SCENARIO A (all_day) — total pairs:", len(norm_a), "=========")
        for p in norm_a[:30]:
            print(f"  {p['key']}  lag={p['lag_days']}  r={p['correlation']:+.4f}  "
                  f"n={p['data_points']}  p={p['p_value']}  q={p['quality_issue']}")

        print("\n========= SCENARIO B (by_interval, empty checkpoints) — total pairs:", len(norm_b), "=========")
        for p in norm_b[:30]:
            print(f"  {p['key']}  lag={p['lag_days']}  r={p['correlation']:+.4f}  "
                  f"n={p['data_points']}  p={p['p_value']}  q={p['quality_issue']}")

        # Build sets for comparison.
        keys_a = {(p["key"], p["lag_days"]) for p in norm_a}
        keys_b = {(p["key"], p["lag_days"]) for p in norm_b}

        only_in_a = keys_a - keys_b
        only_in_b = keys_b - keys_a
        common = keys_a & keys_b

        print(f"\nKeys in A only: {len(only_in_a)}")
        for k in sorted(only_in_a)[:20]:
            print(f"  {k}")
        print(f"\nKeys in B only: {len(only_in_b)}")
        for k in sorted(only_in_b)[:20]:
            print(f"  {k}")
        print(f"\nCommon keys: {len(common)}")

        # Compare values for common keys.
        a_by_key = {(p["key"], p["lag_days"]): p for p in norm_a}
        b_by_key = {(p["key"], p["lag_days"]): p for p in norm_b}

        diffs = []
        for k in common:
            pa, pb = a_by_key[k], b_by_key[k]
            if (pa["correlation"] != pb["correlation"]
                or pa["data_points"] != pb["data_points"]
                or pa["p_value"] != pb["p_value"]
                or pa["quality_issue"] != pb["quality_issue"]):
                diffs.append((k, pa, pb))

        print(f"\nDiffering values among common keys: {len(diffs)}")
        for k, pa, pb in diffs[:20]:
            print(f"  {k}")
            print(f"    A: r={pa['correlation']}  n={pa['data_points']}  p={pa['p_value']}  q={pa['quality_issue']}")
            print(f"    B: r={pb['correlation']}  n={pb['data_points']}  p={pb['p_value']}  q={pb['quality_issue']}")

        # Sanity assertion: both produced something.
        assert len(norm_a) > 0
        assert len(norm_b) > 0
