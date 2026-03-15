from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import InsightCreate, InsightUpdate, InsightOut, InsightMetricOut

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
    rows = await db.fetch(
        """SELECT i.id, i.text, i.created_at, i.updated_at,
                  im.id AS im_id, im.metric_id, im.custom_label,
                  im.sort_order AS im_sort_order,
                  md.name AS metric_name, md.icon AS metric_icon
           FROM insights i
           LEFT JOIN insight_metrics im ON im.insight_id = i.id
           LEFT JOIN metric_definitions md ON md.id = im.metric_id
           WHERE i.user_id = $1
           ORDER BY i.updated_at DESC, im.sort_order""",
        current_user["id"],
    )
    return _build_insights(rows)


@router.post("", response_model=InsightOut, status_code=201)
async def create_insight(
    data: InsightCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    text = data.text.strip()
    async with db.transaction():
        row = await db.fetchrow(
            """INSERT INTO insights (user_id, text)
               VALUES ($1, $2)
               RETURNING id, text, created_at, updated_at""",
            current_user["id"], text,
        )
        insight_id = row["id"]
        metrics_out: list[InsightMetricOut] = []
        for i, m in enumerate(data.metrics):
            im_row = await db.fetchrow(
                """INSERT INTO insight_metrics (insight_id, metric_id, custom_label, sort_order)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id""",
                insight_id, m.metric_id, m.custom_label, i,
            )
            metric_name: str | None = None
            metric_icon: str | None = None
            if m.metric_id is not None:
                md = await db.fetchrow(
                    "SELECT name, icon FROM metric_definitions WHERE id = $1 AND user_id = $2",
                    m.metric_id, current_user["id"],
                )
                if md:
                    metric_name = md["name"]
                    metric_icon = md["icon"]
            metrics_out.append(InsightMetricOut(
                id=im_row["id"],
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
    existing = await db.fetchrow(
        "SELECT id FROM insights WHERE id = $1 AND user_id = $2",
        insight_id, current_user["id"],
    )
    if not existing:
        raise HTTPException(404, "Insight not found")

    async with db.transaction():
        if data.text is not None:
            await db.execute(
                "UPDATE insights SET text = $1, updated_at = now() WHERE id = $2",
                data.text.strip(), insight_id,
            )

        if data.metrics is not None:
            await db.execute(
                "DELETE FROM insight_metrics WHERE insight_id = $1",
                insight_id,
            )
            for i, m in enumerate(data.metrics):
                await db.execute(
                    """INSERT INTO insight_metrics (insight_id, metric_id, custom_label, sort_order)
                       VALUES ($1, $2, $3, $4)""",
                    insight_id, m.metric_id, m.custom_label, i,
                )
            # Touch updated_at even if only metrics changed
            await db.execute(
                "UPDATE insights SET updated_at = now() WHERE id = $1",
                insight_id,
            )

    # Re-fetch full insight
    rows = await db.fetch(
        """SELECT i.id, i.text, i.created_at, i.updated_at,
                  im.id AS im_id, im.metric_id, im.custom_label,
                  im.sort_order AS im_sort_order,
                  md.name AS metric_name, md.icon AS metric_icon
           FROM insights i
           LEFT JOIN insight_metrics im ON im.insight_id = i.id
           LEFT JOIN metric_definitions md ON md.id = im.metric_id
           WHERE i.id = $1
           ORDER BY im.sort_order""",
        insight_id,
    )
    return _build_insights(rows)[0]


@router.delete("/{insight_id}", status_code=204)
async def delete_insight(
    insight_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM insights WHERE id = $1 AND user_id = $2",
        insight_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Insight not found")
    await db.execute("DELETE FROM insights WHERE id = $1", insight_id)
