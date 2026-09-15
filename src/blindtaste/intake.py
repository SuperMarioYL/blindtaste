"""问卷 → 任务电池（Battery）。

任务内容（问题与四类模板）在 ``templates/zh_tasks.toml``，本模块只负责
交互与装配：8 道中文选择题（4 类任务筛选 + 4 个场景 + 密度 + 自定义 +
模型选择）产出 6-10 条任务的电池。

纯装配逻辑（:func:`build_battery`、:func:`battery_from_seed_file`）与终端
交互（:func:`run_questionnaire`）分开，前者供测试与种子模式直接调用。
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .providers import MODELS, ModelRef

BATTERY_SCHEMA_VERSION = "1"
CUSTOM_TASK_LIMIT = 2
MIN_MODELS = 2


class TaskItem(BaseModel):
    """一条盲测任务：prompt 原样发给每个模型。"""

    id: str
    kind: str  # resume | weekly | ppt | translate | custom
    prompt: str
    source: str  # intake | seed


class Battery(BaseModel):
    """一次盲测的全部输入：任务电池 + 参测模型。

    ``retest_fraction`` 记录 m2 重测的抽样比例（首轮随机抽 30% 重测、
    盲序翻转），v0.1 只存储不使用。
    """

    version: str = BATTERY_SCHEMA_VERSION
    created_at: str
    retest_fraction: float = 0.3
    tasks: list[TaskItem]
    models: list[ModelRef]


def load_task_bank() -> dict[str, Any]:
    """读取内置任务题库（问卷问题 + 模板）。"""
    text = (
        resources.files("blindtaste") / "templates" / "zh_tasks.toml"
    ).read_text(encoding="utf-8")
    return tomllib.loads(text)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def battery_fingerprint(battery: Battery) -> str:
    """电池内容指纹：只看任务与模型，不看创建时间。

    trial_id 由指纹派生，因此同一份内容（无论重新 init 几次）生成同一批
    trial，票仓的断点续跑才成立。
    """
    payload = {
        "tasks": [t.model_dump() for t in battery.tasks],
        "models": [m.model_dump() for m in battery.models],
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_battery(
    *,
    kinds: list[str],
    scenes: dict[str, str],
    density: int,
    custom_prompts: list[str],
    models: list[ModelRef],
    bank: dict[str, Any] | None = None,
) -> Battery:
    """把问卷答案装配成电池。

    每类任务先取场景匹配的模板，不足 density 条时用通用兜底模板补齐；
    自定义任务追加为 ``custom`` 类。
    """
    if not kinds:
        raise ValueError("至少选择一类任务")
    if len(models) < MIN_MODELS:
        raise ValueError(f"至少选择 {MIN_MODELS} 家模型才能组成盲测对")
    if density < 1:
        raise ValueError("每类任务至少 1 条")
    bank = bank or load_task_bank()
    templates = bank["template"]
    questions = bank["question"]

    tasks: list[TaskItem] = []
    for kind in kinds:
        variants = [t for t in templates if t["kind"] == kind]
        if not variants:
            raise ValueError(f"任务题库缺少 {kind} 模板")
        scene_q = next(
            (q for q in questions if q.get("applies_to") == kind), None
        )
        chosen: list[dict[str, Any]] = []
        if scene_q:
            want = f"{scene_q['id']}={scenes.get(scene_q['id'], '')}"
            chosen = [t for t in variants if t.get("when", "") == want]
        for fallback in (
            [t for t in variants if not t.get("when", "")],
            [t for t in variants if t not in chosen],
        ):
            for template in fallback:
                if len(chosen) >= density:
                    break
                if template not in chosen:
                    chosen.append(template)
            if len(chosen) >= density:
                break
        tasks.extend(
            TaskItem(id=t["id"], kind=kind, prompt=t["prompt"], source="intake")
            for t in chosen
        )
    tasks.extend(
        TaskItem(id=f"custom-{i}", kind="custom", prompt=prompt, source="intake")
        for i, prompt in enumerate(custom_prompts[:CUSTOM_TASK_LIMIT], start=1)
    )
    return Battery(
        created_at=now_iso(), tasks=tasks, models=list(models)
    )


def battery_from_seed_file(path: Path) -> list[TaskItem]:
    """种子模式：读取 ``[[task]] kind/prompt`` 文件为任务列表。

    与问卷产出的电池共用 Trial/Vote 管线，任务 ``source`` 标记为 seed，
    供 m3 的种子报告复用。
    """
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("task", [])
    if not entries:
        raise ValueError(f"{path} 里没有 [[task]] 条目")
    tasks = []
    for i, entry in enumerate(entries, start=1):
        kind = str(entry.get("kind", "")).strip()
        prompt = str(entry.get("prompt", "")).strip()
        if kind not in {"resume", "weekly", "ppt", "translate", "custom"}:
            raise ValueError(f"{path} 第 {i} 条 task 的 kind 非法：{kind!r}")
        if not prompt:
            raise ValueError(f"{path} 第 {i} 条 task 缺少 prompt")
        tasks.append(
            TaskItem(id=f"seed-{i}", kind=kind, prompt=prompt, source="seed")
        )
    return tasks


# ---------------------------------------------------------------------------
# 终端问卷
# ---------------------------------------------------------------------------


def _numbered_options(console, options: list[dict[str, str]]) -> None:
    for i, opt in enumerate(options, start=1):
        console.print(f"  [cyan]{i}.[/] {opt['label']}")
    console.print()


def _parse_numbers(raw: str, count: int) -> list[int]:
    numbers = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= count:
            raise ValueError(f"无效编号：{part}")
        numbers.append(int(part))
    if not numbers:
        raise ValueError("至少输入一个编号")
    return numbers


def ask_single(console, question: dict[str, Any]) -> str:
    """单选题：返回选项 value。"""
    options = question["option"]
    console.print(f"\n[bold]{question['text']}[/]")
    _numbered_options(console, options)
    while True:
        try:
            raw = console.input("[?] 输入编号 > ").strip()
            numbers = _parse_numbers(raw, len(options))
        except (ValueError, EOFError) as exc:
            if isinstance(exc, EOFError):
                raise
            console.print(f"[yellow]{exc}，请重试。[/]")
            continue
        if len(numbers) != 1:
            console.print("[yellow]这是单选题，只输入一个编号。[/]")
            continue
        return options[numbers[0] - 1]["value"]


def ask_multi(
    console, question: dict[str, Any], *, min_picks: int = 1
) -> list[str]:
    """多选题：返回选项 value 列表；``default_all`` 的题空回车选全部。"""
    options = question["option"]
    console.print(f"\n[bold]{question['text']}[/]")
    _numbered_options(console, options)
    while True:
        try:
            raw = console.input("[?] 输入编号（逗号分隔） > ").strip()
            if not raw and question.get("default_all"):
                return [opt["value"] for opt in options]
            numbers = _parse_numbers(raw, len(options))
        except (ValueError, EOFError) as exc:
            if isinstance(exc, EOFError):
                raise
            console.print(f"[yellow]{exc}，请重试。[/]")
            continue
        if len(set(numbers)) < min_picks:
            console.print(f"[yellow]至少选择 {min_picks} 项。[/]")
            continue
        return [options[n - 1]["value"] for n in sorted(set(numbers))]


def ask_custom_tasks(console, limit: int = CUSTOM_TASK_LIMIT) -> list[str]:
    """自定义任务：每行一条，空行结束，最多 limit 条。"""
    console.print(
        f"\n[bold]（可选）把你自己的高频任务加进电池[/] —— "
        f"每行一条，空行结束，最多 {limit} 条。"
    )
    console.print("例如：把下面这段产品介绍改写成小红书文案：……\n")
    prompts: list[str] = []
    while len(prompts) < limit:
        line = console.input(f"[?] 任务 {len(prompts) + 1}（空行结束） > ").strip()
        if not line:
            break
        prompts.append(line)
    return prompts


def ask_models(console) -> list[ModelRef]:
    """选择参测模型：推荐 3 家，至少 2 家。"""
    refs = list(MODELS.values())
    console.print("\n[bold]选择参测模型（推荐 3 家，至少 2 家）[/]")
    for i, ref in enumerate(refs, start=1):
        note = f" · {ref.note}" if ref.note else ""
        console.print(f"  [cyan]{i}.[/] {ref.label}（{ref.id}）{note}")
    console.print()
    while True:
        try:
            raw = console.input("[?] 输入编号（逗号分隔） > ").strip()
            numbers = _parse_numbers(raw, len(refs))
        except (ValueError, EOFError) as exc:
            if isinstance(exc, EOFError):
                raise
            console.print(f"[yellow]{exc}，请重试。[/]")
            continue
        if len(set(numbers)) < MIN_MODELS:
            console.print(f"[yellow]至少选择 {MIN_MODELS} 家模型才能配对盲测。[/]")
            continue
        return [refs[n - 1] for n in sorted(set(numbers))]


def run_questionnaire(console) -> Battery:
    """完整问卷：8 道选择题（全选四类时）→ Battery。"""
    bank = load_task_bank()
    questions = {q["id"]: q for q in bank["question"]}
    console.print(
        "[bold]BlindTaste 问卷[/] —— 用 8 道选择题生成你的任务电池（约 60 秒）。\n"
        "电池 = 6-10 条你真实会做的任务，之后逐对盲测各家模型。"
    )
    kinds = ask_multi(console, questions["kinds"], min_picks=1)

    scenes: dict[str, str] = {}
    # 场景题只问选中的任务类
    scene_questions = [q for q in bank["question"] if q.get("applies_to")]
    for q in scene_questions:
        if q["applies_to"] in kinds:
            scenes[q["id"]] = ask_single(console, q)

    density = int(ask_single(console, questions["density"]))
    custom_prompts = ask_custom_tasks(console)
    models = ask_models(console)
    return build_battery(
        kinds=kinds,
        scenes=scenes,
        density=density,
        custom_prompts=custom_prompts,
        models=models,
        bank=bank,
    )


def run_seed_intake(console, tasks_path: Path) -> Battery:
    """种子模式入口：任务来自文件，只补问模型选择。"""
    tasks = battery_from_seed_file(tasks_path)
    console.print(f"已从 [cyan]{tasks_path}[/] 读取 {len(tasks)} 条种子任务。")
    models = ask_models(console)
    return Battery(created_at=now_iso(), tasks=tasks, models=models)


__all__ = [
    "Battery",
    "TaskItem",
    "ask_models",
    "battery_from_seed_file",
    "battery_fingerprint",
    "build_battery",
    "load_task_bank",
    "run_questionnaire",
    "run_seed_intake",
]
