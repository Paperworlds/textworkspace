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

# Generate fish shell functions
fish:
    uv run textworkspace shell --fish

# Install fish functions
fish-install:
    uv run textworkspace shell --fish > ~/.config/fish/functions/tw.fish
    @echo "Installed → ~/.config/fish/functions/tw.fish"

# Show current config
config:
    uv run textworkspace config show
