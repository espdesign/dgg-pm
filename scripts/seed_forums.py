"""Simple Forum Seeding Script for dgg-pm.

Creates two Discord forum channels:
1. 🎯-single-project: A forum bound to a single project ("Platform Core" [CORE]) with tasks.
2. 🌐-multi-project-hub: A forum hosting three projects ("Web Portal" [WEB], "API Gateway" [GATE],
   and "Mobile App" [MBL]) demonstrating multi-project forum organization, per-project filtering
   tags (📁 Web Portal, 📁 API Gateway, 📁 Mobile App), shared pinned Control Hub, and task cards.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import discord  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from src.adapters.db.postgres_repo import (  # noqa: E402
    PostgresOutboxRepo,
    PostgresProjectRepo,
    PostgresTaskRepo,
)
from src.adapters.db.session import async_session_factory, close_db, init_db  # noqa: E402
from src.adapters.db.tables import (  # noqa: E402
    ProjectTable,
    TaskDependencyTable,
    TaskHistoryTable,
    TaskTable,
    TaskWatcherTable,
)
from src.adapters.db.unit_of_work import SqlAlchemyUnitOfWork  # noqa: E402
from src.adapters.discord_bot.views.forum_helpers import (  # noqa: E402
    STANDARD_PM_TAG_DEFINITIONS,
    ensure_pinned_hub_post,
    ensure_project_tag,
    resolve_forum_tags,
    setup_forum_tags,
)
from src.adapters.discord_bot.views.task_buttons import TaskActionView  # noqa: E402
from src.adapters.discord_bot.views.task_embed import (  # noqa: E402
    build_task_embed,
    build_thread_workspace_content,
)
from src.config import settings  # noqa: E402
from src.domain.enums import PriorityLevel, TaskStatus  # noqa: E402
from src.domain.models import Project, Task  # noqa: E402
from src.services.outbox_service import OutboxService  # noqa: E402
from src.services.project_service import ProjectService  # noqa: E402
from src.services.task_service import TaskService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_forums")


# Seed configuration definitions
FORUM_SEED_SPECS: list[dict[str, Any]] = [
    {
        "channel_name": "🎯-single-project",
        "topic": "Single-project workspace for Core Platform services",
        "projects": [
            {
                "name": "Platform Core",
                "prefix": "CORE",
                "category": "Core Engineering",
                "description": "Core platform services, shared architecture, and central business logic.",
                "tasks": [
                    (
                        "Implement User Authentication & Session Validation",
                        PriorityLevel.HIGH,
                        TaskStatus.IN_PROGRESS,
                        2,
                        "Deliver OAuth2 JWT issuance, session validation middleware, and token revocation.",
                    ),
                    (
                        "Configure PostgreSQL connection pooling and health checks",
                        PriorityLevel.HIGH,
                        TaskStatus.COMPLETED,
                        None,
                        "Tune asyncpg connection pool parameters, keepalives, and automatic health check ping.",
                    ),
                    (
                        "Refactor unified error handling middleware",
                        PriorityLevel.NORMAL,
                        TaskStatus.NOT_STARTED,
                        5,
                        "Centralize application exception hierarchies and standardize RFC 7807 error responses.",
                    ),
                    (
                        "Design REST & WebSocket event payload schemas",
                        PriorityLevel.LOW,
                        TaskStatus.NOT_STARTED,
                        8,
                        "Define Pydantic schema contracts for asynchronous event dispatch.",
                    ),
                ],
            }
        ],
    },
    {
        "channel_name": "🌐-multi-project-hub",
        "topic": "Multi-project forum hub hosting Web Portal, API Gateway, and Mobile App",
        "projects": [
            {
                "name": "Web Portal",
                "prefix": "WEB",
                "category": "Frontend",
                "description": "Customer-facing web application and dashboard built with Next.js.",
                "tasks": [
                    (
                        "Build responsive navigation bar and theme switcher",
                        PriorityLevel.NORMAL,
                        TaskStatus.COMPLETED,
                        None,
                        "Implement accessible navbar with responsive mobile drawer and dark/light theme toggle.",
                    ),
                    (
                        "Implement project overview metrics cards",
                        PriorityLevel.HIGH,
                        TaskStatus.IN_PROGRESS,
                        3,
                        "Real-time task counters, velocity sparklines, and status breakdown charts.",
                    ),
                    (
                        "Integrate WebSocket live task updates on client",
                        PriorityLevel.HIGH,
                        TaskStatus.NOT_STARTED,
                        7,
                        "Listen for outbox task update events over WebSocket and update UI cache optimistically.",
                    ),
                ],
            },
            {
                "name": "API Gateway",
                "prefix": "GATE",
                "category": "Backend",
                "description": "High-performance reverse proxy and API routing layer.",
                "tasks": [
                    (
                        "Setup Redis rate limiting for public endpoints",
                        PriorityLevel.HIGH,
                        TaskStatus.IN_PROGRESS,
                        2,
                        "Sliding-window token bucket algorithm via Redis Lua script for API consumers.",
                    ),
                    (
                        "Implement JWT token verification and claims extractor",
                        PriorityLevel.HIGH,
                        TaskStatus.COMPLETED,
                        None,
                        "Fast ed25519 signature validation and request context claims attachment.",
                    ),
                    (
                        "Add structured JSON request logging & tracing",
                        PriorityLevel.NORMAL,
                        TaskStatus.NOT_STARTED,
                        6,
                        "OpenTelemetry distributed trace header propagation and correlation ID logging.",
                    ),
                ],
            },
            {
                "name": "Mobile App",
                "prefix": "MBL",
                "category": "Mobile",
                "description": "Cross-platform mobile application for iOS and Android.",
                "tasks": [
                    (
                        "Setup push notification handlers with APNS & FCM",
                        PriorityLevel.HIGH,
                        TaskStatus.NOT_STARTED,
                        4,
                        "Register device tokens and dispatch background alerts for task assignments.",
                    ),
                    (
                        "Implement biometric authentication (FaceID / Fingerprint)",
                        PriorityLevel.NORMAL,
                        TaskStatus.IN_PROGRESS,
                        3,
                        "Native biometric prompt integration with encrypted keychain fallback.",
                    ),
                    (
                        "Build offline SQLite task caching and synchronization",
                        PriorityLevel.NORMAL,
                        TaskStatus.NOT_STARTED,
                        10,
                        "Local offline database cache with background delta sync on reconnect.",
                    ),
                ],
            },
        ],
    },
]


def check_production_safety_guard(guild_id: int | None = None) -> None:
    """Blocks execution in production or if connected to a remote production database."""
    env = (settings.ENVIRONMENT or "").lower().strip()
    if env in ("prod", "production", "live"):
        raise RuntimeError(f"⛔ SAFETY BLOCK: Seeding script cannot be run in production (ENVIRONMENT='{env}').")

    db_url = (settings.DATABASE_URL or "").lower()
    unsafe_keywords = [
        "rds.amazonaws.com",
        "supabase.co",
        "supabase.com",
        "neon.tech",
        "cockroachlabs.cloud",
        "render.com",
        "railway.app",
        "cloudsql",
        "elephantsql.com",
    ]
    if any(kw in db_url for kw in unsafe_keywords):
        raise RuntimeError(
            f"⛔ SAFETY BLOCK: DATABASE_URL appears to point to a production/cloud database ({db_url})! "
            "Seeding aborted to prevent accidental data modification."
        )


async def seed_forums_db(
    guild_id: int,
    reset_existing: bool = False,
    actor_discord_id: int | None = None,
    session_factory: Any | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], TaskService]:
    """Seeds the database records for both forums, their projects, and tasks.

    Returns:
        tuple of (seeded_data_dict, task_service)
        seeded_data_dict is keyed by channel_name and contains list of dicts:
        {"project": Project, "tasks": list[Task]}
    """
    if session_factory is None:
        await init_db()
        sess_factory = async_session_factory
    else:
        sess_factory = session_factory

    task_repo = PostgresTaskRepo(sess_factory)
    project_repo = PostgresProjectRepo(sess_factory)
    outbox_repo = PostgresOutboxRepo(sess_factory)
    uow = SqlAlchemyUnitOfWork(sess_factory)
    project_service = ProjectService(project_repo)
    outbox_service = OutboxService(outbox_repo)
    task_service = TaskService(task_repo, project_service, outbox_service, uow=uow)

    actor_id = actor_discord_id or int(settings.DISCORD_CLIENT_ID or 1001)
    results: dict[str, list[dict[str, Any]]] = {}

    for forum_spec in FORUM_SEED_SPECS:
        chan_name = forum_spec["channel_name"]
        results[chan_name] = []

        for proj_spec in forum_spec["projects"]:
            prefix = proj_spec["prefix"]
            name = proj_spec["name"]
            category = proj_spec["category"]
            description = proj_spec["description"]
            task_specs = proj_spec["tasks"]

            existing_proj = await project_repo.get_by_prefix(guild_id, prefix)

            if existing_proj and reset_existing:
                logger.info(f"Purging existing project [{prefix}] '{name}' for fresh reset...")
                async with sess_factory() as session:
                    task_ids_stmt = select(TaskTable.id).where(TaskTable.project_id == existing_proj.id)
                    res = await session.execute(task_ids_stmt)
                    t_ids = [r[0] for r in res.all()]
                    if t_ids:
                        await session.execute(
                            delete(TaskDependencyTable).where(
                                (TaskDependencyTable.task_id.in_(t_ids))
                                | (TaskDependencyTable.depends_on_task_id.in_(t_ids))
                            )
                        )
                        await session.execute(delete(TaskWatcherTable).where(TaskWatcherTable.task_id.in_(t_ids)))
                        await session.execute(delete(TaskHistoryTable).where(TaskHistoryTable.task_id.in_(t_ids)))
                        await session.execute(delete(TaskTable).where(TaskTable.id.in_(t_ids)))
                    await session.execute(delete(ProjectTable).where(ProjectTable.id == existing_proj.id))
                    await session.commit()
                existing_proj = None

            if not existing_proj:
                project = await project_service.create_project(
                    guild_id=guild_id,
                    name=name,
                    prefix=prefix,
                    description=description,
                    category=category,
                )
                logger.info(f"Created Project: [{project.prefix}] '{project.name}' (ID: {project.id})")
            else:
                project = existing_proj
                logger.info(f"Using Existing Project: [{project.prefix}] '{project.name}' (ID: {project.id})")

            # Query existing tasks in project
            existing_tasks, _ = await task_service.list_tasks(guild_id, project_id=project.id, limit=100)
            existing_by_title = {t.title.lower(): t for t in existing_tasks}

            created_tasks: list[Task] = []
            for title, priority, status, days_offset, body in task_specs:
                due_at = (datetime.now(UTC) + timedelta(days=days_offset)) if days_offset is not None else None
                task = existing_by_title.get(title.lower())
                if not task:
                    task = await task_service.create_task(
                        guild_id=guild_id,
                        title=title,
                        creator_discord_id=actor_id,
                        project_id=project.id,
                        due_at=due_at,
                        priority=priority,
                        body=body,
                    )
                    logger.info(f"  • Created Task [{task.short_id}] '{task.title}'")

                if status != TaskStatus.NOT_STARTED and task.status != status:
                    task = await task_service.update_status(
                        task_id=task.id,
                        new_status=status,
                        expected_version=task.version,
                        actor_discord_id=actor_id,
                    )

                created_tasks.append(task)

            results[chan_name].append({"project": project, "tasks": created_tasks})

    return results, task_service


async def seed_discord_forums(
    guild_id: int,
    db_results: dict[str, list[dict[str, Any]]],
    task_service: TaskService,
    reset_existing: bool = False,
) -> None:
    """Creates the Discord Forum channels, sets up tags, pins Control Hubs, and posts task cards."""
    if not settings.DISCORD_BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN not configured. Skipping Discord channel & post creation.")
        return

    client = discord.Client(intents=discord.Intents.default())
    await client.login(settings.DISCORD_BOT_TOKEN)
    logger.info(f"Connected to Discord as {client.user} (ID: {getattr(client.user, 'id', None)})")

    try:
        guild = await client.fetch_guild(guild_id)
        channels = await guild.fetch_channels()
    except Exception as e:
        logger.error(f"Failed to fetch Discord guild {guild_id}: {e}")
        await client.close()
        return

    # Find or create Projects Category
    category_name = "📁 DGG-PM Projects"
    category = next(
        (c for c in channels if isinstance(c, discord.CategoryChannel) and c.name.lower() == category_name.lower()),
        None,
    )
    if not category:
        try:
            category = await guild.create_category(category_name)
            logger.info(f"Created Discord Category: '{category.name}'")
        except Exception as e:
            logger.warning(f"Could not create Discord category '{category_name}': {e}")
            category = None

    for forum_spec in FORUM_SEED_SPECS:
        chan_name = forum_spec["channel_name"]
        topic = forum_spec["topic"]
        clean_name = chan_name.replace("🎯-", "").replace("🌐-", "").strip("-")
        proj_entries = db_results.get(chan_name, [])

        # Find existing forum channel
        forum_channel = next(
            (
                c
                for c in channels
                if isinstance(c, discord.ForumChannel)
                and c.name.lower() in (chan_name.lower(), clean_name.lower(), f"🎯-{clean_name}".lower())
            ),
            None,
        )

        if not forum_channel:
            standard_tags = [discord.ForumTag(name=d["name"], emoji=d["emoji"]) for d in STANDARD_PM_TAG_DEFINITIONS]
            try:
                forum_channel = await guild.create_forum(
                    name=chan_name,
                    category=category,
                    topic=topic,
                    available_tags=standard_tags,
                )
                logger.info(f"Created Forum Channel: #{forum_channel.name} (ID: {forum_channel.id})")
                channels.append(forum_channel)
            except Exception as e:
                logger.error(f"Failed to create forum channel #{chan_name}: {e}")
                continue
        else:
            logger.info(f"Using Existing Forum Channel: #{forum_channel.name} (ID: {forum_channel.id})")

        # 1. Setup standard PM tags
        await setup_forum_tags(forum_channel)

        # 2. Ensure per-project tags and bind channel ID in database
        for entry in proj_entries:
            proj: Project = entry["project"]
            await ensure_project_tag(forum_channel, proj.name)
            if proj.discord_channel_id != forum_channel.id:
                await task_service.project_service.update_project_channel(proj.id, forum_channel.id)
                proj.discord_channel_id = forum_channel.id
                logger.info(f"Bound [{proj.prefix}] '{proj.name}' to forum #{forum_channel.name}")

        # 3. Mount pinned Control Hub post
        _hub_ok, hub_msg = await ensure_pinned_hub_post(
            channel=forum_channel,
            project_service=task_service.project_service,
            task_service=task_service,
        )
        logger.info(f"Control Hub for #{forum_channel.name}: {hub_msg}")

        # 4. Create Forum Thread Cards for each Task
        # Check active threads to prevent duplicate posts
        active_threads: list[discord.Thread] = list(getattr(forum_channel, "threads", []))
        try:
            guild_threads = await guild.active_threads()
            for t in guild_threads:
                if t.parent_id == forum_channel.id and t not in active_threads:
                    active_threads.append(t)
        except Exception as e:
            logger.debug(f"Failed to fetch active threads: {e}")

        for entry in proj_entries:
            proj: Project = entry["project"]
            tasks: list[Task] = entry["tasks"]

            for task in tasks:
                fresh_task = await task_service.get_by_id(task.id)
                if not fresh_task:
                    continue

                if fresh_task.discord_thread_id:
                    logger.info(
                        f"  • Task [{fresh_task.short_id}] already posted (Thread ID: {fresh_task.discord_thread_id})"
                    )
                    continue

                embed = build_task_embed(fresh_task, project_name=proj.name)
                action_view = TaskActionView(
                    task_id=fresh_task.id,
                    current_status=fresh_task.status,
                    current_priority=fresh_task.priority,
                    task_service=task_service,
                )
                thread_content = build_thread_workspace_content(fresh_task)
                applied_tags = resolve_forum_tags(forum_channel, fresh_task, project_name=proj.name)

                # Delete any old thread matching short_id if resetting
                if reset_existing:
                    old_thread = next(
                        (t for t in active_threads if t.name.startswith(f"[{fresh_task.short_id}]")),
                        None,
                    )
                    if old_thread:
                        try:
                            await old_thread.delete()
                            active_threads.remove(old_thread)
                        except Exception:
                            pass

                try:
                    res = await forum_channel.create_thread(
                        name=f"[{fresh_task.short_id}] {fresh_task.title[:90]}",
                        content=thread_content,
                        embed=embed,
                        view=action_view,
                        applied_tags=applied_tags,
                        auto_archive_duration=10080,
                    )
                    thread = getattr(res, "thread", res)
                    message = getattr(res, "message", None)
                    msg_id = message.id if message else thread.id

                    await task_service.update_discord_message_ids(
                        task_id=fresh_task.id,
                        discord_message_id=msg_id,
                        discord_thread_id=thread.id,
                    )
                    logger.info(f"  • Posted task card [{fresh_task.short_id}] to #{forum_channel.name}")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"  ❌ Failed to post task [{fresh_task.short_id}]: {e}")

    await client.close()


def print_summary(db_results: dict[str, list[dict[str, Any]]]) -> None:
    """Prints a structured summary of seeded forums, projects, and tasks."""
    print("\n" + "=" * 80)
    print("📋 FORUM SEEDING COMPLETE")
    print("=" * 80)

    for forum_name, proj_entries in db_results.items():
        print(f"\n📂 Forum Channel: #{forum_name} ({len(proj_entries)} Project{'s' if len(proj_entries) > 1 else ''})")
        print("-" * 80)
        for entry in proj_entries:
            proj: Project = entry["project"]
            tasks: list[Task] = entry["tasks"]
            print(f"  📁 [{proj.prefix}] {proj.name} ({len(tasks)} Tasks) — Category: {proj.category}")
            for t in tasks:
                status_symbol = (
                    "✅" if t.status == TaskStatus.COMPLETED else ("🟡" if t.status == TaskStatus.IN_PROGRESS else "⏳")
                )
                print(f"     {status_symbol} [{t.short_id:<8}] ({t.priority.value:<6}) {t.title}")
    print("\n" + "=" * 80 + "\n")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed two Discord forums: one single-project forum and one multi-project forum with 3 projects."
    )
    default_guild = settings.DISCORD_GUILD_ID or 1543430283250901023
    parser.add_argument(
        "--guild-id",
        type=int,
        default=default_guild,
        help=f"Target Discord Guild ID (default: {default_guild})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Purge existing project tasks before re-seeding fresh.",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Seed database records only without Discord channel / card operations.",
    )
    args = parser.parse_args()

    check_production_safety_guard(args.guild_id)

    logger.info(f"🌱 Seeding forums for Guild ID: {args.guild_id}...")
    db_results, task_service = await seed_forums_db(
        guild_id=args.guild_id,
        reset_existing=args.reset,
    )

    if not args.no_discord and settings.DISCORD_BOT_TOKEN:
        await seed_discord_forums(
            guild_id=args.guild_id,
            db_results=db_results,
            task_service=task_service,
            reset_existing=args.reset,
        )
    else:
        logger.info("Skipping Discord forum integration (--no-discord flag set or DISCORD_BOT_TOKEN missing).")

    print_summary(db_results)
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
