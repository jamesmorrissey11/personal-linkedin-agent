# Agent-Tools Adapters

An **agent-tools adapter** configures a specific AI coding agent to participate in the Agentic-Agile workflow. Each adapter provides the context, instructions, and tooling configuration that agent needs to understand your project conventions, follow agentic-agile story specs, and integrate with your development environment.

## Available Adapters

| Adapter | Agent | Status | Target file |
|---------|-------|--------|-------------|
| [`github-copilot/`](github-copilot/) | GitHub Copilot (VS Code, JetBrains, CLI) | Maintained | `.github/copilot-instructions.md` |

> `AGENTS.md` (universal cross-agent entry point) lives at the repository root and is **not** an agent-tools adapter — it is the canonical entry point that delegates to one or more of the adapters above. See [`../../AGENTS.md`](../../AGENTS.md).

## Selecting an Adapter

Choose the agent-tools adapter that matches your primary AI coding agent. If your team uses multiple agents (e.g., Copilot plus another agent), you can apply multiple agent-tools adapters — they are designed to coexist in the same repository.

When no adapter exists for your agent, check whether your agent reads a conventions file (like `CLAUDE.md`) and follow the three-file anatomy below to create one.

## Three-File Anatomy

Every agent-tools adapter consists of three files, named as follows:

### 1. `README.md`
Overview of the adapter: which agent it configures, prerequisites, when to choose this adapter, and any agent-specific conventions or limitations that affect how agentic-agile stories should be written for this agent.

### 2. Target-named template file
The **agent context template** — named after the literal filename the agent reads in a downstream project. Examples:
- GitHub Copilot adapter: `copilot-instructions.md` (placed at `.github/copilot-instructions.md` in the downstream project)

This file:
- Tells the agent about the agentic-agile workflow
- Defines story anatomy the agent should expect (scope, file ownership, acceptance criteria)
- Sets conventions for commit messages, PR format, and test expectations

### 3. `quickstart.md`
A short, runnable guide that a new contributor can follow to install the adapter into their own project. Should include: where to copy the target file, how the agent auto-discovers it, any required configuration, and a compatibility table for use alongside other agents.

> Adapters within the **agent-tools** layer should keep their target file (e.g., `copilot-instructions.md`) independent of any specific issue-tracker or ci-cd choice — the three layers (agent-tools / issue-trackers / ci-cd) must remain independently swappable. Multi-tool compatibility tables within an adapter's `quickstart.md` (referencing other agent-tools adapters in the same layer) are expected and encouraged.

## Relationship to Other Layers

Agent-tools adapters are one of three layers in the platform-adapters system:

- **agent-tools** (this layer) — configures the AI agent
- **issue-trackers** — provides story templates for your backlog tool → see [../issue-trackers/](../issue-trackers/)
- **ci-cd** — wires up pipeline checks → see [../ci-cd/](../ci-cd/)

For a pre-assembled combination of all three layers, see [../combos/](../combos/).
