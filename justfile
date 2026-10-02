# dtandev-running-animation - https://dtanajewski.com
# Usage: just <command>
# Requires: just (https://github.com/casey/just), uv (https://github.com/astral-sh/uv)

# Pass recipe arguments to the shell as "$@" so paths and names with spaces survive
set positional-arguments

# Default: list available commands
default:
    @just --list

# Install dependencies and git hooks
setup:
    @echo "Setting up project environment..."
    uv sync
    uv run pre-commit install
    uv run pre-commit install --hook-type commit-msg
    @echo "✅ Setup complete."

# Generate an animation: just run --gpx FILE [--photos DIR] [--logo FILE] [--name NAME]
run *ARGS:
    uv run python src/main.py "$@"

# Run all tests
test:
    uv run pytest tests/ -v

# Run all quality checks (lint, format)
check:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    @echo "✅ All checks passed."

# Auto-fix lint and format issues
fix:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

# Run pre-commit on all files
lint:
    uv run pre-commit run --all-files
