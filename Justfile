default:
    @just --list

# Run tests
test:
    uv run pytest -x -q

# Run tests verbose
test-v:
    uv run pytest -v

# Install as editable uv tool
install:
    uv tool install -e . --force

# Build distribution
build:
    uv build

# Show CLI help
help:
    uv run textworkspace --help

# Run doctor
doctor:
    uv run textworkspace doctor

# Show unified status
status:
    uv run textworkspace status

# Generate shell wrapper (auto-detects shell, or: just shell --fish/--bash/--zsh)
shell *FLAGS:
    uv run textworkspace shell {{ FLAGS }}

# Install shell wrapper + completions (auto-detects shell)
shell-install:
    uv run textworkspace shell install

# Show current config
config:
    uv run textworkspace config show
