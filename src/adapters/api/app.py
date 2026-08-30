from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select

from src.adapters.db.session import get_session
from src.adapters.db.tables import OutboxEventTable, ProjectTable, TaskTable

api_app = FastAPI(
    title="dgg-pm Service API",
    description="Health and metrics service for Discord-Native Task Management Platform",
    version="0.1.0",
)


@api_app.get("/healthz")
async def health_check() -> dict:
    """Liveness & Readiness probe checking database connectivity."""
    try:
        async with get_session() as session:
            # Simple query to verify DB is responsive
            await session.execute(select(1))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connectivity check failed: {e}") from e


@api_app.get("/metrics")
async def metrics() -> dict:
    """Basic platform operational metrics."""
    try:
        async with get_session() as session:
            task_count_stmt = select(func.count()).select_from(TaskTable)
            task_res = await session.execute(task_count_stmt)
            total_tasks = task_res.scalar() or 0

            proj_count_stmt = select(func.count()).select_from(ProjectTable)
            proj_res = await session.execute(proj_count_stmt)
            total_projects = proj_res.scalar() or 0

            outbox_pending_stmt = (
                select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == "PENDING")
            )
            outbox_res = await session.execute(outbox_pending_stmt)
            pending_outbox = outbox_res.scalar() or 0

        return {
            "total_tasks": total_tasks,
            "total_projects": total_projects,
            "pending_outbox_events": pending_outbox,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
