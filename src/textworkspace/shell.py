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

# Tab completions (Click-generated)
function _textworkspace_completion
    set -l response (env _TEXTWORKSPACE_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) textworkspace)
    for completion in $response
        set -l metadata (string split "," $completion)
        if test $metadata[1] = "dir"
            __fish_complete_directories $metadata[2]
        else if test $metadata[1] = "file"
            __fish_complete_path $metadata[2]
        else if test $metadata[1] = "plain"
            echo $metadata[2]
        end
    end
end
complete --no-files --command textworkspace --arguments "(_textworkspace_completion)"
complete --no-files --command tw --arguments "(_textworkspace_completion)"
complete --no-files --command xtw --arguments "(_textworkspace_completion)"
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

# Tab completions (Click-generated)
_textworkspace_completion() {
    local IFS=$'\\n'
    local response
    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD _TEXTWORKSPACE_COMPLETE=bash_complete $1)
    for completion in $response; do
        IFS=',' read type value <<< "$completion"
        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
        fi
    done
    return 0
}
complete -o nosort -F _textworkspace_completion textworkspace
complete -o nosort -F _textworkspace_completion tw
complete -o nosort -F _textworkspace_completion xtw
"""


def generate_fish() -> str:
    return FISH_WRAPPER


def generate_bash() -> str:
    return BASH_WRAPPER


ZSH_WRAPPER = """\
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

# Tab completions (Click-generated)
_textworkspace_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[textworkspace] )) && return 1
    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) _TEXTWORKSPACE_COMPLETE=zsh_complete textworkspace)}")
    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                completions_with_descriptions+=("$key":"$descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            _path_files -/
        elif [[ "$type" == "file" ]]; then
            _path_files -f
        fi
    done
    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}
compdef _textworkspace_completion textworkspace
compdef _textworkspace_completion tw
compdef _textworkspace_completion xtw
"""


def generate_zsh() -> str:
    return ZSH_WRAPPER
