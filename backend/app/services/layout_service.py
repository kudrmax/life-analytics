"""Service for daily layout — assembles order data and saves changes."""

from app.repositories.layout_repository import LayoutRepository


class LayoutService:
    def __init__(self, repo: LayoutRepository) -> None:
        self.repo = repo

    async def get_order_data(self) -> dict:
        """Build full order structure for the Order panel."""
        layout = await self.repo.get_layout()
        checkpoints = await self.repo.get_active_checkpoints()
        intervals = await self.repo.get_active_intervals()
        categories = await self.repo.get_categories()
        metrics = await self.repo.get_enabled_metrics()

        metric_ids = [m["id"] for m in metrics]
        mc_rows = await self.repo.get_metric_checkpoints(metric_ids)
        mi_rows = await self.repo.get_metric_intervals(metric_ids)

        # Build lookup structures
        metrics_by_id = {m["id"]: dict(m) for m in metrics}
        cp_by_id = {c["id"]: dict(c) for c in checkpoints}
        iv_by_id = {i["id"]: dict(i) for i in intervals}
        cat_by_id = {c["id"]: dict(c) for c in categories}

        # metrics per checkpoint: {checkpoint_id: [{metric_id, sort_order, category_id, ...}]}
        metrics_per_cp: dict[int, list[dict]] = {}
        for row in mc_rows:
            cp_id = row["checkpoint_id"]
            if cp_id not in metrics_per_cp:
                metrics_per_cp[cp_id] = []
            m = metrics_by_id.get(row["metric_id"])
            if m:
                metrics_per_cp[cp_id].append({
                    "metric_id": row["metric_id"],
                    "name": m["name"],
                    "icon": m.get("icon", ""),
                    "sort_order": row["sort_order"],
                    "category_id": row["category_id"],
                })

        # metrics per interval: {interval_id: [{metric_id, sort_order, category_id, ...}]}
        metrics_per_iv: dict[int, list[dict]] = {}
        for row in mi_rows:
            iv_id = row["interval_id"]
            if iv_id not in metrics_per_iv:
                metrics_per_iv[iv_id] = []
            m = metrics_by_id.get(row["metric_id"])
            if m:
                metrics_per_iv[iv_id].append({
                    "metric_id": row["metric_id"],
                    "name": m["name"],
                    "icon": m.get("icon", ""),
                    "sort_order": row["sort_order"],
                    "category_id": row["category_id"],
                })

        # Standalone metrics: not bound to any checkpoint or interval
        bound_metric_ids: set[int] = set()
        for row in mc_rows:
            bound_metric_ids.add(row["metric_id"])
        for row in mi_rows:
            bound_metric_ids.add(row["metric_id"])

        standalone = [m for m in metrics if m["id"] not in bound_metric_ids]
        # Group standalone by category
        standalone_by_cat: dict[int, list[dict]] = {}
        standalone_no_cat: list[dict] = []
        for m in standalone:
            item = {"metric_id": m["id"], "name": m["name"], "icon": m.get("icon", ""), "sort_order": m["sort_order"]}
            if m["category_id"] and m["category_id"] in cat_by_id:
                cat_id = m["category_id"]
                if cat_id not in standalone_by_cat:
                    standalone_by_cat[cat_id] = []
                standalone_by_cat[cat_id].append(item)
            else:
                standalone_no_cat.append(item)

        # Build response blocks in layout order
        blocks: list[dict] = []
        for entry in layout:
            bt = entry["block_type"]
            bid = entry["block_id"]

            if bt == "checkpoint" and bid in cp_by_id:
                cp = cp_by_id[bid]
                items = sorted(metrics_per_cp.get(bid, []), key=lambda x: x["sort_order"])
                blocks.append({
                    "type": "checkpoint", "id": bid,
                    "label": cp["label"], "description": cp.get("description"),
                    "items": items,
                })
            elif bt == "interval" and bid in iv_by_id:
                iv = iv_by_id[bid]
                items = sorted(metrics_per_iv.get(bid, []), key=lambda x: x["sort_order"])
                blocks.append({
                    "type": "interval", "id": bid,
                    "label": iv["label"],
                    "items": items,
                })
            elif bt == "category" and bid in cat_by_id:
                cat = cat_by_id[bid]
                items = sorted(standalone_by_cat.get(bid, []), key=lambda x: x["sort_order"])
                if items:
                    blocks.append({
                        "type": "category", "id": bid,
                        "label": cat["name"],
                        "items": items,
                    })
            elif bt == "metric" and bid in metrics_by_id:
                m = metrics_by_id[bid]
                if bid not in bound_metric_ids and m.get("category_id") is None:
                    blocks.append({
                        "type": "metric", "id": bid,
                        "label": m["name"], "icon": m.get("icon", ""),
                    })

        return {
            "blocks": blocks,
            "categories": [{"id": c["id"], "name": c["name"], "parent_id": c.get("parent_id")} for c in categories],
        }

    async def _ensure_layout(
        self,
        layout: list,
        checkpoints: list,
        intervals: list,
        standalone_by_cat: dict[int, list],
        standalone_no_cat: list,
    ) -> list:
        """Auto-generate or update layout if it's empty or missing entries."""
        existing = {(r["block_type"], r["block_id"]) for r in layout}

        # Determine what should exist
        expected: list[tuple[str, int]] = []
        for cp in checkpoints:
            expected.append(("checkpoint", cp["id"]))
        for iv in intervals:
            expected.append(("interval", iv["id"]))
        for cat_id in standalone_by_cat:
            expected.append(("category", cat_id))
        for m in standalone_no_cat:
            expected.append(("metric", m["metric_id"]))

        # Find missing entries
        missing = [e for e in expected if e not in existing]
        if not missing and existing:
            # Remove stale entries
            expected_set = set(expected)
            stale = [e for e in existing if e not in expected_set]
            if stale:
                layout_list = [r for r in layout if (r["block_type"], r["block_id"]) not in set(stale)]
                await self.repo.save_layout([
                    {"block_type": r["block_type"], "block_id": r["block_id"], "sort_order": i * 10}
                    for i, r in enumerate(layout_list)
                ])
                return await self.repo.get_layout()
            return layout

        # Add missing entries at the end
        max_order = max((r["sort_order"] for r in layout), default=-10)
        for i, (bt, bid) in enumerate(missing):
            max_order += 10
            await self.repo.conn.execute(
                "INSERT INTO daily_layout (user_id, block_type, block_id, sort_order) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, block_type, block_id) DO NOTHING",
                self.repo.user_id, bt, bid, max_order,
            )

        return await self.repo.get_layout()

    async def save_block_order(self, items: list[dict]) -> None:
        """Save top-level block ordering."""
        await self.repo.save_layout(items)

    async def save_inner_order(self, block_type: str, block_id: int, items: list[dict]) -> None:
        """Save metric ordering within a block."""
        if block_type == "checkpoint":
            await self.repo.save_inner_checkpoint(block_id, items)
        elif block_type == "interval":
            await self.repo.save_inner_interval(block_id, items)
        elif block_type in ("category", "metric"):
            await self.repo.save_inner_standalone(items)
