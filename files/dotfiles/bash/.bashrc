# If not running interactively, don't do anything (leave this at the top).
[[ $- != *i* ]] && return

# History: ignore dupes/space-prefixed, erase old dupes, keep a decent depth.
HISTCONTROL=ignoreboth:erasedups
HISTSIZE=5000
HISTFILESIZE=10000
shopt -s histappend checkwinsize

# On Omarchy machines, load its default bash rc first (prompt, aliases, etc.).
# Guarded so it is simply skipped on non-Omarchy hosts (servers, raspi, ...).
if [[ -f ~/.local/share/omarchy/default/bash/rc ]]; then
  source ~/.local/share/omarchy/default/bash/rc
fi

# ~/.bashrc.local is sourced at the very end and is itself a managed dotfile
# (Stow symlink into the dotfiles repo). It carries the portable RSE helpers —
# aliases, functions, and tweaks that are identical on every Omarchy host.
# Put per-host tweaks you do NOT want in git (tokens, host IPs, ...) in a
# sibling file like ~/.bashrc.local.secret and source it from there.

#######################################################
# FUNCTIONS (each guards on command availability, so they stay portable)
#######################################################

# Show files with bat syntax highlighting, without opening a pager, when available.
cat() {
  if [[ -t 1 ]] && command -v bat >/dev/null 2>&1; then
    bat --paging=never --style=header,grid "$@"
  else
    command cat "$@"
  fi
}

# Print the current directory and copy it to the Wayland clipboard when available.
pwd() {
  if [[ -n $WAYLAND_DISPLAY ]] && command -v wl-copy >/dev/null 2>&1; then
    builtin pwd "$@" | tee >(wl-copy >/dev/null)
  else
    builtin pwd "$@"
  fi
}

# Use duf when available, otherwise fall back to df.
df() {
  if command -v duf >/dev/null 2>&1; then
    duf "$@"
  else
    command df "$@"
  fi
}

# cheat.sh lookup
cheat() { curl -sL "https://cheat.sh/$1"; }

# Make cd use exact paths first, then fall back to zoxide jumps, and list on arrival.
if command -v zoxide >/dev/null 2>&1; then
  eval "$(zoxide init bash)"

  cd() {
    if (($# == 0)); then
      builtin cd ~ || return
    elif [[ -d $1 ]]; then
      builtin cd "$1" || return
    else
      z "$@" || return
    fi

    if command -v eza >/dev/null 2>&1; then
      eza -lah --group-directories-first --icons=auto
    else
      command ls -lah
    fi
  }
fi

# Searches for text in all files in the current folder.
ftext() {
  # -i case-insensitive, -I ignore binary, -H print filename, -r recursive, -n line numbers
  grep -iIHrn --color=always "$1" . | less -r
}

# Search the text of every local OpenCode conversation, across all projects.
#
# OpenCode's `session.list --param search=...` API searches session titles only.
# The transcript-search API does not exist yet, so this read-only helper queries
# OpenCode's local SQLite database. It handles both the current V2 tables and
# the legacy tables, prints the matching session ID plus surrounding text, and
# lets you resume a match with: opencode --session <session-id>
#
# This searches every observed OpenCode transcript storage layout (legacy
# `part`, current `session_part`, and transitional `session_message`). The
# database schema is internal and can change in a future OpenCode release. It
# never writes to the database.
ocgrep() {
  if (($# != 1)) || [[ -z $1 ]]; then
    printf 'Usage: ocgrep <text>\n' >&2
    return 2
  fi
  if ! command -v opencode >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    printf 'ocgrep requires opencode, python3, and jq.\n' >&2
    return 127
  fi

  local db
  db=$(opencode debug paths db) || return
  if [[ ! -r $db ]]; then
    printf 'OpenCode database is not readable: %s\n' "$db" >&2
    return 1
  fi

  local use_color=false
  [[ -t 1 ]] && use_color=true

  python3 - "$1" "$db" <<'PY' | jq -r --argjson color "$use_color" '
    if .type == "match" then
      if $color then
        "\u001b[1;36m\(.session_id)\u001b[0m  \u001b[1m\(.title)\u001b[0m\n\u001b[2m\(.role) · \(.timestamp)\u001b[0m\n\u001b[2m\(.excerpt)\u001b[0m"
      else
        "\(.session_id) — \(.title)\n\(.role) · \(.timestamp)\n\(.excerpt)"
      end
    else
      "No OpenCode transcript text matched: \(.needle|@json)"
    end
  '
import json
import sqlite3
import sys
from datetime import datetime

needle, database = sys.argv[1], sys.argv[2]

query = """
WITH transcript AS (
  SELECT p.session_id, s2.title, json_extract(p.data, '$.text') AS text,
         p.time_created, p.type AS role
  FROM session_part AS p
  JOIN session_v2 AS s2 ON s2.id = p.session_id
  UNION ALL
  SELECT p.session_id, s.title, json_extract(p.data, '$.text') AS text,
         p.time_created, json_extract(p.data, '$.type') AS role
  FROM part AS p
  JOIN session AS s ON s.id = p.session_id
  UNION ALL
  SELECT sm.session_id, COALESCE(s2.title, s.title), json_extract(sm.data, '$.text') AS text,
         COALESCE(json_extract(sm.data, '$.time.completed'),
                  json_extract(sm.data, '$.time.created'),
                  sm.time_created),
         sm.type AS role
  FROM session_message AS sm
  LEFT JOIN session_v2 AS s2 ON s2.id = sm.session_id
  LEFT JOIN session AS s ON s.id = sm.session_id
  UNION ALL
  SELECT sm.session_id, COALESCE(s2.title, s.title), json_extract(content.value, '$.text') AS text,
         COALESCE(json_extract(sm.data, '$.time.completed'),
                  json_extract(sm.data, '$.time.created'),
                  sm.time_created),
         sm.type AS role
  FROM session_message AS sm
  JOIN json_each(sm.data, '$.content') AS content
  LEFT JOIN session_v2 AS s2 ON s2.id = sm.session_id
  LEFT JOIN session AS s ON s.id = sm.session_id
  WHERE json_extract(content.value, '$.type') = 'text'
)
SELECT session_id, title, text, time_created, role
FROM transcript
WHERE lower(text) LIKE '%' || lower(?) || '%'
ORDER BY time_created DESC
"""

try:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    matches = connection.execute(query, (needle,))
    found = False
    for session_id, title, text, time_created, role in matches:
        if not text:
            continue
        found = True
        excerpt = " ".join(text.split())
        position = excerpt.lower().find(needle.lower())
        start = max(0, position - 120)
        end = position + len(needle) + 240
        timestamp = datetime.fromtimestamp(time_created / 1000).astimezone().isoformat(timespec="seconds")
        print(json.dumps({
            "type": "match",
            "session_id": session_id,
            "title": title or "(untitled session)",
            "role": role or "message",
            "timestamp": timestamp,
            "excerpt": excerpt[start:end],
        }))
    if not found:
        print(json.dumps({"type": "empty", "needle": needle}))
except sqlite3.Error as error:
    print(f"Could not search the OpenCode database: {error}", file=sys.stderr)
    sys.exit(1)
PY
  local pipeline_status=("${PIPESTATUS[@]}")
  (( pipeline_status[0] == 0 && pipeline_status[1] == 0 )) || return 1

  return 0
}

# Copy a file with a progress bar.
cpp() {
  set -e
  strace -q -ewrite cp -- "${1}" "${2}" 2>&1 |
    awk '{
        count += $NF
        if (count % 10 == 0) {
            percent = count / total_size * 100
            printf "%3d%% [", percent
            for (i=0;i<=percent;i++) printf "="
            printf ">"
            for (i=percent;i<100;i++) printf " "
            printf "]\r"
        }
    }
    END { print "" }' total_size="$(stat -c '%s' "${1}")" count=0
}

# Internal + external IP lookup (auto-detects the default interface).
whatsmyip() {
  local iface
  iface=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
  echo -n "Internal IP: "
  ip addr show "${iface:-eth0}" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1
  echo -n "External IP: "
  curl -s ifconfig.me
  echo
}
alias whatismyip="whatsmyip"

# git add . && commit && push, in one go.
lazyg() {
  git add .
  git commit -m "$1"
  git push
}

# Trigger each machine's local Ansible pull in parallel from the laptop. The
# dedicated SSH key is forced on targets to this action only; wait for each
# systemd job so the notification reports the actual final result. Keep the
# output human-oriented: Bash job-control messages are noise, while a host can
# have a failed pull or simply be offline.
if [[ -r $HOME/.ssh/autoconfig-fleet-trigger ]]; then
  fleet-pull() {
    local host logdir status=0 summary result exit_code local_name=laptop
    local success_count=0 failed_count=0 unreachable_count=0
    local reset='' bold='' dim='' green='' yellow='' red='' cyan=''
    local monitor_was_enabled=0
    local -a hosts=(serverannah raspi kidsbook)
    local -a ssh_args=(-i "$HOME/.ssh/autoconfig-fleet-trigger" -o BatchMode=yes -o IdentitiesOnly=yes)
    local -A pids logs
    local fleet_config="$HOME/.config/autoconfig/fleet-pull.conf"
    local ssh_config="$HOME/.ssh/autoconfig-fleet-trigger-config"

    if [[ -r $fleet_config ]]; then
      # This file is managed mode 0600 by the fleet controller role.
      source "$fleet_config"
      local_name=${AUTOCONFIG_FLEET_PULL_LOCAL_NAME:-$local_name}
      hosts=("${AUTOCONFIG_FLEET_PULL_HOSTS[@]}")
    fi
    [[ -r $ssh_config ]] && ssh_args=(-F "$ssh_config")

    sudo -v || return
    logdir=$(mktemp -d "${TMPDIR:-/tmp}/fleet-pull.XXXXXX") || return

    # Prevent completed background jobs printing their own "[1] Done" lines
    # while this function formats the final result.
    if [[ $- == *m* ]]; then
      monitor_was_enabled=1
      set +m
    fi

    if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
      reset=$(tput sgr0)
      bold=$(tput bold)
      dim=$(tput dim)
      green=$(tput setaf 2)
      yellow=$(tput setaf 3)
      red=$(tput setaf 1)
      cyan=$(tput setaf 6)
    fi

    printf '\n%s%sFleet pull%s — starting %d managed hosts\n\n' \
      "$bold" "$cyan" "$reset" "$(( ${#hosts[@]} + 1 ))"
    # Bash emits a job number and PID when it starts each background command.
    # Redirect only those shell messages; each command's own output still goes
    # to its per-host log file and is available on a failure.
    {
      sudo -n /usr/bin/systemctl start autoconfig-pull.service >"$logdir/laptop" 2>&1 &
      pids["$local_name"]=$!
      logs["$local_name"]="$logdir/$local_name"

      for host in "${hosts[@]}"; do
        ssh "${ssh_args[@]}" "$host" start >"$logdir/$host" 2>&1 &
        pids["$host"]=$!
        logs["$host"]="$logdir/$host"
      done
    } 2>/dev/null

    for host in "$local_name" "${hosts[@]}"; do
      if wait "${pids[$host]}"; then
        printf '  %s✓%s %-12s %ssuccess%s\n' "$green" "$reset" "$host" "$dim" "$reset"
        ((success_count++))
      else
        exit_code=$?
        if grep -qE 'No route to host|Connection timed out|Connection refused|Could not resolve hostname' "${logs[$host]}"; then
          result=$(grep -m1 -E 'No route to host|Connection timed out|Connection refused|Could not resolve hostname' "${logs[$host]}")
          printf '  %s✗%s %-12s %sunreachable%s\n' "$yellow" "$reset" "$host" "$dim" "$reset"
          printf '     %s%s%s\n' "$dim" "$result" "$reset"
          ((unreachable_count++))
        else
          result=$(sed -n '/[^[:space:]]/ {p; q;}' "${logs[$host]}")
          printf '  %s✗%s %-12s %spull failed%s %s(exit %d)%s\n' "$red" "$reset" "$host" "$bold" "$reset" "$dim" "$exit_code" "$reset"
          [[ -n $result ]] && printf '     %s%s%s\n' "$dim" "$result" "$reset"
          ((failed_count++))
        fi
        status=1
      fi
    done

    printf '\n%s────────────────────────────────────────────────%s\n' "$dim" "$reset"
    printf '%sSummary:%s %s%d succeeded%s · %s%d failed%s · %s%d unreachable%s\n' \
      "$bold" "$reset" "$green" "$success_count" "$reset" "$red" "$failed_count" "$reset" "$yellow" "$unreachable_count" "$reset"

    if ((status == 0)); then
      summary='Ansible fleet pull completed successfully.'
      rm -rf -- "$logdir"
    else
      summary="Ansible fleet pull completed with ${failed_count} failed and ${unreachable_count} unreachable host(s)."
      printf '%sLogs retained:%s %s\n' "$bold" "$reset" "$logdir"
    fi
    if command -v notify-send >/dev/null 2>&1; then
      notify-send -a 'Ansible fleet' -u "$([[ $status -eq 0 ]] && echo normal || echo critical)" 'Fleet pull complete' "$summary"
    fi
    ((monitor_was_enabled)) && set -m
    return "$status"
  }
fi

#######################################################
# ALIASES
#######################################################

# Listing (fall back to coreutils ls when eza is absent).
if command -v eza >/dev/null 2>&1; then
  alias ls='eza --group-directories-first --icons=auto'
  alias ll='eza -lah --group-directories-first --icons=auto'
  alias la='eza -a --group-directories-first --icons=auto'
else
  alias ls='ls --color=auto'
  alias ll='ls -alFh'
  alias la='ls -Alh'
fi
alias lt='ls -ltrh' # sort by date
alias lk='ls -lSrh' # sort by size

alias ..='cd ..'
alias ...='cd ../..'
alias f="find . | grep "
alias rmd='/bin/rm --recursive --force --verbose '
alias folders='du -h --max-depth=1'
alias treed='tree -CAFda -I ".git"'

# Archives
alias mktar='tar -cvf'
alias mkgz='tar -cvzf'
alias untar='tar -xvf'
alias ungz='tar -xvzf'

# git / docker
alias gs='git status'
alias dcu='docker compose up -d'
alias dcd='docker compose down'
alias docker-clean='docker container prune -f; docker image prune -f; docker network prune -f; docker volume prune -f'

# various tools
alias t='tuios start-agent opencode'
# Run the managed pull synchronously so a desktop notification can report its
# actual outcome, not merely that systemd accepted the start request. The
# service's OnFailure path continues to send the remote ntfy alert; this is the
# local, interactive counterpart for a manually run `apull`.
# This deliberately replaces Omarchy's inherited apull alias. `&&` shows the
# desktop notification only after the Type=oneshot pull service succeeds.
alias apull='sudo systemctl start autoconfig-pull.service && notify-send -a "Ansible" -u normal "Ansible pull complete" "Configuration applied successfully."'

c-later() {
  local duration="${1:-90 minutes}"
  local prompt="${2:-Continue the previous task now.}"
  local sid="${3:-$OC_SESSION}"
  local when

  if [ -z "$sid" ]; then
    cat >&2 <<'EOF'
usage: c-later [duration] [prompt] [session_id]
       (or export OC_SESSION=ses_...)

No session id given. To find one:
  opencode session list        # lists sessions with their ses_... ids
  opencode session --help      # other session subcommands

Then either:
  export OC_SESSION=ses_xxxxxxxx
  c-later "2 hours" "Resume work" ses_xxxxxxxx
EOF
    return 1
  fi

  # OpenCode receives the prompt unchanged and delivers it to the target
  # session at the requested time. This function is deliberately not an AI
  # command: jq only constructs the documented automation API payload.
  case "$duration" in
    in\ *) when="$duration" ;;
    * )    when="in $duration" ;;
  esac

  opencode api post /api/experimental/automation --data "$(jq -nc \
    --arg s "$sid" --arg p "$prompt" --arg w "$when" \
    '{
      name: "Retry later",
      trigger: {type: "at", at: $w},
      action: {type: "prompt", prompt: $p, to: {session: $s}}
    }')"
}

export TLDR_OPTIONS="${TLDR_OPTIONS:-both}"

# Per-machine overrides last, so they win over everything above.
if [[ -f ~/.bashrc.local ]]; then
  . ~/.bashrc.local
fi

# opencode AI coding agent. The upstream install script
# (https://opencode.ai/install) drops the binary at
# ~/.opencode/bin/opencode and appends this line; committing it here makes the
# path available without a local modification to the dotfiles checkout (which
# would otherwise block ansible-pull from updating the repo).
# Keep this standalone install as a fallback so Mise's managed version wins.
export PATH="${PATH}:${HOME}/.opencode/bin"
