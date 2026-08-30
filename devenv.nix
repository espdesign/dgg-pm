{ pkgs, lib, config, inputs, ... }:

{
  # Default environment variables for local development
  env = {
    DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/dgg_pm";
    API_HOST = "127.0.0.1";
    API_PORT = "8000";
    OUTBOX_POLL_INTERVAL_SECONDS = "5.0";
    OUTBOX_BATCH_SIZE = "10";
  };

  # Packages available in the shell environment
  packages = with pkgs; [
    git
    curl
    ruff
    postgresql_16
  ];

  # Python language configuration
  languages.python = {
    enable = true;
    package = pkgs.python312;
    venv.enable = true;
    uv = {
      enable = true;
      sync = {
        enable = true;
        allExtras = true;
      };
    };
  };

  # PostgreSQL service configuration
  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    initialDatabases = [
      {
        name = "dgg_pm";
        user = "postgres";
        pass = "postgres";
      }
    ];
    listen_addresses = "127.0.0.1";
    port = 5432;
  };

  # Background processes when running `devenv up`
  processes = {
    app.exec = "python -m src.main";
  };

  # Handy helper scripts
  scripts = {
    run-app.exec = ''
      python -m src.main
    '';

    run-tests.exec = ''
      pytest -v tests/
    '';

    lint.exec = ''
      ruff check .
    '';

    format.exec = ''
      ruff format .
    '';

    db-init.exec = ''
      python -c 'import asyncio; from src.adapters.db.session import init_db; asyncio.run(init_db())'
    '';

    db-clear.exec = ''
      python scripts/clear_db.py
    '';

    db-reset.exec = ''
      python scripts/clear_db.py --seed
    '';

    db-shell.exec = ''
      psql -h 127.0.0.1 -U postgres -d dgg_pm
    '';

    sync.exec = ''
      uv sync --all-extras
    '';
  };

  # Actions to run when entering shell
  enterShell = ''
    # Load .env file if it exists
    if [ -f .env ]; then
      set -a
      source .env
      set +a
    fi

    echo "=========================================================="
    echo " 🚀 Welcome to the dgg-pm Development Environment (devenv)"
    echo "=========================================================="
    echo " Python     : $(python --version 2>/dev/null || echo 'Python 3.12')"
    echo " PostgreSQL : PostgreSQL 16 (services.postgres)"
    echo ""
    echo " Available commands:"
    echo "   - run-app      : Start the dgg-pm bot & API server"
    echo "   - run-tests    : Run test suite with pytest"
    echo "   - lint         : Run ruff lint checks"
    echo "   - format       : Auto-format code with ruff"
    echo "   - db-init      : Initialize PostgreSQL database schema"
    echo "   - db-clear     : Wipe/truncate PostgreSQL database tables"
    echo "   - db-reset     : Wipe database tables and re-seed test data"
    echo "   - db-shell     : Open interactive psql shell"
    echo "   - sync         : Sync dependencies with uv"
    echo "   - devenv up    : Start background services (PostgreSQL, App)"
    echo "=========================================================="
  '';

  # Pre-commit hooks
  git-hooks.hooks = {
    ruff.enable = true;
    ruff-format.enable = true;
  };
}
