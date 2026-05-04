#!/bin/bash
set -eo pipefail

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

# jq filter to extract streaming text from assistant messages
stream_text='select(.type == "assistant").message.content[]? | select(.type == "text").text // empty | gsub("\n"; "\r\n") | . + "\r\n\n"'

# jq filter to extract final result
final_result='select(.type == "result").result // empty'

for ((i = 1; i <= $1; i++)); do
  tmpfile=$(mktemp)
  trap "rm -f $tmpfile" EXIT

  echo "===== Ralph iteration $i / $1 =====" >&2

  commits=$(git log -n 5 --format="%H%n%ad%n%B---" --date=short 2>/dev/null || echo "No commits found")
  issues=$(gh issue list \
    --state open \
    --label ready-for-agent \
    --json number,title,body,labels,comments \
    --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]' \
    2>/dev/null || echo "[]")
  prompt=$(cat ralph/prompt.md)

  echo "Calling claude (this can take a while before first output)..." >&2

  claude --permission-mode auto \
    --verbose \
    --print \
    --input-format text \
    --output-format stream-json \
    "Previous commits: $commits Issues: $issues $prompt" |
    grep --line-buffered '^{' |
    tee "$tmpfile" |
    jq --unbuffered -rj "$stream_text"

  result=$(jq -r "$final_result" "$tmpfile")

  if [[ "$result" == *"<promise>NO MORE TASKS</promise>"* ]]; then
    echo "Ralph complete after $i iterations."
    exit 0
  fi
done
