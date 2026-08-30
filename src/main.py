import asyncio
import logging
import signal
import sys

import uvicorn

from src.adapters.api.app import api_app
from src.adapters.db.postgres_repo import (
    PostgresOutboxRepo,
    PostgresProjectRepo,
    PostgresTaskRepo,
    PostgresTeamRepo,
)
from src.adapters.db.session import close_db, get_session, init_db
from src.adapters.discord_bot.bot import DggPmBot
from src.adapters.discord_bot.discord_notifier import DiscordNotifier
from src.adapters.worker.outbox_worker import OutboxWorker
from src.config import settings
from src.services.outbox_service import OutboxService
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dgg_pm.main")


async def run_app() -> None:
    logger.info("Initializing dgg-pm platform...")

    # 1. Initialize Database schema
    await init_db()
    logger.info("Database schema initialized.")

    # 2. Wire Hexagonal Repositories & Services
    async with get_session() as session:
        task_repo = PostgresTaskRepo(session)
        project_repo = PostgresProjectRepo(session)
        team_repo = PostgresTeamRepo(session)
        outbox_repo = PostgresOutboxRepo(session)

        project_service = ProjectService(project_repo)
        team_service = TeamService(team_repo)
        outbox_service = OutboxService(outbox_repo)
        task_service = TaskService(task_repo, project_service, outbox_service)

        # 3. Wire Discord Bot & Notifier
        bot = DggPmBot(
            task_service=task_service,
            project_service=project_service,
            team_service=team_service,
        )
        notifier = DiscordNotifier(bot)

        # 4. Wire Outbox Worker
        worker = OutboxWorker(
            outbox_repo=outbox_repo,
            notifier=notifier,
            poll_interval=settings.OUTBOX_POLL_INTERVAL_SECONDS,
            batch_size=settings.OUTBOX_BATCH_SIZE,
        )

        # 5. Configure FastAPI Server
        uvicorn_config = uvicorn.Config(
            app=api_app,
            host=settings.API_HOST,
            port=settings.API_PORT,
            log_level="warning",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)

        # 6. Gather concurrent async tasks
        tasks = [
            asyncio.create_task(uvicorn_server.serve(), name="FastAPI-Health-Server"),
            asyncio.create_task(worker.start(), name="Outbox-Worker"),
        ]

        if settings.DISCORD_BOT_TOKEN:
            tasks.append(
                asyncio.create_task(
                    bot.start(settings.DISCORD_BOT_TOKEN),
                    name="Discord-Bot-Gateway",
                )
            )
        else:
            logger.warning("DISCORD_BOT_TOKEN is not set. Bot Gateway will not start. (API & Worker running)")

        # Shutdown handler
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def handle_signal():
            logger.info("Received termination signal. Initiating graceful shutdown...")
            worker.stop()
            uvicorn_server.should_exit = True
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Windows support fallback
                pass

        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for t in done:
                if t.exception():
                    logger.error("Service task %s failed with exception: %s", t.get_name(), t.exception())
        finally:
            logger.info("Cleaning up platform resources...")
            worker.stop()
            if not bot.is_closed():
                await bot.close()
            await close_db()
            logger.info("Graceful shutdown complete.")


def main():
    try:
        asyncio.run(run_app())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
