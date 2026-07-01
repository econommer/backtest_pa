# Installing Superpowers (Claude Code plugin)

[Superpowers](https://github.com/obra/superpowers) by Jesse Vincent (obra) is a **Claude Code plugin** — a software-development methodology delivered as auto-triggering skills (brainstorming → writing-plans → TDD → subagent-driven-development → code-review → finishing-a-branch).

> It is meant to be installed as a **plugin in your coding agent**, not vendored file-by-file into a project. Installed properly, its skills trigger automatically. Run the commands below **inside Claude Code** (opened on this `code/` folder, or anywhere — plugins install at the agent level).

## Recommended: official marketplace (one command)
```
/plugin install superpowers@claude-plugins-official
```

## Alternative: Superpowers marketplace (also gets related plugins)
```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

After install, just start working — Superpowers checks for a relevant skill before each task automatically. Try: *"let's build the M0 interfaces for the backtesting framework"* and it should kick off its brainstorming → plan flow.

## Notes
- This is the right surface: you'll be doing the code work in **Claude Code**, where `/plugin` works and the skills auto-trigger.
- (Cowork could not `git clone` this from its sandbox — outbound GitHub is blocked by the proxy — so a folder-local vendored copy isn't set up here. If you ever want a manual, no-auto-trigger copy of just the `SKILL.md` files dropped into `.claude/skills/`, ask and I can best-effort fetch them via raw URLs.)
- Other agents (Codex, Cursor, Gemini, Copilot CLI) have their own install commands — see the repo README.
