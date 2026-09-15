"""票仓统计。

m1（本文件已实现）：胜负平统计与每类任务的胜率——run/report 的当前票数
即由此而来。

m2（``m2_score_retest_reliability``，未实现）：Bradley-Terry 个人排名、
重测一致率（个人信度分）、噪声任务判定。票仓 ``votes.jsonl`` 已经携带
这些统计需要的全部字段（round、blind_order、models、winner），m2 不需要
改 m1 的数据格式。
"""

from __future__ import annotations

from dataclasses import dataclass

from .session import Vote

#: 噪声任务判定阈值：重测一致率低于该值的任务类记为噪声（m2 使用）。
NOISE_TASK_THRESHOLD = 0.6


class MilestoneNotImplemented(NotImplementedError):
    """该能力属于后续里程碑（m2/m3），当前版本明确不提供。"""


@dataclass
class ModelTally:
    """一个模型（或某任务类下的一个模型）的票面统计。"""

    model_id: str
    wins: int = 0
    ties: int = 0
    losses: int = 0

    @property
    def total(self) -> int:
        return self.wins + self.ties + self.losses

    @property
    def winrate(self) -> float:
        """胜率 =（胜 + 0.5×平）/ 出场次数；平票记半胜。"""
        if self.total == 0:
            return 0.0
        return (self.wins + 0.5 * self.ties) / self.total


def _vote_edges(vote: Vote) -> list[tuple[str, str, str]]:
    """一张选票拆成 (model_id, wins_delta, ties_delta) 计数增量。"""
    if vote.winner is None:
        return [
            (vote.models[side], "ties", 1) for side in ("a", "b")
        ]
    loser = (
        vote.models["b"] if vote.winner == vote.models["a"] else vote.models["a"]
    )
    return [(vote.winner, "wins", 1), (loser, "losses", 1)]


def tally_votes(votes: list[Vote]) -> dict[str, ModelTally]:
    """按模型聚合整轮选票。"""
    tallies: dict[str, ModelTally] = {}
    for vote in votes:
        for model, field, delta in _vote_edges(vote):
            tally = tallies.setdefault(model, ModelTally(model))
            setattr(tally, field, getattr(tally, field) + delta)
    return tallies


def kind_winrates(votes: list[Vote]) -> dict[tuple[str, str], ModelTally]:
    """按（任务类, 模型）聚合选票：报告「每类任务冠军」的数据底座。"""
    grouped: dict[tuple[str, str], ModelTally] = {}
    for vote in votes:
        for model, field, delta in _vote_edges(vote):
            key = (vote.task_kind, model)
            tally = grouped.setdefault(key, ModelTally(model))
            setattr(tally, field, getattr(tally, field) + delta)
    return grouped


def bradley_terry(votes: list[Vote]) -> list[tuple[str, float]]:
    """Bradley-Terry 个人排名：把两两胜负聚成带强度的个人排名。

    m2 交付。实现将基于票仓中的 (winner, loser) 对做迭代比例拟合，
    平票按半胜计入双方；当前调用直接抛出 :class:`MilestoneNotImplemented`。
    """
    raise MilestoneNotImplemented(
        "Bradley-Terry 个人排名在 m2（blindtaste retest + report）交付；"
        "v0.1 先用 tally_votes/kind_winrates 查看票面统计。"
    )


def retest_agreement(votes: list[Vote]) -> float:
    """重测一致率：同 trial 第 1、2 轮选择的一致比例，即个人信度分。

    m2 交付。重测对从首轮随机抽样（battery.retest_fraction，默认 0.3）
    且盲序翻转；一致率按「解析到同一胜者」判定，平票算一致。
    """
    raise MilestoneNotImplemented(
        "重测一致率（个人信度分）在 m2（blindtaste retest）交付。"
    )


def noise_tasks(votes: list[Vote]) -> list[str]:
    """噪声任务：重测一致率低于 NOISE_TASK_THRESHOLD 的任务类。

    m2 交付。一致率 < 60% 意味着该任务上偏好肉眼级不稳定，报告会明确
    标注「此处排名不可信」而不是给出一个假精确的数字。
    """
    raise MilestoneNotImplemented(
        "噪声任务判定在 m2 交付（依赖 retest_agreement）。"
    )
