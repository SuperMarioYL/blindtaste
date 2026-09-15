"""个人选型报告（m2 ``m2_score_retest_reliability`` / m3 发布套件）——文档化占位。

v0.1（m1）尚未生成报告；本模块固定报告的输入契约与输出形态，使 m1 落盘
的数据（``battery.json`` + ``votes.jsonl``）就是 m2 报告的全部输入：

- ``per_task_winrate``     —— scoring.kind_winrates（m1 已实现）
- ``personal_ranking``     —— scoring.bradley_terry（m2）
- ``retest_agreement``     —— scoring.retest_agreement（m2，个人信度分）
- ``noise_tasks``          —— scoring.noise_tasks（m2，一致率 < 60% 的任务类）
- ``index_disagreement``   —— 与聚合榜单快照的分歧表（m2，快照见
  ``data/aggregate_index_snapshot.json``）

当前版本调用 :func:`render_markdown` / :func:`render_html` 会抛出
:class:`~blindtaste.scoring.MilestoneNotImplemented`。
"""

from __future__ import annotations

import json
from importlib import resources

from .intake import Battery
from .scoring import MilestoneNotImplemented, Vote


def load_index_snapshot() -> dict:
    """读取打包的聚合榜单快照。

    快照的分数字段为 null 表示「尚未人工抄录」：BlindTaste 不抓取任何
    榜单数据，分歧表只在用户从公开榜单页抄录当期数值后才有意义。
    """
    text = (
        resources.files("blindtaste") / "data" / "aggregate_index_snapshot.json"
    ).read_text(encoding="utf-8")
    return json.loads(text)


def snapshot_is_filled(snapshot: dict) -> bool:
    """快照是否已抄录全部模型的榜单分数。"""
    return all(
        entry.get("index_score") is not None
        for entry in snapshot.get("models", {}).values()
    )


def render_markdown(
    battery: Battery, votes: list[Vote], snapshot: dict | None = None
) -> str:
    """渲染 report.md：个人排名、每类任务冠军、信度分、噪声任务、分歧表。

    m2 交付；v0.1 调用直接抛出 :class:`MilestoneNotImplemented`。
    """
    raise MilestoneNotImplemented(
        "report.md 导出在 m2（blindtaste report）交付；"
        "v0.1 的 report 命令只展示当前票面统计与进度。"
    )


def render_html(
    battery: Battery, votes: list[Vote], snapshot: dict | None = None
) -> str:
    """渲染 report.html：可截图分享的三格报告卡片（排名/信度分/分歧表）。

    m2 交付；v0.1 调用直接抛出 :class:`MilestoneNotImplemented`。
    """
    raise MilestoneNotImplemented(
        "report.html 导出在 m2（blindtaste report）交付。"
    )
