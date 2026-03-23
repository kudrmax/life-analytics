from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import InsightCreate, InsightUpdate, InsightOut, InsightMetricOut
from app.repositories.insights_repository import InsightsRepository

router = APIRouter(prefix="/api/insights", tags=["insights"])


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


@router.get("", response_model=list[InsightOut])
async def list_insights(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = InsightsRepository(db, current_user["id"])
    rows = await repo.get_all_with_metrics()
    return _build_insights(rows)


@router.post("", response_model=InsightOut, status_code=201)
async def create_insight(
    data: InsightCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = InsightsRepository(db, current_user["id"])
    text = data.text.strip()
    async with db.transaction():
        row = await repo.create(text)
        insight_id = row["id"]
        metrics_out: list[InsightMetricOut] = []
        for i, m in enumerate(data.metrics):
            im_id = await repo.insert_metric(insight_id, m.metric_id, m.custom_label, i)
            metric_name: str | None = None
            metric_icon: str | None = None
            if m.metric_id is not None:
                md = await repo.get_metric_name_icon(m.metric_id)
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


@router.put("/{insight_id}", response_model=InsightOut)
async def update_insight(
    insight_id: int,
    data: InsightUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = InsightsRepository(db, current_user["id"])
    await repo.get_by_id(insight_id)

    async with db.transaction():
        if data.text is not None:
            await repo.update_text(insight_id, data.text.strip())

        if data.metrics is not None:
            await repo.delete_all_metrics(insight_id)
            for i, m in enumerate(data.metrics):
                await repo.insert_metric(insight_id, m.metric_id, m.custom_label, i)
            await repo.touch_updated_at(insight_id)

    rows = await repo.get_one_with_metrics(insight_id)
    return _build_insights(rows)[0]


@router.delete("/{insight_id}", status_code=204)
async def delete_insight(
    insight_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = InsightsRepository(db, current_user["id"])
    await repo.get_by_id(insight_id)
    await repo.delete(insight_id)
