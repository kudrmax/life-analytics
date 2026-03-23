"""Service layer for insights — business logic between router and repository."""

from app.repositories.insights_repository import InsightsRepository
from app.schemas import InsightOut, InsightMetricOut, InsightCreate, InsightUpdate


def _build_insights(rows: list) -> list[InsightOut]:
    """Group flat JOIN rows into InsightOut objects."""
    insights: dict[int, InsightOut] = {}
    for r in rows:
        iid = r["id"]
        if iid not in insights:
            insights[iid] = InsightOut(
                id=iid,
                text=r["text"],
                metrics=[],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
        if r["im_id"] is not None:
            insights[iid].metrics.append(InsightMetricOut(
                id=r["im_id"],
                metric_id=r["metric_id"],
                metric_name=r["metric_name"],
                metric_icon=r["metric_icon"],
                custom_label=r["custom_label"],
                sort_order=r["im_sort_order"],
            ))
    return list(insights.values())


class InsightsService:
    def __init__(self, repo: InsightsRepository) -> None:
        self.repo = repo

    async def list_all(self) -> list[InsightOut]:
        rows = await self.repo.get_all_with_metrics()
        return _build_insights(rows)

    async def create(self, data: InsightCreate) -> InsightOut:
        text = data.text.strip()
        async with self.repo.conn.transaction():
            row = await self.repo.create(text)
            insight_id = row["id"]
            metrics_out: list[InsightMetricOut] = []
            for i, m in enumerate(data.metrics):
                im_id = await self.repo.insert_metric(insight_id, m.metric_id, m.custom_label, i)
                metric_name: str | None = None
                metric_icon: str | None = None
                if m.metric_id is not None:
                    md = await self.repo.get_metric_name_icon(m.metric_id)
                    if md:
                        metric_name = md["name"]
                        metric_icon = md["icon"]
                metrics_out.append(InsightMetricOut(
                    id=im_id,
                    metric_id=m.metric_id,
                    metric_name=metric_name,
                    metric_icon=metric_icon,
                    custom_label=m.custom_label,
                    sort_order=i,
                ))

        return InsightOut(
            id=row["id"],
            text=row["text"],
            metrics=metrics_out,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def update(self, insight_id: int, data: InsightUpdate) -> InsightOut:
        await self.repo.get_by_id(insight_id)
        async with self.repo.conn.transaction():
            if data.text is not None:
                await self.repo.update_text(insight_id, data.text.strip())
            if data.metrics is not None:
                await self.repo.delete_all_metrics(insight_id)
                for i, m in enumerate(data.metrics):
                    await self.repo.insert_metric(insight_id, m.metric_id, m.custom_label, i)
                await self.repo.touch_updated_at(insight_id)
        rows = await self.repo.get_one_with_metrics(insight_id)
        return _build_insights(rows)[0]

    async def delete(self, insight_id: int) -> None:
        await self.repo.get_by_id(insight_id)
        await self.repo.delete(insight_id)
