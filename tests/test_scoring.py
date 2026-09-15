"""m1 盲测电池测试：电池构建、盲配对、投票落盘与续跑、统计与适配层。

所有模型调用全部使用替身（伪适配器 / httpx.MockTransport / DemoAdapter），
测试不发出任何网络请求、不需要 API key。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from blindtaste import intake, providers, scoring, session
from blindtaste.cli import app
from blindtaste.intake import Battery, TaskItem, build_battery, battery_fingerprint
from blindtaste.providers import (
    MODELS,
    DemoAdapter,
    OpenAICompatAdapter,
    ProviderNotConfigured,
    build_adapters,
    load_keys,
)
from blindtaste.session import (
    SessionStore,
    display_models,
    home_dir,
    record_vote,
    round1_trials,
    run_session,
)

REPO = Path(__file__).resolve().parent.parent
runner = CliRunner()


# ---------------------------------------------------------------------------
# 测试基建
# ---------------------------------------------------------------------------


class FakeAdapter:
    """每个模型返回固定前缀 + prompt 摘要的伪适配器（内容不含模型身份）。"""

    def __init__(self, model_id: str, marker: str) -> None:
        self.model_id = model_id
        self.marker = marker
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return f"({self.marker}) 对「{prompt[:12]}…」的回答"


def three_models() -> list[providers.ModelRef]:
    return [MODELS[i] for i in ("glm-4-flash-250414", "deepseek-flash", "kimi-k3")]


@pytest.fixture()
def battery() -> Battery:
    return build_battery(
        kinds=["resume", "weekly", "ppt", "translate"],
        scenes={"resume_scene": "social", "weekly_scene": "focus",
                "ppt_scene": "business", "translate_scene": "mail"},
        density=1,
        custom_prompts=[],
        models=three_models(),
    )


@pytest.fixture()
def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setenv("BLINDTASTE_HOME", str(tmp_path / "home"))
    return SessionStore(home_dir())


def fake_adapters() -> dict[str, FakeAdapter]:
    return {
        "glm-4-flash-250414": FakeAdapter("glm-4-flash-250414", "甲"),
        "deepseek-flash": FakeAdapter("deepseek-flash", "乙"),
        "kimi-k3": FakeAdapter("kimi-k3", "丙"),
    }


# ---------------------------------------------------------------------------
# intake：问卷 -> 电池
# ---------------------------------------------------------------------------


def test_build_battery_matches_plan_shape(battery: Battery) -> None:
    """四类任务、密度 1、无自定义 -> 4 条任务；模型 3 家；source=intake。"""
    kinds = [t.kind for t in battery.tasks]
    assert kinds == ["resume", "weekly", "ppt", "translate"]
    assert all(t.source == "intake" for t in battery.tasks)
    assert all(t.prompt.strip() for t in battery.tasks)
    assert [m.id for m in battery.models] == [
        "glm-4-flash-250414", "deepseek-flash", "kimi-k3",
    ]
    assert battery.retest_fraction == 0.3
    # 场景答案命中对应模板而不是兜底模板
    assert battery.tasks[0].id == "resume-social"
    assert battery.tasks[1].id == "weekly-focus"


def test_build_battery_density_two_uses_fallback(battery: Battery) -> None:
    wide = build_battery(
        kinds=["resume", "weekly", "ppt", "translate"],
        scenes={"resume_scene": "campus", "weekly_scene": "cross",
                "ppt_scene": "training", "translate_scene": "tech"},
        density=2,
        custom_prompts=["把这段介绍改写成小红书文案：……"],
        models=three_models(),
    )
    assert len(wide.tasks) == 9  # 4 类 × 2 + 1 自定义
    assert wide.tasks[-1].kind == "custom"
    assert wide.tasks[-1].id == "custom-1"
    resume_ids = [t.id for t in wide.tasks if t.kind == "resume"]
    assert "resume-campus" in resume_ids and "resume-general" in resume_ids


def test_build_battery_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        build_battery(kinds=[], scenes={}, density=1, custom_prompts=[],
                      models=three_models())
    with pytest.raises(ValueError):
        build_battery(kinds=["resume"], scenes={}, density=1, custom_prompts=[],
                      models=three_models()[:1])


def test_seed_mode_reads_tasks_file(tmp_path: Path) -> None:
    path = tmp_path / "tasks.toml"
    path.write_text(
        '[[task]]\nkind = "weekly"\nprompt = "整理这份周报"\n\n'
        '[[task]]\nkind = "custom"\nprompt = "改写这段文案"\n',
        encoding="utf-8",
    )
    tasks = intake.battery_from_seed_file(path)
    assert [t.source for t in tasks] == ["seed", "seed"]
    assert [t.kind for t in tasks] == ["weekly", "custom"]


def test_seed_mode_rejects_bad_kind(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text('[[task]]\nkind = "nope"\nprompt = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="kind"):
        intake.battery_from_seed_file(path)


def test_battery_fingerprint_ignores_timestamp(battery: Battery) -> None:
    other = battery.model_copy(update={"created_at": "2030-01-01T00:00:00+00:00"})
    assert battery_fingerprint(battery) == battery_fingerprint(other)
    trimmed = battery.model_copy(
        update={"tasks": battery.tasks[:2]}
    )
    assert battery_fingerprint(battery) != battery_fingerprint(trimmed)


# ---------------------------------------------------------------------------
# session：盲配对与投票
# ---------------------------------------------------------------------------


def test_round1_trials_shape_and_determinism(battery: Battery) -> None:
    trials = round1_trials(battery)
    pairs_per_task = 3  # C(3,2)
    assert len(trials) == min(session.ROUND1_MAX_PAIRS, 4 * pairs_per_task)
    assert all(t.blind_order in ("AB", "BA") for t in trials)
    assert all(len(set(t.models)) == 2 for t in trials)
    assert len({t.id for t in trials}) == len(trials)
    # 确定性：同一电池两次生成完全一致（断点续跑的前提）
    again = round1_trials(battery)
    assert [t.id for t in trials] == [t.id for t in again]
    # 轮转取对：第一轮每类任务各出一对
    first_pass_kinds = [t.task_kind for t in trials[: len(battery.tasks)]]
    assert sorted(first_pass_kinds) == sorted(t.kind for t in battery.tasks)


def test_display_models_respects_blind_order() -> None:
    trial = session.Trial(
        id="x", task_id="t", task_kind="resume",
        models=("deepseek-flash", "glm-4-flash-250414"), blind_order="BA",
    )
    assert display_models(trial) == {
        "a": "glm-4-flash-250414", "b": "deepseek-flash",
    }
    trial_ab = trial.model_copy(update={"blind_order": "AB"})
    assert display_models(trial_ab) == {
        "a": "deepseek-flash", "b": "glm-4-flash-250414",
    }


def test_record_vote_resolves_winner() -> None:
    trial = session.Trial(
        id="x", task_id="t", task_kind="weekly",
        models=("deepseek-flash", "glm-4-flash-250414"), blind_order="BA",
    )
    vote = record_vote(trial, "a", think_ms=1200)
    assert vote.models == {"a": "glm-4-flash-250414", "b": "deepseek-flash"}
    assert vote.winner == "glm-4-flash-250414"  # 投显示侧 A，胜者是它背后的模型
    assert vote.round == 1
    tie = record_vote(trial, "tie", think_ms=800)
    assert tie.winner is None
    with pytest.raises(ValueError):
        record_vote(trial, "c", think_ms=1)


def test_run_session_records_votes_and_resumes(
    battery: Battery, store: SessionStore, tmp_path: Path
) -> None:
    console = Console(file=open(tmp_path / "out.txt", "w"), width=100)
    adapters = fake_adapters()
    picks = iter(["a", "b", "tie", "a", "b", "a"])
    votes_cast: list[str] = []

    def vote_fn(trial, answer_a, answer_b):
        pick = next(picks)
        votes_cast.append(pick)
        return pick, 900

    # 第一次只投 3 对
    result = run_session(battery, adapters, store, console, vote_fn, limit=3)
    assert len(result.voted) == 3
    assert result.completed == 3 and result.remaining == 9

    # 模拟中断后重跑：从第 4 对继续，不重复已投票的 trial
    remaining = [p for p in ["a", "b", "tie", "a", "b", "a"]][3:]
    picks = iter(remaining + ["tie"] * 20)
    result2 = run_session(battery, adapters, store, console, vote_fn)
    assert result2.remaining == 0

    votes = store.load_votes()
    assert len(votes) == 12  # 4 任务 × 3 对
    assert len({v.trial_id for v in votes}) == 12
    # 每张票自描述：winner 与显示侧映射一致
    for vote in votes:
        if vote.pick == "tie":
            assert vote.winner is None
        else:
            assert vote.winner == vote.models[vote.pick]
    # 回答缓存生效：同一 (模型, 任务) 只真正请求一次
    # 4 任务 × 3 模型 = 12 次调用；无缓存将是 12 对 × 2 = 24 次
    total_calls = sum(len(a.calls) for a in adapters.values())
    assert total_calls == 12


def test_run_session_shows_blind_panels(
    battery: Battery, store: SessionStore, tmp_path: Path
) -> None:
    out = open(tmp_path / "out.txt", "w")
    console = Console(file=out, width=100)
    adapters = fake_adapters()

    def vote_fn(trial, answer_a, answer_b):
        out.flush()
        rendered = (tmp_path / "out.txt").read_text()
        # 投票前票面上只有匿名 A/B，不出现任何模型名或厂商标签
        assert "回答 A" in rendered and "回答 B" in rendered
        for label in ("智谱", "DeepSeek", "Kimi", "glm", "kimi-k3", "deepseek"):
            assert label not in rendered, f"票面泄漏了模型身份：{label}"
        return "tie", 10

    run_session(battery, adapters, store, console, vote_fn, limit=1)
    # 投票后揭晓
    out.flush()
    assert "揭晓" in (tmp_path / "out.txt").read_text()


# ---------------------------------------------------------------------------
# scoring：票面统计 + m2 占位
# ---------------------------------------------------------------------------


def _vote(a: str, b: str, pick: str, kind: str = "resume") -> session.Vote:
    return session.Vote(
        trial_id=f"{a}-{b}-{pick}-{kind}", task_id="t", task_kind=kind,
        round=1, models={"a": a, "b": b}, blind_order="AB", pick=pick,
        think_ms=1,
        winner=None if pick == "tie" else (a if pick == "a" else b),
        voted_at="2026-01-01T00:00:00+00:00",
    )


def test_tally_votes_counts_and_winrate() -> None:
    votes = [
        _vote("glm", "ds", "a"),
        _vote("glm", "kimi", "a"),
        _vote("ds", "kimi", "a"),
        _vote("glm", "kimi", "tie"),
        _vote("ds", "kimi", "tie"),
    ]
    tallies = scoring.tally_votes(votes)
    assert tallies["glm"].wins == 2 and tallies["glm"].losses == 0
    assert tallies["ds"].wins == 1 and tallies["ds"].losses == 1
    # 两次平票：kimi 各 +1 tie；另有两票 kimi 落败
    assert tallies["kimi"].ties == 2 and tallies["kimi"].losses == 2
    # winrate = (胜 + 0.5×平) / 出场
    assert tallies["kimi"].winrate == pytest.approx((0 + 0.5 * 2) / 4)


def test_kind_winrates_groups_by_kind() -> None:
    votes = [
        _vote("glm", "ds", "a", kind="resume"),
        _vote("ds", "glm", "a", kind="weekly"),
        _vote("glm", "ds", "a", kind="weekly"),
    ]
    grouped = scoring.kind_winrates(votes)
    assert grouped[("resume", "glm")].wins == 1
    assert grouped[("weekly", "glm")].wins == 1
    assert grouped[("weekly", "glm")].losses == 1
    assert grouped[("weekly", "ds")].wins == 1
    assert ("resume", "kimi") not in grouped


def test_m2_stubs_are_documented_and_raise() -> None:
    for fn in (scoring.bradley_terry, scoring.retest_agreement, scoring.noise_tasks):
        with pytest.raises(scoring.MilestoneNotImplemented):
            fn([])
    import blindtaste.report as report

    with pytest.raises(scoring.MilestoneNotImplemented):
        report.render_markdown([], [])
    with pytest.raises(scoring.MilestoneNotImplemented):
        report.render_html([], [])
    # 快照装载是真实功能：全部为 null（未抄录）
    snapshot = report.load_index_snapshot()
    assert report.snapshot_is_filled(snapshot) is False
    assert set(snapshot["models"]) == set(MODELS)


# ---------------------------------------------------------------------------
# providers：key 解析、错误与请求形状
# ---------------------------------------------------------------------------


def test_load_keys_parses_env_style_file(tmp_path: Path) -> None:
    path = tmp_path / "keys.env"
    path.write_text(
        "# 注释\nZHIPU_API_KEY=sk-abc\n\nDEEPSEEK_API_KEY='sk-def'\n",
        encoding="utf-8",
    )
    keys = load_keys(path)
    assert keys == {"ZHIPU_API_KEY": "sk-abc", "DEEPSEEK_API_KEY": "sk-def"}
    assert load_keys(tmp_path / "missing.env") == {}


def test_build_adapters_unconfigured_lists_env_and_path(tmp_path: Path) -> None:
    with pytest.raises(ProviderNotConfigured) as excinfo:
        build_adapters(["glm-4-flash-250414", "deepseek-flash"], {})
    message = str(excinfo.value)
    assert "ZHIPU_API_KEY" in message and "DEEPSEEK_API_KEY" in message
    assert "keys.env" in message
    # 未验证的豆包单独配置 key 时可以构建（best-effort 不拦人）
    adapters = build_adapters(["doubao-pro-32k"], {"ARK_API_KEY": "x"})
    assert isinstance(adapters["doubao-pro-32k"], OpenAICompatAdapter)
    with pytest.raises(ProviderNotConfigured, match="未经验证"):
        build_adapters(["doubao-pro-32k"], {})


def test_build_adapters_demo_mode_needs_no_keys() -> None:
    adapters = build_adapters(
        ["glm-4-flash-250414", "kimi-k3"], {}, demo=True
    )
    assert all(isinstance(a, DemoAdapter) for a in adapters.values())


def test_demo_adapter_deterministic_and_distinct() -> None:
    glm = DemoAdapter(MODELS["glm-4-flash-250414"])
    kimi = DemoAdapter(MODELS["kimi-k3"])
    prompt = "把这段周报整理成三段"
    assert glm.complete(prompt) == glm.complete(prompt)
    assert glm.complete(prompt) != kimi.complete(prompt)


def test_openai_adapter_request_and_errors() -> None:
    ref = MODELS["glm-4-flash-250414"]
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "回答内容"}}]},
        )

    adapter = OpenAICompatAdapter(
        ref, "sk-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert adapter.complete("任务 prompt") == "回答内容"
    assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == ref.id
    assert captured["body"]["messages"] == [
        {"role": "user", "content": "任务 prompt"}
    ]

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    bad = OpenAICompatAdapter(
        ref, "sk-wrong",
        client=httpx.Client(transport=httpx.MockTransport(unauthorized)),
    )
    with pytest.raises(providers.ProviderError, match="ZHIPU_API_KEY"):
        bad.complete("任务")

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    ugly = OpenAICompatAdapter(
        ref, "sk-ok",
        client=httpx.Client(transport=httpx.MockTransport(malformed)),
    )
    with pytest.raises(providers.ProviderError, match="结构"):
        ugly.complete("任务")


# ---------------------------------------------------------------------------
# CLI：端到端（伪输入，无网络）
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_init_questionnaire_creates_battery(store: SessionStore) -> None:
    result = runner.invoke(
        app,
        ["init"],
        input="1,2,3,4\n1\n1\n1\n1\n2\n\n1,2,4\n",
    )
    assert result.exit_code == 0, result.output
    battery = store.load_battery()
    assert battery is not None
    assert len(battery.tasks) == 8  # 每类 2 条
    assert [m.id for m in battery.models] == [
        "glm-4-flash-250414", "deepseek-flash", "kimi-k3",
    ]


def test_cli_init_seed_mode(store: SessionStore) -> None:
    result = runner.invoke(
        app,
        ["init", "--tasks", str(REPO / "examples" / "tasks.example.toml")],
        input="1,3\n",
    )
    assert result.exit_code == 0, result.output
    battery = store.load_battery()
    assert battery is not None
    assert [t.source for t in battery.tasks] == ["seed"] * 3
    assert [m.id for m in battery.models] == [
        "glm-4-flash-250414", "qwen3.7-plus",
    ]


def test_cli_run_without_battery_fails_cleanly(store: SessionStore) -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "blindtaste init" in result.output


def test_cli_run_without_keys_shows_env_names(store: SessionStore) -> None:
    runner.invoke(app, ["init"], input="1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n")
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "ZHIPU_API_KEY" in result.output
    assert "keys.env" in result.output


def test_cli_demo_run_end_to_end(store: SessionStore) -> None:
    """init -> run --demo（投 2 票）-> 续跑 -> report，全链路无网络。"""
    init_result = runner.invoke(
        app, ["init"], input="1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n"
    )
    assert init_result.exit_code == 0, init_result.output

    first = runner.invoke(app, ["run", "--demo", "--limit", "2"], input="a\nb\n")
    assert first.exit_code == 0, first.output
    assert "演示模式" in first.output
    assert "揭晓" in first.output
    votes = store.load_votes()
    assert len(votes) == 2 and all(v.round == 1 for v in votes)

    second = runner.invoke(app, ["run", "--demo", "--limit", "1"], input="tie\n")
    assert second.exit_code == 0, second.output
    assert "已完成 2" in second.output  # 续跑从上一轮进度开始
    assert len(store.load_votes()) == 3

    report_result = runner.invoke(app, ["report"])
    assert report_result.exit_code == 0
    assert "首轮进度 3 对" in report_result.output
    assert "m2" in report_result.output

    retest_result = runner.invoke(app, ["retest"])
    assert retest_result.exit_code == 0
    assert "m2" in retest_result.output


def test_cli_models_override_rejects_unknown(store: SessionStore) -> None:
    runner.invoke(app, ["init"], input="1,2,3,4\n1\n1\n1\n1\n1\n\n1,2,4\n")
    result = runner.invoke(
        app, ["run", "--demo", "--models", "glm-4-flash-250414,nope"], input=""
    )
    assert result.exit_code == 1
    assert "未知模型" in result.output
