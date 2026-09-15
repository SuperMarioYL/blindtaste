**English** | [简体中文](./README.md)

<div align="center">

# BlindTaste

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://readme-typing-svg.demolab.com/?font=JetBrains+Mono&weight=600&size=22&pause=1400&color=E1E656&center=true&vCenter=true&random=false&width=640&lines=Leaderboards+can+be+farmed.+Your+taste+cannot.;Your+recurring+tasks%2C+packed+into+a+10-minute+blind+test;Anonymous+A%2FB+voting+%C2%B7+resumable+vote+vault">
  <img src="https://readme-typing-svg.demolab.com/?font=JetBrains+Mono&weight=600&size=22&pause=1400&color=77792D&center=true&vCenter=true&random=false&width=640&lines=Leaderboards+can+be+farmed.+Your+taste+cannot.;Your+recurring+tasks%2C+packed+into+a+10-minute+blind+test;Anonymous+A%2FB+voting+%C2%B7+resumable+vote+vault" alt="Leaderboards can be farmed. Your taste cannot. Your recurring tasks, packed into a 10-minute blind test. Anonymous A/B voting, resumable vote vault.">
</picture>

**Blind-test CN LLMs on your own tasks — resume edits, weekly reports, deck outlines, translation — with anonymous pairwise voting, and see your stable preference before picking a model.**

<p>
  <img src="https://img.shields.io/badge/version-0.1.0-blue" alt="version 0.1.0">
  <img src="https://img.shields.io/badge/python-3.12+-3776AB" alt="python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
  <img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/blindtaste/ci.yml?branch=main&label=ci" alt="ci status">
</p>

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="assets/presentation/hero-static-dark.svg">
  <source media="(prefers-reduced-motion: reduce)" srcset="assets/presentation/hero-static-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/hero-dark.svg">
  <img src="assets/presentation/hero-light.svg" alt="BlindTaste brand hero: particles converging into 'your taste' — a personal blind test distills scattered tasks into a stable preference" width="720">
</picture>

</div>

## Why it exists

Every CN flagship is free and the rotation is monthly, so "which one writes my weekly report better" needs re-answering every drop. All three default paths are unreliable:

- **Aggregate boards.** Indices like Artificial Analysis's Intelligence Index can be farmed — the private eval swapped in with the v4.3 update drew farming accusations within days — and they never answer which one edits *your* resume better anyway.
- **LLM judges.** Judges agreeing with each other is not correctness (a public methodological critique, not a conspiracy theory), and whoever pays the judge is its own problem.
- **Eyeballing two tabs.** Pasting one prompt into two apps is a single trial — display order, mood and the previous round are each enough to flip your verdict.

BlindTaste brings the **anonymous pairwise tasting** mechanism proven by Chatbot Arena into your terminal, changing exactly one thing: your votes do not feed a population Elo, they feed your own vault. Eight Chinese questionnaire questions pin down your recurring tasks into a battery; every pair shows only anonymous A/B, models are revealed after you vote; from m2 a random retest (blind order flipped) scores your preference with a **test-retest agreement** — a personal reliability score. It will likely disagree with the Intelligence Index, which is precisely the point.

## Run it in 10 minutes

Requires Python 3.12+ ([uv](https://docs.astral.sh/uv/) or pip):

```bash
git clone https://github.com/SuperMarioYL/blindtaste.git
cd blindtaste
uv tool install .        # or: pip install -e .
```

**Step 1 — build the battery (~60 s)**

```bash
blindtaste init
```

Eight Chinese questions: pick your recurring task kinds (resume edits / weekly reports / deck outlines / translation), their scenarios, 1-2 tasks per kind, optionally 0-2 custom tasks, then 3 models. The result is a 6-10 task battery.

**Step 2 — paste keys (~60 s)**

Put 1-2 API keys into `~/.blindtaste/keys.env`:

```bash
ZHIPU_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-yyy
```

Zhipu's `glm-4-flash-250414` has a free tier, so one key is enough to run the whole flow; see [Model integrations](#model-integrations) for every endpoint.

**Step 3 — taste (~10 min)**

```bash
blindtaste run
```

Each pair shows the task and two anonymous answers side by side; vote with `a` / `b` / `tie`, and the models behind A/B are revealed immediately after. About 15 pairs; Ctrl-C anytime, re-running resumes exactly where you stopped. Want the interaction without keys first: `blindtaste run --demo --limit 2`.

> v0.1 (m1) ends here: `blindtaste retest` (random retest, flipped blind order, agreement score) and `blindtaste report` (reliability-scored personal report, md/html) land in m2; the current `report` command shows battery, round-1 progress and the vote tally.

## Recorded demo

Real terminal capture (replayable commands and output in [docs/demo-results.json](docs/demo-results.json)): `init` builds the battery → `run --demo` anonymous tasting → resume → `report` shows progress. The recording uses the `--demo` offline adapter — no API calls, no keys — while the voting interaction, vote vault and resume path are all real code.

<img src="docs/demo/battery-run.gif" width="860" alt="Terminal recording: blindtaste init builds the task battery, blindtaste run --demo votes on anonymous A/B pairs and reveals the models, blindtaste report shows progress and tally">

For your own version, replay the commands in [docs/demo-results.json](docs/demo-results.json); [docs/demo.tape](docs/demo.tape) is the equivalent vhs script.

## How it works

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/process-mobile-light.svg">
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="assets/presentation/process-static-dark.svg">
  <source media="(prefers-reduced-motion: reduce)" srcset="assets/presentation/process-static-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/process-dark.svg">
  <img src="assets/presentation/process-light.svg" alt="Tasting flow: init builds the battery, run tastes anonymously, votes hit disk immediately, resume and reveal" width="860">
</picture>

Three invariants run through all of it:

1. **The ballot shows only anonymous A/B.** The mapping from display side to real model is decided by the blind order (`blind_order`) and revealed only after you vote — preference forms before branding.
2. **The vault is append-only.** Every vote is written immediately to `votes.jsonl` (self-describing: task, model mapping, blind order, pick, think time), deduped by `trial_id`; Ctrl-C and re-run picks up at the breakpoint.
3. **Trials derive deterministically from the battery fingerprint.** The same tasks and models always produce the same pairs — across reinstalls, re-runs and machines; answer caching is keyed by (mode, model, task), so the same task never burns the API twice.

## Architecture

A single-process Python CLI: no server, no database, all state in a local directory (default `~/.blindtaste/`):

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="assets/presentation/architecture-static-dark.svg">
  <source media="(prefers-reduced-motion: reduce)" srcset="assets/presentation/architecture-static-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/architecture-dark.svg">
  <img src="assets/presentation/architecture-light.svg" alt="Architecture blueprint: data flow across cli, intake, session, providers, scoring and report, with battery and votes as real on-disk artifacts" width="860">
</picture>

| Module | Responsibility |
| --- | --- |
| `cli.py` | typer entry: init / run / retest / report |
| `intake.py` | questionnaire → battery; `--tasks` seed mode; battery fingerprint |
| `providers.py` | model registry + OpenAI-compatible adapters behind one `ChatAdapter` interface; `--demo` offline adapter |
| `session.py` | tasting scheduler: fingerprint-derived trials, blind order, vote vault, answer cache |
| `scoring.py` | vote tally (wins/ties/losses, per-kind winrates); m2: BT ranking, retest agreement, noise tasks |
| `report.py` | m2 report outlet; aggregate index snapshot loading (`data/aggregate_index_snapshot.json`) |

Task content (questions and the four kind templates) lives in [`src/blindtaste/templates/zh_tasks.toml`](src/blindtaste/templates/zh_tasks.toml) — rewording never touches code.

## Usage

```bash
blindtaste init                                        # questionnaire -> battery
blindtaste init --tasks examples/tasks.example.toml   # seed mode: skip the questionnaire
blindtaste run                                         # tasting (~15 pairs, resumable)
blindtaste run --demo --limit 2                        # offline demo: simulated answers, no API
blindtaste run --models glm-4-flash-250414,kimi-k3     # override models for this run
blindtaste retest                                      # (m2) random retest, flipped order, reliability
blindtaste report                                      # (m2 placeholder) progress and tally for now
```

| State file | Contents |
| --- | --- |
| `~/.blindtaste/battery.json` | the battery: tasks, models, retest_fraction |
| `~/.blindtaste/votes.jsonl` | append-only vote vault — the full input of the m2 report |
| `~/.blindtaste/keys.env` | API keys (`KEY=VALUE` per line, `#` comments) |
| `~/.blindtaste/cache/answers/` | answer cache (live and demo keyed separately) |

Override the state directory with `--home` or `BLINDTASTE_HOME` — handy for keeping multiple batteries apart.

## Model integrations

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="assets/presentation/integrations-static-dark.svg">
  <source media="(prefers-reduced-motion: reduce)" srcset="assets/presentation/integrations-static-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/integrations-dark.svg">
  <img src="assets/presentation/integrations-light.svg" alt="Model integrations: five official OpenAI-compatible endpoints plus the offline demo adapter, unified behind ChatAdapter" width="860">
</picture>

Only official OpenAI-compatible endpoints — no browser automation, no scraping:

| Model | Provider | Endpoint | Key variable | Note |
| --- | --- | --- | --- | --- |
| `glm-4-flash-250414` | Zhipu | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPU_API_KEY` | free tier |
| `deepseek-flash` | DeepSeek | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | pay per token, no free tier |
| `qwen3.7-plus` | Alibaba Bailian (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` | compatible mode |
| `kimi-k3` | Kimi | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` | |
| `doubao-pro-32k` | Volcengine Ark (Doubao) | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_KEY` | **unverified** compatibility, best-effort |

When keys are missing, `run` lists the missing variables and the `keys.env` format before exiting. Doubao (Ark) OpenAI compatibility has never been verified against a live key, so it carries an explicit unverified flag — configured, it still participates only as best-effort and cannot break the rest of the battery.

## Capabilities and limits

| Capability | v0.1 (this release) | m2 (planned) |
| --- | :---: | :---: |
| Questionnaire-built task battery (4 kinds + custom) | ✓ | |
| Anonymous A/B tasting + post-vote reveal | ✓ | |
| Append-only vote vault with resume | ✓ | |
| Offline demo mode (`--demo`) | ✓ | |
| Retest (random sample + flipped blind order) | — | ✓ |
| Test-retest agreement score / noise-task warnings | — | ✓ |
| Bradley-Terry personal ranking | — | ✓ |
| Report export md/html + index disagreement table | — | ✓ |

Explicit limits:

- `--demo` answers are deterministic simulations and represent no real model.
- The aggregate index snapshot (`src/blindtaste/data/aggregate_index_snapshot.json`) has null scores (not transcribed): the disagreement table lands in m2 and only means anything after you transcribe current numbers from a public board by hand — BlindTaste scrapes nothing.
- Tasting requires official API keys; this repository provides and proxies none.

## Pricing

The tool monetizes reports and team services, **never model rankings** — commercializing rankings is exactly the trust collapse aggregate boards keep walking into.

| Stage | Offering | Price |
| --- | --- | --- |
| **v0.1 (now)** | Personal CLI (this repo, MIT) | free |
| **v0.1 (now)** | Team blind-tasting pilot: a 10-30 person team's real tasks built into a battery, 5-model tasting, delivered team report and decision memo, run by us (keys on us; no payment flow inside the product, settled via QR code) | **¥1,980 / pilot** |
| v0.2+ (planned) | Hosted no-key web version, per-report | ¥9.9 / report |
| v0.2+ (planned) | Team edition: shared battery + team report | ¥39 / seat / month |

Pilot note: the v0.1 CLI already covers battery building and tasting collection; the pilot's aggregate report is currently assembled by us manually and becomes fully tool-based once the m2 auto-report lands. The personal CLI stays open source — the two do not conflict.

## Roadmap

- [x] **m1 blind battery** (this release): init questionnaire + run anonymous tasting + resumable vote vault + offline demo
- [ ] **m2 retest and reliability**: `retest` random retest (flipped blind order), agreement score, noise-task warnings, `report` md/html export, disagreement table vs aggregate boards
- [ ] **m3 report kit**: seed report "30 real workplace tasks, blind-tested: personal ranking and three disagreements with the Intelligence Index", Gitee mirror, PyPI release (`uvx blindtaste` one-liner)

## FAQ

**Why no LLM judge?** The votes must be cast by the human running the battery — that is the essential difference from farmable leaderboards: judges echoing each other is not correctness, and your ballot cannot be farmed. v0.1 explicitly excludes auto-judging.

**Fifteen pairs — is that enough for a ranking?** Each task kind gets a winrate, not a single total; from m2, kinds with agreement below 60% are flagged as noise tasks — the report declares where it cannot be trusted, which is exactly what aggregate boards don't do.

**Isn't this a single-player Chatbot Arena?** Arena feeds your prompt into a population Elo; here the votes feed only your own report, plus resume support and (in m2) a retest reliability score. Same mechanism, different question.

## Development

```bash
uv venv && uv pip install -e ".[test]"
pytest                      # 26 tests, model calls fully mocked — no network, no keys
```

Demo assets (SVG groups and the terminal GIF) are generated by [docs/render_presentation.py](docs/render_presentation.py) and [docs/demo.tape](docs/demo.tape); the palette comes from the renderer (`web/palette.json`).

---

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
