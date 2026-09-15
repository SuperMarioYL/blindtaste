"""盲测回合调度：trial 生成、匿名 A/B 展示、票仓落盘与断点续跑。

核心不变量（来自产品定义）：

- 票面只见匿名 A/B，投票后才揭晓模型；
- trial_id 由电池内容指纹确定性派生，因此 ``run`` 中断后重跑会跳过已投
  票的对（票仓 ``votes.jsonl`` 按 trial_id 去重）；
- 盲序（blind_order）决定哪侧模型显示为 A，重测轮会翻转盲序（m2）。

回答缓存按 (mode, model, prompt) 键落盘：同一任务同一模型的回答在多个
trial 间复用，不重复烧 API。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from itertools import combinations
from pathlib import Path
from typing import Callable, Mapping

from pydantic import BaseModel, Field
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel

from .intake import Battery, TaskItem, battery_fingerprint, now_iso
from .providers import ChatAdapter

#: 首轮盲测的对数上限：约 10 分钟内可完成的量（来自产品定义）。
ROUND1_MAX_PAIRS = 15

#: 一次 trial 投票的决策：(pick, think_ms)。
VoteDecision = tuple[str, int]


class Trial(BaseModel):
    """一对盲测：task × 两个模型，外加盲序。"""

    id: str
    task_id: str
    task_kind: str
    models: tuple[str, str]  # 规范序（排序后）的两个模型 id
    blind_order: str  # "AB" | "BA"：BA 表示规范序第二个模型显示为 A


class Vote(BaseModel):
    """一张选票：自描述，m2 的统计只读票仓即可完成。

    ``models`` 记录显示侧到真实模型的映射（{"a": id, "b": id}），
    ``winner`` 是按 pick 解析后的胜者模型 id（平票为 None）。
    """

    trial_id: str
    task_id: str
    task_kind: str
    round: int  # 1 = 首轮；2 = 重测（m2）
    models: dict[str, str]
    blind_order: str
    pick: str  # "a" | "b" | "tie"
    think_ms: int = Field(ge=0)
    winner: str | None
    voted_at: str


def home_dir(override: Path | None = None) -> Path:
    """状态目录：--home > BLINDTASTE_HOME 环境变量 > ~/.blindtaste。"""
    if override is not None:
        return Path(override).expanduser()
    env = os.environ.get("BLINDTASTE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".blindtaste"


def display_models(trial: Trial) -> dict[str, str]:
    """盲序解析：返回显示侧 -> 真实模型 id。"""
    first, second = trial.models
    return {"a": second, "b": first} if trial.blind_order == "BA" else {
        "a": first,
        "b": second,
    }


def record_vote(
    trial: Trial, pick: str, think_ms: int, *, round_: int = 1
) -> Vote:
    """把 (trial, 选择) 固化成自描述选票。"""
    if pick not in {"a", "b", "tie"}:
        raise ValueError(f"非法选择：{pick!r}")
    sides = display_models(trial)
    return Vote(
        trial_id=trial.id,
        task_id=trial.task_id,
        task_kind=trial.task_kind,
        round=round_,
        models=sides,
        blind_order=trial.blind_order,
        pick=pick,
        think_ms=think_ms,
        winner=None if pick == "tie" else sides[pick],
        voted_at=now_iso(),
    )


def _trial_id(fingerprint: str, task_id: str, pair: tuple[str, str], round_: int) -> str:
    raw = f"{fingerprint}|{task_id}|{pair[0]}|{pair[1]}|r{round_}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_trial(
    fingerprint: str, task: TaskItem, pair: tuple[str, str], *, round_: int = 1
) -> Trial:
    """构建单个 trial；盲序由 trial_id 派生，确定性可重放。"""
    trial_id = _trial_id(fingerprint, task.id, pair, round_)
    blind_order = "BA" if random.Random(trial_id).random() < 0.5 else "AB"
    return Trial(
        id=trial_id,
        task_id=task.id,
        task_kind=task.kind,
        models=pair,
        blind_order=blind_order,
    )


def round1_trials(
    battery: Battery, *, max_pairs: int = ROUND1_MAX_PAIRS
) -> list[Trial]:
    """生成首轮盲测日程。

    确定性：任务序、对序、盲序全部由电池指纹播种的 RNG 决定，同一电池
    永远得到同一批 trial（断点续跑的前提）。轮转取对让每类任务先各出
    一对，再补第二对，避免某类任务被截断出局。
    """
    if len(battery.models) < 2:
        raise ValueError("电池里至少需要 2 家模型才能组成盲测对")
    fingerprint = battery_fingerprint(battery)
    rng = random.Random(fingerprint)
    task_order = list(battery.tasks)
    rng.shuffle(task_order)
    model_ids = sorted(m.id for m in battery.models)
    queues: dict[str, list[tuple[str, str]]] = {}
    for task in task_order:
        pairs = [tuple(sorted(pair)) for pair in combinations(model_ids, 2)]
        rng.shuffle(pairs)
        queues[task.id] = pairs

    trials: list[Trial] = []
    task_by_id = {t.id: t for t in battery.tasks}
    while len(trials) < max_pairs:
        progressed = False
        for task in task_order:
            if len(trials) >= max_pairs:
                break
            if queues[task.id]:
                pair = queues[task.id].pop(0)
                trials.append(make_trial(fingerprint, task_by_id[task.id], pair))
                progressed = True
        if not progressed:
            break
    return trials


class SessionStore:
    """票仓与缓存的落盘位置和读写。"""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.battery_path = self.home / "battery.json"
        self.votes_path = self.home / "votes.jsonl"
        self.cache_dir = self.home / "cache" / "answers"

    def load_battery(self) -> Battery | None:
        if not self.battery_path.is_file():
            return None
        return Battery.model_validate_json(
            self.battery_path.read_text(encoding="utf-8")
        )

    def save_battery(self, battery: Battery) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.battery_path.write_text(
            battery.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_votes(self) -> list[Vote]:
        if not self.votes_path.is_file():
            return []
        votes = []
        for lineno, line in enumerate(
            self.votes_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                votes.append(Vote.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"票仓 {self.votes_path} 第 {lineno} 行损坏：{exc}") from exc
        return votes

    def append_vote(self, vote: Vote) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        with self.votes_path.open("a", encoding="utf-8") as handle:
            handle.write(vote.model_dump_json() + "\n")

    def _cache_key(self, model_id: str, prompt: str, *, demo: bool) -> str:
        mode = "demo" if demo else "live"
        raw = f"{mode}\x00{model_id}\x00{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def load_answer(
        self, model_id: str, prompt: str, *, demo: bool
    ) -> str | None:
        path = self.cache_dir / f"{self._cache_key(model_id, prompt, demo=demo)}.json"
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return record.get("answer")

    def save_answer(
        self, model_id: str, prompt: str, answer: str, *, demo: bool
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{self._cache_key(model_id, prompt, demo=demo)}.json"
        record = {
            "model": model_id,
            "mode": "demo" if demo else "live",
            "answer": answer,
        }
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


class RunResult:
    """一次 run 的结果：本轮新投的票 + 全局进度。"""

    def __init__(self, voted: list[Vote], total_trials: int, remaining: int) -> None:
        self.voted = voted
        self.total_trials = total_trials
        self.remaining = remaining

    @property
    def completed(self) -> int:
        """首轮累计已完成的对数（含本轮之前）。"""
        return self.total_trials - self.remaining


def run_session(
    battery: Battery,
    adapters: Mapping[str, ChatAdapter],
    store: SessionStore,
    console: Console,
    vote_fn: Callable[[Trial, str, str], VoteDecision],
    *,
    limit: int | None = None,
    demo: bool = False,
    max_pairs: int = ROUND1_MAX_PAIRS,
) -> RunResult:
    """执行（或续跑）首轮盲测。

    ``vote_fn(trial, answer_a, answer_b)`` 负责提问并返回 ``(pick, think_ms)``；
    展示、缓存、落盘、揭晓都在本函数内完成，测试注入伪 vote_fn 即可全链路
    验证票仓。
    """
    trials = round1_trials(battery, max_pairs=max_pairs)
    done_ids = {v.trial_id for v in store.load_votes() if v.round == 1}
    pending = [t for t in trials if t.id not in done_ids]
    console.print(
        f"\n[bold]第 1 轮盲测[/]：共 {len(trials)} 对，"
        f"已完成 {len(trials) - len(pending)} 对，待投 {len(pending)} 对。"
    )
    if demo:
        console.print(
            "[yellow]演示模式：回答由内置模拟适配器生成，不调用任何 API，"
            "不代表真实模型表现。[/]"
        )
    if not pending:
        return RunResult([], len(trials), 0)

    task_by_id = {t.id: t for t in battery.tasks}
    label_by_id = {m.id: m.label for m in battery.models}
    to_vote = pending if limit is None else pending[:limit]
    voted: list[Vote] = []
    for index, trial in enumerate(to_vote, start=1):
        task = task_by_id[trial.task_id]
        sides = display_models(trial)
        answers = {
            side: _fetch_answer(
                store, adapters[model_id], task, demo=demo
            )
            for side, model_id in sides.items()
        }
        console.print(f"\n[bold]── 对 {index}/{len(to_vote)} · 任务 {task.id}[/]")
        console.print(
            Panel(task.prompt, title=f"任务（{task.kind}）", border_style="dim")
        )
        panels = [
            Panel(answers["a"], title="回答 A", border_style="cyan"),
            Panel(answers["b"], title="回答 B", border_style="magenta"),
        ]
        if console.width >= 90:
            console.print(Columns(panels, equal=True, expand=True))
        else:
            for panel in panels:
                console.print(panel)
        pick, think_ms = vote_fn(trial, answers["a"], answers["b"])
        vote = record_vote(trial, pick, think_ms)
        store.append_vote(vote)
        voted.append(vote)
        console.print(
            f"[green]✓ 已记录[/] 揭晓：A = {label_by_id.get(sides['a'], sides['a'])}"
            f" · B = {label_by_id.get(sides['b'], sides['b'])}"
        )
    return RunResult(voted, len(trials), len(pending) - len(voted))


def _fetch_answer(
    store: SessionStore, adapter: ChatAdapter, task: TaskItem, *, demo: bool
) -> str:
    cached = store.load_answer(adapter.model_id, task.prompt, demo=demo)
    if cached is not None:
        return cached
    answer = adapter.complete(task.prompt)
    store.save_answer(adapter.model_id, task.prompt, answer, demo=demo)
    return answer
