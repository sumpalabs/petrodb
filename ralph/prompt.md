# ISSUES

Open GitHub issues are provided at the start of context. Parse them to understand what's open.

You will work on issues labelled `ready-for-agent` only. Skip everything else.

You've also been passed a file containing the last few commits. Review these to understand what work has been done.

If there are no `ready-for-agent` issues left, output <promise>NO MORE TASKS</promise>.

# TASK SELECTION

Pick the next issue. Prioritize in this order:

1. Critical bugfixes
2. Development infrastructure

Getting development infrastructure like tests, types, and dev scripts ready is an important precursor to building features.

3. Tracer bullets for new features

Tracer bullets are small slices of functionality that go through all layers of the system, allowing you to test and validate your approach early. This helps in identifying potential issues and ensures that the overall architecture is sound before investing significant time in development.

TL;DR — build a tiny, end-to-end slice of the feature first, then expand it out.

4. Polish and quick wins
5. Refactors

# EXPLORATION

Explore the repo. If you need the full issue body or comments, run:

```
gh issue view <number> --comments
```

# IMPLEMENTATION

Use /tdd to complete the task.

# FEEDBACK LOOPS

Before committing, run the feedback loops:

- `uv run pytest` to run the tests
- `uv run ruff check .` to run the linter
- `uv run ruff format --check .` to verify formatting

Fix any failures before committing.

# COMMIT

Make a git commit. The commit message must:

1. Include key decisions made
2. Include files changed
3. Include blockers or notes for next iteration
4. Reference the issue with `Refs #<number>` (or `Closes #<number>` if the issue is fully done)

# THE ISSUE

If the task is complete, close the GitHub issue with a summary comment:

```
gh issue close <number> --comment "..."
```

If the task is not complete, leave a progress comment on the issue describing what was done and what's left:

```
gh issue comment <number> --body "..."
```

# FINAL RULES

ONLY WORK ON A SINGLE ISSUE.
