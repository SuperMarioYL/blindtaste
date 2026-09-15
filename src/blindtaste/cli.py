"""blindtaste 命令行入口。

命令一览（v0.1 = m1）：

- ``init``    问卷生成任务电池（或 ``--tasks`` 种子文件直建）
- ``run``     终端盲测：匿名 A/B 投票、票仓落盘、断点续跑
- ``retest``  （m2）随机重测、盲序翻转、重测一致率信度分 —— 占位
- ``report``  （m2）个人选型报告 md/html —— 占位，当前展示票面统计
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from . import __version__
from .intake import Battery, run_questionnaire, run_seed_intake
from .providers import MODELS, ProviderError, build_adapters, effective_keys
from .scoring import tally_votes
from .session import (
    ROUND1_MAX_PAIRS,
    SessionStore,
    Trial,
    Vote,
    home_dir,
    round1_trials,
    run_session,
)

app = typer.Typer(
    help="用你自己的任务盲测国产大模型：榜单会被刷分，你的口味不会。",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def _root(
    version: bool = typer.Option(
        False, "--version", is_eager=True, help="显示版本号并退出。"
    ),
) -> None:
    if version:
        console.print(f"blindtaste {__version__}")
        raise typer.Exit()


def _store_for(home: Path | None) -> SessionStore:
    return SessionStore(home_dir(home))


def _print_battery_summary(battery: Battery) -> None:
    kinds: dict[str, int] = {}
    for task in battery.tasks:
        kinds[task.kind] = kinds.get(task.kind, 0) + 1
    console.print(
        f"\n[green]✓ 电池已生成[/]：{len(battery.tasks)} 条任务（"
        + "、".join(f"{kind} × {count}" for kind, count in kinds.items())
        + f"），参测模型 {len(battery.models)} 家。"
    )
    console.print(
        f"首轮盲测约 {min(ROUND1_MAX_PAIRS, len(battery.tasks) * len(battery.models) * (len(battery.models) - 1) // 2)} 对。"
    )


@app.command()
def init(
    tasks: Path = typer.Option(
        None,
        "--tasks",
        exists=True,
        dir_okay=False,
        readable=True,
        help="跳过问卷：从任务文件（[[task]] kind/prompt）直接建电池。",
    ),
    home: Path = typer.Option(
        None, "--home", help="状态目录（默认 ~/.blindtaste）。"
    ),
) -> None:
    """问卷生成任务电池：8 道中文选择题 → 6-10 条你的高频任务。"""
    store = _store_for(home)
    try:
        battery = run_seed_intake(console, tasks) if tasks else run_questionnaire(console)
    except EOFError:
        console.print("[red]输入提前结束，电池未保存。[/]")
        raise typer.Exit(code=1)
    store.save_battery(battery)
    _print_battery_summary(battery)
    store_home = store.home
    console.print(
        f"\n下一步：把 1-2 个 API key 粘贴到 [cyan]{store_home / 'keys.env'}[/]，例如\n"
        "  ZHIPU_API_KEY=sk-xxx\n"
        "智谱 glm-4-flash-250414 有免费档；然后运行 [bold]blindtaste run[/]。"
        "不配 key 也可以先 [bold]blindtaste run --demo[/] 体验盲测交互。"
    )


def _resolve_models(battery: Battery, models_override: str | None) -> Battery:
    """--models 覆盖本次运行的参测模型（不回写电池）。"""
    if not models_override:
        return battery
    ids = [part.strip() for part in models_override.replace("，", ",").split(",") if part.strip()]
    unknown = [i for i in ids if i not in MODELS]
    if unknown:
        console.print(
            f"[red]未知模型：{', '.join(unknown)}[/]；可选：{', '.join(MODELS)}"
        )
        raise typer.Exit(code=1)
    return battery.model_copy(
        update={"models": [MODELS[i] for i in ids]}
    )


def _interactive_vote(trial: Trial, answer_a: str, answer_b: str) -> tuple[str, int]:
    started = time.perf_counter()
    pick = Prompt.ask(
        "[bold]哪份回答更好？[/]", choices=["a", "b", "tie"], console=console
    )
    return pick, int((time.perf_counter() - started) * 1000)


def _print_run_summary(
    *,
    completed: int,
    total: int,
    voted_now: int,
    votes: list[Vote],
    battery: Battery,
) -> None:
    label_by_id = {m.id: m.label for m in battery.models}
    if voted_now:
        console.print(
            f"\n[bold]本轮完成[/]：新投 {voted_now} 对，累计 {completed}/{total}。"
        )
    if completed < total:
        console.print(
            f"随时 Ctrl-C 中断，重跑 [bold]blindtaste run[/] 会从 "
            f"{completed}/{total} 继续。"
        )
        return
    console.print("\n[bold]第 1 轮盲测全部完成[/] —— 当前票面统计：")
    table = Table(show_header=True, header_style="bold")
    for column in ("模型", "胜", "平", "负", "胜率"):
        table.add_column(column, justify="left" if column == "模型" else "right")
    for model_id, tally in sorted(
        tally_votes([v for v in votes if v.round == 1]).items(),
        key=lambda item: item[1].winrate,
        reverse=True,
    ):
        table.add_row(
            label_by_id.get(model_id, model_id),
            str(tally.wins),
            str(tally.ties),
            str(tally.losses),
            f"{tally.winrate:.0%}",
        )
    console.print(table)
    console.print(
        "[dim]以上是票面计数；带重测信度评分的完整排名与个人选型报告在 m2"
        "（blindtaste retest / report）交付。[/]"
    )


@app.command()
def run(
    home: Path = typer.Option(
        None, "--home", help="状态目录（默认 ~/.blindtaste）。"
    ),
    models: str = typer.Option(
        None, "--models", help="覆盖本次参测模型（逗号分隔 id），不回写电池。"
    ),
    limit: int = typer.Option(
        None, "--limit", min=1, help="本轮最多新投多少对（体验/演示用）。"
    ),
    demo: bool = typer.Option(
        False, "--demo", help="演示模式：内置模拟回答，不调用任何 API。"
    ),
) -> None:
    """终端盲测：逐对匿名 A/B 投票；Ctrl-C 中断后重跑自动续上。"""
    store = _store_for(home)
    battery = store.load_battery()
    if battery is None:
        console.print(
            "[red]还没有任务电池。[/]先运行 [bold]blindtaste init[/] 生成。"
        )
        raise typer.Exit(code=1)
    battery = _resolve_models(battery, models)
    try:
        adapters = build_adapters(
            [m.id for m in battery.models],
            effective_keys(store.home / "keys.env"),
            demo=demo,
        )
    except ProviderError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    try:
        result = run_session(
            battery,
            adapters,
            store,
            console,
            _interactive_vote,
            limit=limit,
            demo=demo,
        )
    except (KeyboardInterrupt, EOFError):
        voted = store.load_votes()
        done = sum(1 for v in voted if v.round == 1)
        console.print(
            f"\n[yellow]已中断，进度已保存：{done} 对已投票，"
            "重跑 blindtaste run 自动续上。[/]"
        )
        raise typer.Exit()
    _print_run_summary(
        completed=result.completed,
        total=result.total_trials,
        voted_now=len(result.voted),
        votes=store.load_votes(),
        battery=battery,
    )


@app.command()
def retest(
    home: Path = typer.Option(
        None, "--home", help="状态目录（默认 ~/.blindtaste）。"
    ),
) -> None:
    """（m2）随机重测：盲序翻转 + 重测一致率（个人信度分）。"""
    store = _store_for(home)
    battery = store.load_battery()
    votes = store.load_votes()
    done = sum(1 for v in votes if v.round == 1)
    if battery is None or done == 0:
        console.print(
            "[red]还没有首轮盲测记录。[/]先运行 [bold]blindtaste init[/] 和 "
            "[bold]blindtaste run[/]。"
        )
        raise typer.Exit(code=1)
    console.print(
        f"当前进度：首轮 {done} 对已投票（电池 {len(battery.tasks)} 条任务、"
        f"{len(battery.models)} 家模型）。\n\n"
        "[bold]retest 属于 m2 里程碑，v0.1 尚未实现[/]：将从首轮随机抽约 "
        f"{battery.retest_fraction:.0%} 的对重测并翻转盲序，输出重测一致率"
        "（个人信度分）与噪声任务警示。票仓格式已按 m2 预留 round 字段，"
        "升级后无需重跑首轮。"
    )


@app.command()
def report(
    home: Path = typer.Option(
        None, "--home", help="状态目录（默认 ~/.blindtaste）。"
    ),
) -> None:
    """（m2）个人选型报告：排名、信度分、噪声任务、与聚合榜单的分歧表。"""
    from .report import load_index_snapshot, snapshot_is_filled

    store = _store_for(home)
    battery = store.load_battery()
    if battery is None:
        console.print(
            "[red]还没有任务电池。[/]先运行 [bold]blindtaste init[/]。"
        )
        raise typer.Exit(code=1)
    votes = store.load_votes()
    done = sum(1 for v in votes if v.round == 1)
    console.print(
        f"电池：{len(battery.tasks)} 条任务 × {len(battery.models)} 家模型；"
        f"首轮进度 {done} 对。"
    )
    if done:
        _print_run_summary(
            completed=done,
            total=len(round1_trials(battery)),
            voted_now=0,
            votes=votes,
            battery=battery,
        )
    snapshot = load_index_snapshot()
    status = "已抄录" if snapshot_is_filled(snapshot) else "未抄录（分歧表待 m2）"
    console.print(f"聚合榜单快照：{status}。")
    console.print(
        "\n[bold]完整个人选型报告属 m2 里程碑，v0.1 尚未实现[/]：BT 个人排名、"
        "每类任务冠军、重测一致率信度分、噪声任务警示，以及与 "
        "Artificial Analysis 的 Intelligence Index 式聚合榜单的分歧表，"
        "将导出为 report.md / report.html。"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
