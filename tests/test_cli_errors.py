"""CLI 错误路径：非法输入给出干净的错误信息与退出码，而不是抛栈。

覆盖 v0.2.0 修的三类缺陷（每类都对应一条已复现的缺陷）：

- ``run --models`` 少于 2 家模型（未捕获 ValueError）或重复 id（自比自，
  票仓落一条 ``models.a == models.b`` 的无意义选票）；
- ``init --tasks`` 种子文件的 kind 非法 / prompt 缺失 / TOML 语法错误；
- 票仓 ``votes.jsonl`` 损坏（追加写被中断留下的半行）。

判定「干净退出」的方式：命令以 ``typer.Exit(1)`` 结束（CliRunner 记为
``SystemExit``），而不是让 ValueError 逃逸到调用栈外。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from blindtaste.cli import app
from blindtaste.session import SessionStore, home_dir

REPO = Path(__file__).resolve().parent.parent
runner = CliRunner()

# 四类任务全选、每类 1 条、智谱/DeepSeek/Kimi 三家。
INIT_INPUT = "1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n"
THREE_MODELS = ["glm-4-flash-250414", "deepseek-flash", "kimi-k3"]


@pytest.fixture()
def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setenv("BLINDTASTE_HOME", str(tmp_path / "home"))
    return SessionStore(home_dir())


def _init(store: SessionStore) -> None:
    result = runner.invoke(app, ["init"], input=INIT_INPUT)
    assert result.exit_code == 0, result.output
    assert store.load_battery() is not None


def _assert_clean_failure(result, *expected_fragments: str) -> None:
    """以 typer.Exit(1) 退出（不是未捕获异常），且提示里含预期片段。"""
    assert isinstance(result.exception, SystemExit), (
        f"期望干净退出，实际抛出 {result.exception!r}"
    )
    assert result.exit_code == 1
    for fragment in expected_fragments:
        assert fragment in result.output, result.output


# ---------------------------------------------------------------------------
# run --models 覆盖
# ---------------------------------------------------------------------------


def test_models_override_single_model_exits_cleanly(store: SessionStore) -> None:
    """只给 1 家模型无法配对：干净报错，而不是 round1_trials 的 ValueError 抛栈。"""
    _init(store)
    result = runner.invoke(
        app, ["run", "--demo", "--models", "glm-4-flash-250414"], input=""
    )
    _assert_clean_failure(result, "2")
    assert store.load_votes() == []


def test_models_override_duplicate_ids_exits_cleanly(store: SessionStore) -> None:
    """重复 id 去重后只剩 1 家：干净报错，绝不落一条自比自的选票。"""
    _init(store)
    result = runner.invoke(
        app,
        ["run", "--demo", "--models", "glm-4-flash-250414,glm-4-flash-250414"],
        input="a\n",
    )
    _assert_clean_failure(result, "2")
    assert store.load_votes() == []


def test_models_override_two_distinct_models_still_runs(store: SessionStore) -> None:
    """回归护栏：合法的两家模型覆盖必须照常工作，且票面两侧是不同模型。"""
    _init(store)
    result = runner.invoke(
        app,
        ["run", "--demo", "--limit", "1", "--models", "glm-4-flash-250414,kimi-k3"],
        input="a\n",
    )
    assert result.exit_code == 0, result.output
    votes = store.load_votes()
    assert len(votes) == 1
    assert votes[0].models["a"] != votes[0].models["b"]
    assert {votes[0].models["a"], votes[0].models["b"]} == {
        "glm-4-flash-250414",
        "kimi-k3",
    }


# ---------------------------------------------------------------------------
# init --tasks 种子文件
# ---------------------------------------------------------------------------


def test_init_tasks_illegal_kind_exits_cleanly(store: SessionStore, tmp_path: Path) -> None:
    path = tmp_path / "bad-kind.toml"
    path.write_text('[[task]]\nkind = "nope"\nprompt = "x"\n', encoding="utf-8")
    result = runner.invoke(app, ["init", "--tasks", str(path)])
    _assert_clean_failure(result, "kind")
    assert store.load_battery() is None


def test_init_tasks_missing_prompt_exits_cleanly(store: SessionStore, tmp_path: Path) -> None:
    path = tmp_path / "no-prompt.toml"
    path.write_text('[[task]]\nkind = "weekly"\n', encoding="utf-8")
    result = runner.invoke(app, ["init", "--tasks", str(path)])
    _assert_clean_failure(result, "prompt")
    assert store.load_battery() is None


def test_init_tasks_malformed_toml_exits_cleanly(store: SessionStore, tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("this is not toml [[[\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--tasks", str(path)])
    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 1
    assert store.load_battery() is None


# ---------------------------------------------------------------------------
# 票仓损坏
# ---------------------------------------------------------------------------


def test_corrupt_vault_reports_cleanly_on_report(store: SessionStore) -> None:
    _init(store)
    runner.invoke(app, ["run", "--demo", "--limit", "1"], input="a\n")
    assert len(store.load_votes()) == 1
    # 模拟追加写被中断留下的半行
    with store.votes_path.open("a", encoding="utf-8") as handle:
        handle.write('{"partial": tru')

    result = runner.invoke(app, ["report"])
    _assert_clean_failure(result, "损坏")


def test_corrupt_vault_reports_cleanly_on_run(store: SessionStore) -> None:
    _init(store)
    with store.votes_path.open("a", encoding="utf-8") as handle:
        handle.write('{"partial": tru')

    result = runner.invoke(app, ["run", "--demo", "--limit", "1"], input="a\n")
    _assert_clean_failure(result, "损坏")
