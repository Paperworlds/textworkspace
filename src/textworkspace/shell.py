"""Fish function generation for the Paperworlds stack."""

from __future__ import annotations

# Main tw wrapper that handles __TW_EVAL__ protocol for env-setting commands
TW_WRAPPER = """\
function tw
    # Only capture output for 'switch' (needs __TW_EVAL__ to set env in parent shell).
    # All other commands run directly so interactive prompts and streaming output work.
    if test (count $argv) -gt 0; and test "$argv[1]" = switch
        set -lx __TW_WRAPPER__ 1
        set -l out (command textworkspace $argv)
        set -l status_code $status
        if test $status_code -ne 0
            printf '%s\\n' $out >&2
            return $status_code
        end
        if test (count $out) -gt 0; and string match -q '__TW_EVAL__*' $out[1]
            for line in $out[2..-1]
                eval $line
            end
        else
            printf '%s\\n' $out
        end
    else
        command textworkspace $argv
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
