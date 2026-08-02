# AGENTS.md

This repository uses multiple AI tools on purpose. Do not default to the most expensive agent.
The operating principle is: use the cheapest tool that can finish the task reliably, then escalate only when needed.

## Tool roles

### 1. Perplexity Ask via MCP
Use for:
- Internet search
- Documentation lookup
- API, release-note, and changelog lookup
- Fast factual research before code changes

Prefer Perplexity before Cursor when the task depends on current external information.
If a URL is already known, terminal retrieval may be cheaper and faster than asking an LLM to search.

### 2. Terminal tools
Use for direct retrieval and local inspection:
- `curl`, `wget`
- `grep`, `rg`, `sed`, `awk`
- local docs search, file discovery, quick text extraction

Prefer terminal tools over paid agent reasoning when the task is deterministic retrieval or filtering.

### 3. Continue + local Qwen 2.5 14B Q4
Use first for low-cost local generation:
- README drafts
- small code snippets
- boilerplate
- simple rewrites
- summarization
- isolated utility functions
- regexes and small transformations

Also usable as a **review sidekick** (`cn -p --silent`) with a tight pasted packet — see `.cursor/rules/continue-sidekick.mdc`. Limited context; not an authoritative Forge/security reviewer.

Escalate only if local output is weak, hallucinated, or needs broader repo context.

### 4. Cursor Agent
Reserve for high-value repo-aware work:
- multi-file edits
- refactors
- debugging across files
- test repair
- architecture-aware implementation
- changes that require strong editor context and direct code manipulation

Cursor is not the default search engine and not the default README writer.
Use it when codebase context materially matters.

### 5. Kilo
Use as a second pass for:
- code review
- sanity checking
- bug hunting
- regression review
- validation of Cursor output

When possible, review diffs, changed files, or a commit rather than asking for an unfocused full-project review.

## Dispatch policy

- Search -> Perplexity Ask via MCP, or terminal retrieval if the source is already known.
- Draft -> Continue with local Qwen first.
- Code -> Cursor Agent.
- Review -> Kilo checks Cursor output; optional Continue sidekick for cheap sanity passes (not the final authority).

## Cost policy

To minimize Cursor token spending:
- Do not use Cursor for broad research if Perplexity or terminal tools can handle it.
- Do not use Cursor first for READMEs, summaries, or tiny snippets.
- Ask for exact files before starting repo-aware work.
- Keep tasks narrow, file-bounded, and acceptance-criteria driven.
- Prefer phased work: research -> draft -> implement -> review.

## Execution pattern for agents

When taking a task:
1. Classify it as search, draft, code, or review.
2. Choose the cheapest matching tool first.
3. If the chosen tool is insufficient, escalate one step up.
4. Return concise outputs and concrete next actions.

## Escalation guide

- Search failed or results conflict -> use Perplexity if terminal tools were tried first, or move to Cursor only if implementation context is now needed.
- Local draft is weak -> ask Kilo for a quality pass or move to Cursor if repo context matters.
- Code task grows from one file to many files -> move from Continue/local to Cursor Agent.
- Cursor implementation completed -> send to Kilo for review when available.

## Expected agent behavior

Agents should avoid expensive exploration.
Agents should ask clarifying questions before scanning the entire repository.
Agents should prefer editing existing files over generating broad new scaffolding.
Agents should explicitly say when a cheaper tool would be more appropriate.