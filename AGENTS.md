# Project Instructions & Workspace Rules

## Development Environment (`devenv`)

This project uses [`devenv`](https://devenv.sh/) (Nix-based) for managing Python, PostgreSQL, toolchains, and environment variables.

### Rules for Tool & Command Execution

1. **Always use `devenv shell -- <cmd>` for non-interactive commands**:
   - Do NOT run `pip`, `pytest`, `python`, or `ruff` directly on the host system without devenv.
   - Execute all project-related commands, test runs, linting, and script invocations using `devenv shell -- <command>`.

2. **Common devenv Commands**:
   - **Run Test Suite**: `devenv shell -- run-tests` (or `devenv shell -- pytest`)
   - **Run Application**: `devenv shell -- run-app` (or `devenv shell -- python src/main.py`)
   - **Linting**: `devenv shell -- lint` (or `devenv shell -- ruff check .`)
   - **Formatting**: `devenv shell -- format` (or `devenv shell -- ruff format .`)
   - **Database Initialization**: `devenv shell -- db-init`
   - **Database Shell**: `devenv shell -- db-shell`
   - **Sync Dependencies**: `devenv shell -- sync` (or `devenv shell -- uv sync --all-extras`)

3. **Background Services**:
   - PostgreSQL 16 is managed via devenv.
   - Use `devenv up` to start all declared services and background processes.

4. **Dependency Management**:
   - Specify new runtime and development dependencies in `pyproject.toml`.
   - Sync the virtual environment using `devenv shell -- sync`.
