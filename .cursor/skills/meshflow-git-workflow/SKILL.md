---
name: meshflow-git-workflow
description: >-
  Git workflow for Meshflow (meshflow-api, meshtastic-bot, meshtastic-bot-ui).
  Plan with GitHub issues, branch by issue number, use conventional commits,
  open PRs with linked tickets. Use when starting features, committing, or
  opening pull requests in any Meshflow repo.
---

# Meshflow Git Workflow

## Overview

When working on a feature across meshflow-api, meshtastic-bot, or meshtastic-bot-ui, follow this workflow: plan → issue → branch → commit → PR.

Use the `github-personal` MCP for all MeshFlow work.

We start by documenting and refining a plan collaboratively. After agreeing upon the plan, create tickets in applicable repositories. If necessary add a parent ticket and create linked children. Add the plan to the single or parent ticket, and exerpts of the plan to any children. Update the plan with links to any relevant tickets.

It's also possible that we start with a lightweight ticket (i.e. a feature request from a user), then generate the plan. In that situation, the ticket should be updated with full details from the plan, instead of creating a new one

When executing the plan:

1. Create our git branches from origin/main
2. Do the work
3. Commit as appropriate
4. Push and open a pull request for applicable repositories. Link relevant tickets.
5. Done

---

## 1. Planning and Issues

**Single-repo work**: Create one issue in the relevant repo with the plan.

**Multi-repo work**: Create a parent issue in meshflow-api and child issues in each affected repo. Link children to the parent.

---

## 2. Branch Naming

Format: `{issue-repo-prefix}-{issue-number}/{author}/{short-description}`

**Which prefix?** Use the prefix for the **GitHub repository where the tracking issue lives**, not the repo you are committing in. That keeps one issue number traceable across Meshflow repos.

| Issue filed in | Prefix | Use that prefix in every repo that has a branch for the work |
|----------------|--------|----------------------------------------------------------------|
| meshtastic-bot-ui | `ui` | e.g. UI #136 → `ui-136/paddy/...` in **both** meshtastic-bot-ui **and** meshflow-api (and meshtastic-bot if needed) |
| meshflow-api | `api` | e.g. API #456 → `api-456/paddy/...` in every affected repo |
| meshtastic-bot | `bot` | e.g. bot #123 → `bot-123/paddy/...` in every affected repo |

Use kebab-case for the description. Keep it short.

---

## 3. Pre-commit Formatting

**Before committing**, run the project's formatters:

### meshflow-api

```bash
cd meshflow-api
source venv/bin/activate
cd Meshflow
black .
isort .
flake8 .
```

### meshtastic-bot

```bash
cd meshtastic-bot
source venv/bin/activate
black src/
isort src/
flake8 src/
```

### meshtastic-bot-ui

```bash
cd meshtastic-bot-ui
npm run format
```

---

## 4. Commits

Use [conventional commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Rules**:
- Be brief but descriptive
- Do **not** use the word "enhance"

**Examples**:
```
feat(nodes): add last_heard filter to observed-nodes list
fix(api): correct timezone handling in packet ingestion
refactor(storage): extract packet parsing into service
```

---

## 5. Pull Requests

When the work is done:

1. Open a PR in each affected repository using the github-personal MCP. Do not use gh cli.
2. Link the relevant issue(s) in the PR (e.g. "Closes #123")
3. For multi-repo changes, link related PRs between repos in the description

**PR description**: Use the project's `.github/pull_request_template.md` (Summary, Testing performed).

---

## Quick Reference

| Step | Action |
|------|--------|
| Plan | Issue in relevant repo(s); parent in meshflow-api if multi-repo |
| Branch | `{issue-repo-prefix}-{num}/{author}/{description}` (prefix = repo where the issue lives) |
| Pre-commit | meshflow-api/meshtastic-bot: venv + black, isort, flake8; meshtastic-bot-ui: `npm run format` |
| Commit | Conventional commits, no "enhance" |
| PR | Open in all affected repos, link issues and related PRs |
