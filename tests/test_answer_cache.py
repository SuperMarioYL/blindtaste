"""回答缓存是派生状态：损坏的缓存条目应当降级为 cache miss（v0.3.0 回归测试）。

缺陷（v0.2.0）：``SessionStore.load_answer`` 无保护地 ``json.loads`` 缓存文件，
写一半的 JSON（Ctrl-C / 磁盘满）会让 ``blindtaste run`` 以 JSONDecodeError
traceback 退出，任何一对都还没显示。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from blindtaste import cli
from blindtaste.session import SessionStore, home_dir, round1_trials

runner = CliRunner()

INIT_TWO = "1,2,3,4\n1\n1\n1\n1\n1\n\n1,2\n"


@pytest.fixture()
def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setenv("BLINDTASTE_HOME", str(tmp_path / "home"))
    return SessionStore(home_dir())


def test_corrupt_cache_entry_is_a_miss(store: SessionStore) -> None:
    result = runner.invoke(cli.app, ["init"], input=INIT_TWO)
    assert result.exit_code == 0, result.output

    battery = store.load_battery()
    assert battery is not None
    trial = round1_trials(battery)[0]
    task = {t.id: t for t in battery.tasks}[trial.task_id]

    corrupt_paths = []
    for model_id in trial.models:
        path = store.cache_dir / f"{store._cache_key(model_id, task.prompt, demo=True)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 追加写被中断后的典型残留：合法前缀 + 半截 JSON。
        path.write_text('{"model": "x", "mode": "demo", "answer": "trunc', encoding="utf-8")
        corrupt_paths.append(path)

    assert store.load_answer(trial.models[0], task.prompt, demo=True) is None

    run_result = runner.invoke(cli.app, ["run", "--demo", "--limit", "1"], input="a\n")

    assert run_result.exit_code == 0, run_result.output
    assert "Traceback" not in run_result.output
    assert "JSONDecodeError" not in run_result.output
    assert len(store.load_votes()) == 1

    # 重新请求后的缓存被覆盖成合法 JSON，下一次运行不再命中坏条目。
    for path in corrupt_paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(record["answer"], str) and record["answer"]
        assert store.load_answer(record["model"], task.prompt, demo=True) == record["answer"]
