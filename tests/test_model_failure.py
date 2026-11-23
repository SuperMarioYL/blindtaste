"""一家模型的 API 调用失败不能拖垮整轮盲测（v0.3.0 回归测试）。

缺陷（v0.2.0）：``OpenAICompatAdapter.complete`` 在 401/5xx/网络错误时 raise
``ProviderError``，而 ``run_session`` 与 ``cli.run`` 都没有捕获，于是整轮盲测
以 traceback 中止——与 providers.py / README「失败不会拖垮其余模型的盲测」矛盾。
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from blindtaste import cli
from blindtaste.providers import MODELS, DemoAdapter, ProviderError
from blindtaste.session import SessionStore, home_dir

runner = CliRunner()

# 四类任务各 1 条、三家模型（glm / deepseek / kimi）。
INIT_THREE = "1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n"
# 两家模型：任意一对都包含失败模型，可验证「全部失败」的退出码。
INIT_TWO = "1,2,3,4\n1\n1\n1\n1\n1\n\n1,2\n"


@pytest.fixture()
def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setenv("BLINDTASTE_HOME", str(tmp_path / "home"))
    return SessionStore(home_dir())


class FailingAdapter:
    """模拟配置了错误 key 的模型：每次调用都抛 ProviderError。"""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def complete(self, prompt: str) -> str:
        raise ProviderError(
            f"{self.model_id}（测试替身）鉴权失败（HTTP 401）：检查 key 是否正确。"
        )


def _patch_adapters(monkeypatch: pytest.MonkeyPatch, failing_id: str) -> None:
    def fake_build(model_ids, keys, *, demo: bool = False):
        return {
            model_id: (
                FailingAdapter(model_id)
                if model_id == failing_id
                else DemoAdapter(MODELS[model_id])
            )
            for model_id in model_ids
        }

    monkeypatch.setattr(cli, "build_adapters", fake_build)


def test_provider_error_skips_pair_and_run_continues(store, monkeypatch) -> None:
    """kimi 全部失败：其余模型的对局照常投票，失败的对不落票、重跑会重试。"""
    assert runner.invoke(cli.app, ["init"], input=INIT_THREE).exit_code == 0
    _patch_adapters(monkeypatch, "kimi-k3")

    result = runner.invoke(cli.app, ["run"], input="a\n" * 20)

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "跳过" in result.output and "kimi-k3" in result.output
    assert "因模型调用失败被跳过" in result.output

    votes = store.load_votes()
    assert votes, "另外两家模型的对局应当照常落票"
    assert all("kimi-k3" not in vote.models.values() for vote in votes)
    assert all(vote.mode == "live" for vote in votes)


def test_all_pairs_failing_exits_nonzero(store, monkeypatch) -> None:
    """两家模型且其中一家全失败：本轮一对也没投成，退出码必须是 1 而不是静默 0。"""
    assert runner.invoke(cli.app, ["init"], input=INIT_TWO).exit_code == 0
    _patch_adapters(monkeypatch, "glm-4-flash-250414")

    result = runner.invoke(cli.app, ["run"], input="")

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "跳过" in result.output
    assert "所有对局都因模型调用失败被跳过" in result.output
    assert store.load_votes() == []
