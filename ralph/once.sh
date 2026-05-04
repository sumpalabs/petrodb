#!/bin/bash
set -eo pipefail

issues=$(gh issue list \
  --state open \
  --label ready-for-agent \
  --json number,title,body,labels,comments \
  --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]' \
  2>/dev/null || echo "[]")

commits=$(git log -n 5 --format="%H%n%ad%n%B---" --date=short 2>/dev/null || echo "No commits found")
prompt=$(cat ralph/prompt.md)

claude --permission-mode auto \
  "Previous commits: $commits Issues: $issues $prompt"
