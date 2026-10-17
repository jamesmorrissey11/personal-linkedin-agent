# Style Guide

> Conventions for Personal LinkedIn Agent. Path-specific rules live in `.github/instructions/`.

---

## 1. Code Style

### Language-Specific Conventions

**Primary language:** Python (>=3.10)

| Convention | Rule |
|-----------|------|
| Indentation | 4 spaces |
| Line length | Not enforced (`line-length = 1000` in `pyproject.toml`); keep lines readable |
| Quotes | Double quotes (ruff format default) |
| Dependencies | Managed with `uv`; run everything via `uv run` |

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Variables / functions | snake_case | `get_invitations` |
| Classes | PascalCase | `CorrectDecisionEvaluator` |
| Constants | UPPER_SNAKE | `INVITATION_CARD_SELECTORS` |
| Files | snake_case | `src/linkedin_agent/invitations.py` |
| Test files | `test_*.py` in `tests/` | `test_selectors.py` |

### Formatting Tools

- **Formatter:** ruff format
- **Linter:** ruff
- **Config files:** `pyproject.toml`, `.pre-commit-config.yaml`
- **Run before commit:** `uv run ruff check --fix . && uv run ruff format .`

---

## 2. Documentation Style

### Code Comments

- Comment **why**, not **what**. The code shows what; comments explain reasoning.
- Use doc comments for all public APIs (functions, classes, modules).
- Remove commented-out code. Use version control, not comments, for history.

### Doc Comment Format

```
/**
 * Brief description of what this function does.
 *
 * @param paramName - Description of the parameter
 * @returns Description of the return value
 * @throws ErrorType - When this error occurs
 */
```

### README and Docs

- Every module or package should have a README explaining its purpose.
- Use short paragraphs (2-5 sentences).
- Lead with the most important information.
- Include runnable examples where possible.

---

## 3. Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/) or a similar structured format:

```
<type>(<scope>): <short summary>

<optional body: explain what and why, not how>

<optional footer: breaking changes, issue references>
```

### Types

| Type | When to Use |
|------|------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Build, CI, tooling changes |

### Examples

```
feat(auth): add JWT token refresh endpoint

Implements automatic token refresh when the access token expires.
Refresh tokens are stored in HTTP-only cookies.

Closes #42
```

```
fix(api): handle null response from external service

The payment gateway occasionally returns null instead of an error
object. Added null check with appropriate error mapping.
```

---

## 4. Pull Request Format

### PR Title

Follow the same format as commit messages: `<type>(<scope>): <summary>`

### PR Description Template

```markdown
## What

Brief description of what this PR changes.

## Why

Context and motivation for the change.

## How

Key implementation decisions (not a line-by-line walkthrough).

## Testing

How the changes were tested. Include commands to reproduce.

## Checklist

- [ ] Tests pass locally
- [ ] Documentation updated (if applicable)
- [ ] No unrelated changes included
```

---

## 5. Agent Communication Preferences

When working with AI coding agents, these conventions improve output quality:

### Spec Structure for Agent Stories

- Start with a clear summary of the deliverable.
- List specific files to create or modify.
- Define acceptance criteria as testable conditions.
- Include negative constraints (what the story does NOT do).
- Specify file ownership to prevent overlap with parallel work.

### Review Expectations

- Agent-generated code should pass the same review standards as human-written code.
- Review for correctness, not style (let formatters handle style).
- Every review finding reaches a terminal state: fixed, accepted, or deferred.

### Context Files

- Maintain `AGENTS.md` and `.github/copilot-instructions.md` (agent context files) at the repo root.
- Keep it current. Outdated context files cause agent drift.
- Include: project purpose, structure, conventions, process, and validation gates.

---

## 6. Hard Bans

- No credentials or secrets in source code.
- No `TODO` comments without a linked issue.
- No suppressed linter warnings without a justifying comment.
- No wildcard imports (import only what you use).
- No committed LinkedIn session state, runtime data, or `.env` files. Runtime state lives outside the repo (see `linkedin_agent.runtime`).
- No replacing multi-selector scraping fallbacks with a single selector.
