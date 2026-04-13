"""Shell wrapper generation for the Paperworlds stack."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fish
# ---------------------------------------------------------------------------

FISH_WRAPPER = """\
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

function xtw
    tw $argv
end
"""

# ---------------------------------------------------------------------------
# Bash / Zsh (identical — both use POSIX function syntax)
# ---------------------------------------------------------------------------

BASH_WRAPPER = """\
tw() {
    if [ "$1" = "switch" ]; then
        local out
        out="$(__TW_WRAPPER__=1 command textworkspace "$@")"
        local rc=$?
        if [ $rc -ne 0 ]; then
            printf '%s\\n' "$out" >&2
            return $rc
        fi
        case "$out" in
            __TW_EVAL__*)
                eval "$(printf '%s\\n' "$out" | tail -n +2)"
                ;;
            *)
                printf '%s\\n' "$out"
                ;;
        esac
    else
        command textworkspace "$@"
    fi
}

xtw() {
    tw "$@"
}
"""


def generate_fish() -> str:
    return FISH_WRAPPER


def generate_bash() -> str:
    return BASH_WRAPPER


# zsh uses the same syntax
generate_zsh = generate_bash
