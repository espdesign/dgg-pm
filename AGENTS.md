# Project Instructions & Workspace Rules

## Development Environment (`devenv`)

This project uses [`devenv`](https://devenv.sh/) (Nix-based) for managing Python, PostgreSQL, toolchains, and environment variables.

### Rules for Tool & Command Execution

1. **Always use `devenv shell -- <cmd>` for non-interactive commands**:
   - The host system runs in a Nix environment where tools (`python`, `python3`, `pip`, `pytest`, `ruff`, `uv`, etc.) are not in host `$PATH`.
   - Do NOT run bare `python3`, `python`, `pip`, `pytest`, or `ruff` directly on the host.
   - Always execute all commands, one-off scripts, test runs, and tooling through `devenv shell -- <command>` (or `nix shell`).
   - **Do NOT write or edit source files using shell scripts or inline python** (e.g. `python -c "open(...)"` or `cat <<EOF`). Always use the dedicated file editing tools (`replace_file_content`) to modify code files.

2. **Common devenv Commands**:
   - **Run Test Suite**: `devenv shell -- run-tests` (or `devenv shell -- pytest`)
   - **Run Application**: `devenv shell -- run-app` (or `devenv shell -- python src/main.py`)
   - **Linting**: `devenv shell -- lint` (or `devenv shell -- ruff check .`)
   - **Formatting**: `devenv shell -- format` (or `devenv shell -- ruff format .`)
   - **Database Initialization**: `devenv shell -- db-init`
   - **Database Clear/Wipe**: `devenv shell -- db-clear`
   - **Database Reset & Re-seed**: `devenv shell -- db-reset`
   - **Database Shell**: `devenv shell -- db-shell`
   - **Sync Dependencies**: `devenv shell -- sync` (or `devenv shell -- uv sync --all-extras`)

3. **Background Services**:
   - PostgreSQL 16 is managed via devenv.
   - Use `devenv up` to start all declared services and background processes.

4. **Dependency Management**:
   - Specify new runtime and development dependencies in `pyproject.toml`.
   - Sync the virtual environment using `devenv shell -- sync`.

5. **Deployment & App Container Rebuild**:
   - When finished making code changes/updates, always rebuild and restart the application container by running `docker compose up -d --build app`.
