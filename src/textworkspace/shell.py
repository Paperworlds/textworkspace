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

XTW_ALIAS = """\
function xtw
    tw $argv
end
"""


def generate_tw_wrapper() -> str:
    return TW_WRAPPER


def generate_all_functions() -> str:
    return "\n".join([generate_tw_wrapper(), XTW_ALIAS])
