#!/usr/bin/env bash
# Claude Code status line: folder | session | model | tokens | context usage
input=$(cat)

j() { echo "$input" | jq -r "$1" 2>/dev/null; }

cwd=$(j '.workspace.current_dir // .cwd // ""')
folder="${cwd/#"$HOME"/\~}"
session=$(j '.session_name // empty')
[ -z "$session" ] && session=$(j '.session_id // "" | .[0:8]')
model=$(j '.model.display_name // ""')

in_tok=$(j '.context_window.total_input_tokens // 0')
out_tok=$(j '.context_window.total_output_tokens // 0')
pct=$(j '.context_window.used_percentage // empty')
size=$(j '.context_window.context_window_size // empty')

fmt() { # 12345 -> 12.3k
  local n=${1:-0}
  if [ "$n" -ge 1000000 ]; then awk "BEGIN{printf \"%.1fM\", $n/1000000}"
  elif [ "$n" -ge 1000 ]; then awk "BEGIN{printf \"%.1fk\", $n/1000}"
  else echo "$n"; fi
}

# Colors
dim=$'\e[2m'; rst=$'\e[0m'; blue=$'\e[34m'; mag=$'\e[35m'; cyan=$'\e[36m'
green=$'\e[32m'; yellow=$'\e[33m'; red=$'\e[31m'

ctx=""
if [ -n "$pct" ]; then
  p=${pct%.*}
  if [ "$p" -ge 80 ]; then c=$red; elif [ "$p" -ge 50 ]; then c=$yellow; else c=$green; fi
  filled=$((p / 10)); bar=""
  for i in $(seq 1 10); do [ "$i" -le "$filled" ] && bar+="█" || bar+="░"; done
  ctx="${c}${bar} ${p}%${rst}"
  [ -n "$size" ] && ctx+="${dim} of $(fmt "$size")${rst}"
fi

sep="${dim} │ ${rst}"
printf '%s' "${blue}📁 ${folder}${rst}${sep}${mag}💬 ${session}${rst}${sep}${cyan}${model}${rst}${sep}↑$(fmt "$in_tok") ↓$(fmt "$out_tok")${sep}ctx ${ctx}"
