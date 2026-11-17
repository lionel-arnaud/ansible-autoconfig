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
if [[ $(hostname -s) == savannarchome && -r $HOME/.ssh/autoconfig-fleet-trigger ]]; then
  fleet-pull() {
    local host logdir status=0 summary result exit_code
    local success_count=0 failed_count=0 unreachable_count=0
    local reset='' bold='' dim='' green='' yellow='' red='' cyan=''
    local monitor_was_enabled=0
    local -a hosts=(serverannah raspi kidsbook)
    local -A pids logs

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

    printf '\n%s%sFleet pull%s — starting 4 managed hosts\n\n' "$bold" "$cyan" "$reset"
    # Bash emits a job number and PID when it starts each background command.
    # Redirect only those shell messages; each command's own output still goes
    # to its per-host log file and is available on a failure.
    {
      sudo -n /usr/bin/systemctl start autoconfig-pull.service >"$logdir/laptop" 2>&1 &
      pids[laptop]=$!
      logs[laptop]="$logdir/laptop"

      for host in "${hosts[@]}"; do
        ssh -i "$HOME/.ssh/autoconfig-fleet-trigger" -o BatchMode=yes -o IdentitiesOnly=yes "$host" start >"$logdir/$host" 2>&1 &
        pids["$host"]=$!
        logs["$host"]="$logdir/$host"
      done
    } 2>/dev/null

    for host in laptop "${hosts[@]}"; do
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
# Omarchy defines apull as an alias. Remove it before defining the function:
# aliases are expanded while Bash parses `apull() {`, and also outrank a
# same-named function at invocation time.
unalias apull 2>/dev/null || true
function apull {
  local status=0

  sudo systemctl start --wait autoconfig-pull.service || status=$?

  if command -v notify-send >/dev/null 2>&1; then
    if ((status == 0)); then
      notify-send -a 'Ansible' -u normal \
        'Ansible pull complete' 'The configuration was applied successfully.'
    else
      notify-send -a 'Ansible' -u critical \
        'Ansible pull failed' 'See: journalctl -u autoconfig-pull.service -n 100'
    fi
  fi

  return "$status"
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
