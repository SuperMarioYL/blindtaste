"""--demo 模拟票不能混进真实盲测（v0.3.0 回归测试）。

缺陷（v0.2.0）：Vote 没有 mode 字段，演示票与真实票共用 votes.jsonl；
真实 run 把演示票当成「已投票」跳过，report 也把模拟回答算成用户偏好。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from blindtaste import cli
from blindtaste.providers import MODELS, DemoAdapter
from blindtaste.session import SessionStore, home_dir

runner = CliRunner()

INIT_THREE = "1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n"


@pytest.fixture()
def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setenv("BLINDTASTE_HOME", str(tmp_path / "home"))
    return SessionStore(home_dir())


@pytest.fixture()
def live_adapters(monkeypatch) -> None:
    """live 语义（demo=False）但用离线适配器，避免测试触网。"""

    def fake_build(model_ids, keys, *, demo: bool = False):
        return {model_id: DemoAdapter(MODELS[model_id]) for model_id in model_ids}

    monkeypatch.setattr(cli, "build_adapters", fake_build)


def _init(store: SessionStore) -> None:
    result = runner.invoke(cli.app, ["init"], input=INIT_THREE)
    assert result.exit_code == 0, result.output
    assert store.load_battery() is not None


def test_live_run_reasks_pairs_voted_in_demo(store, live_adapters) -> None:
    """演示票不算完成：真实 run 会重新问同一对，票仓保留两种模式各一张。"""
    _init(store)
    demo = runner.invoke(cli.app, ["run", "--demo", "--limit", "2"], input="a\nb\n")
    assert demo.exit_code == 0, demo.output
    demo_votes = store.load_votes()
    assert [v.mode for v in demo_votes] == ["demo", "demo"]

    live = runner.invoke(cli.app, ["run", "--limit", "2"], input="a\nb\n")
    assert live.exit_code == 0, live.output

    votes = store.load_votes()
    assert [v.mode for v in votes] == ["demo", "demo", "live", "live"]
    demo_ids = {v.trial_id for v in votes if v.mode == "demo"}
    live_ids = {v.trial_id for v in votes if v.mode == "live"}
    assert demo_ids == live_ids, "同一批 trial 必须能被真实运行重新提问"

    # 真实 run 的总结只统计 live 票，并说明演示票未计入。
    assert "另有 2 张 --demo 模拟票不计入本次统计" in live.output


def test_report_ignores_demo_votes(store) -> None:
    """只有演示票时，report 的真实进度是 0，并说明演示票未计入。"""
    _init(store)
    assert runner.invoke(
        cli.app, ["run", "--demo", "--limit", "2"], input="a\nb\n"
    ).exit_code == 0

    result = runner.invoke(cli.app, ["report"])

    assert result.exit_code == 0, result.output
    assert "首轮进度 0 对" in result.output
    assert "另有 2 张 --demo 模拟票不计入本次统计" in result.output
    assert "第 1 轮盲测全部完成" not in result.output


def test_retest_accepts_live_votes(store, live_adapters) -> None:
    """有真实票时 retest 正常进入 m2 占位提示，不因筛选条件过严而误报无记录。"""
    _init(store)
    assert runner.invoke(
        cli.app, ["run", "--limit", "1"], input="a\n"
    ).exit_code == 0

    result = runner.invoke(cli.app, ["retest"])

    assert result.exit_code == 0, result.output
    assert "m2" in result.output


def test_legacy_vote_without_mode_is_live(store, live_adapters) -> None:
    """v0.2 的旧票仓没有 mode 字段：必须按 live 读取，而不是校验失败。"""
    _init(store)
    assert runner.invoke(
        cli.app, ["run", "--limit", "1"], input="a\n"
    ).exit_code == 0

    vote = store.load_votes()[0]
    legacy = {k: v for k, v in vote.model_dump().items() if k != "mode"}
    store.votes_path.write_text(
        json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert [v.mode for v in store.load_votes()] == ["live"]
