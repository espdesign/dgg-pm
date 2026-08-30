# Devenv Usage Rules

When working in this repository:
- Execute all Python commands, tests, linters, formatters, and database operations inside the devenv environment using `devenv shell -- <command>`.
- Use the built-in helper scripts: `run-tests`, `run-app`, `lint`, `format`, `db-init`, `db-shell`, `sync`.
- Use `devenv up` to start PostgreSQL and application background services.
- Never install packages into global Python; manage dependencies via `pyproject.toml` and `devenv shell -- sync`.
