"""Fish function generation for the Paperworlds stack."""

from __future__ import annotations

# Main tw wrapper that handles __TW_EVAL__ protocol for env-setting commands
TW_WRAPPER = """\
function tw
    set -lx __TW_WRAPPER__ 1
    set -l out (command textworkspace $argv)
    set -l status_code $status
    if test $status_code -eq 0
        # Check if output contains eval directives (__TW_EVAL__ protocol)
        if test (count $out) -gt 0; and string match -q '__TW_EVAL__*' $out[1]
            # Skip the __TW_EVAL__ marker, eval the rest
            for line in $out[2..-1]
                eval $line
            end
        else
            # Normal output, just print it
            printf '%s\\n' $out
        end
    else
        # Command failed, print any error output
        printf '%s\\n' $out >&2
        return $status_code
    end
end
"""

# Simple alias that delegates to tw
ALIAS_TEMPLATE = """\
function {name}
    tw {name} $argv
end
"""


def generate_tw_wrapper() -> str:
    """Return the main tw wrapper function that handles __TW_EVAL__ protocol."""
    return TW_WRAPPER


def generate_alias(name: str) -> str:
    """Return a fish function definition that delegates to tw."""
    return ALIAS_TEMPLATE.format(name=name)


def generate_all_functions(names: list[str]) -> str:
    """Return fish function definitions including tw wrapper and aliases.

    Args:
        names: List of tool/command names to create aliases for (e.g., ['ta', 'ts', 'tp'])

    Returns:
        Fish function definitions for tw wrapper, xtw, and x-aliases.
    """
    lines = [generate_tw_wrapper()]

    # Always create xtw alias
    lines.append(generate_alias("xtw"))

    # Create x-aliases for all provided names
    for name in names:
        lines.append(generate_alias(f"x{name}"))

    return "\n".join(lines)
