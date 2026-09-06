# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to over complication, and clarifying questions come before implementation rather than after mistakes.

## Skill Usage Map for This Project

- Fetching third-party API/SDK docs (NeatLogs, Smallest.ai, TensorMux/GLM) → use the context7 MCP (`resolve-library-id` then `query-docs`) before writing integration code, since these are fast-moving/less-common APIs not in training data.
- Verifying a frontend/UI implementation actually renders and behaves correctly → use the chrome-devtools MCP / browser tooling to load the running app and visually confirm, not just type-check.
- Building any new feature (voice agent integration, exception-resolution UI, etc.) → use superpowers:brainstorming before implementation, superpowers:writing-plans for multi-step work, superpowers:test-driven-development while implementing, superpowers:systematic-debugging when something breaks.
- Any data visualization (dashboards, exception charts) → use the dataviz skill for chart/color/layout consistency.
- Any UI/UX-heavy screen → use the ui-ux-pro-max skill (design system, accessibility, layout conventions) if available in this environment.
- Long-running/background research or repo memory recall → use ponytail / context-mode skills per their own trigger descriptions.
