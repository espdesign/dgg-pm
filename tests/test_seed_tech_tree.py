import pytest

from scripts.seed_tech_tree_forum import (
    TECH_TREE_NODES,
    check_production_safety_guard,
    seed_tech_tree_db,
)
from src.config import settings
from src.domain.enums import TaskStatus


def test_seed_tech_tree_safety_guards(monkeypatch):
    # Production environment check
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="SAFETY BLOCK: Seeding script cannot be run in production"):
        check_production_safety_guard()

    # Cloud DB check
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://user:pass@ep-cool-db.us-east-2.neon.tech/dgg_pm"
    )
    with pytest.raises(
        RuntimeError, match="SAFETY BLOCK: DATABASE_URL appears to point to a production/cloud database"
    ):
        check_production_safety_guard()


@pytest.mark.asyncio
async def test_seed_tech_tree_db_creation():
    guild_id = 998877880

    project, tasks_by_index, task_service = await seed_tech_tree_db(
        guild_id=guild_id,
        project_name="Autonomous Swarm Platform",
        project_prefix="TREE",
        reset_existing=True,
    )

    assert project is not None
    assert project.prefix == "TREE"
    assert len(tasks_by_index) == len(TECH_TREE_NODES)

    # Verify specific nodes and states
    t1 = tasks_by_index[1]
    assert t1.status == TaskStatus.COMPLETED
    assert t1.short_id == "TREE-1"

    t4 = tasks_by_index[4]
    assert t4.status == TaskStatus.IN_PROGRESS

    t11 = tasks_by_index[11]
    assert t11.metadata_json.get("blocked") is True

    # Verify dependencies populated in DB
    prereqs_3, _ = await task_service.get_task_dependencies(tasks_by_index[3].id)
    assert len(prereqs_3) == 1
    assert prereqs_3[0].id == t1.id

    prereqs_6, _ = await task_service.get_task_dependencies(tasks_by_index[6].id)
    assert len(prereqs_6) == 2
    prereq_6_ids = {p.id for p in prereqs_6}
    assert tasks_by_index[3].id in prereq_6_ids
    assert tasks_by_index[4].id in prereq_6_ids

    # Verify Tech Tree Data derivation
    nodes, edges = await task_service.get_project_tree_data(guild_id, project.id)
    assert len(nodes) == len(TECH_TREE_NODES)
    assert len(edges) > 0

    node_map = {n["key"]: n for n in nodes}
    assert node_map["TREE-1"]["state"] == "complete"
    assert node_map["TREE-2"]["state"] == "complete"
    assert node_map["TREE-3"]["state"] == "complete"
    assert node_map["TREE-4"]["state"] == "active"
    assert node_map["TREE-5"]["state"] == "complete"
    assert node_map["TREE-6"]["state"] == "active"
    assert node_map["TREE-7"]["state"] == "available"  # Prereq TREE-5 is complete!
    assert node_map["TREE-8"]["state"] == "complete"
    assert node_map["TREE-9"]["state"] == "locked"  # Prereqs 6 & 7 not complete
    assert node_map["TREE-10"]["state"] == "available"  # Prereq TREE-8 is complete!
    assert node_map["TREE-11"]["state"] == "blocked"  # Metadata blocked: True
    assert node_map["TREE-12"]["state"] == "locked"  # Prereqs 9 & 10 not complete
