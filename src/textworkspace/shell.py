"""Fish function generation for the Paperworlds stack."""

from __future__ import annotations

FISH_TEMPLATE = """\
function {name}
    textworkspace {name} $argv
end
"""


def generate_fish_function(name: str) -> str:
    """Return a fish function definition that delegates to textworkspace."""
    return FISH_TEMPLATE.format(name=name)


def generate_all_functions(names: list[str]) -> str:
    """Return fish function definitions for all given command names."""
    return "\n".join(generate_fish_function(n) for n in names)
