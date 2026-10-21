"""版本 lockstep：每个描述「当前版本」的手工版本面都必须与 ``blindtaste.__version__`` 一致。

v0.2.0 是本仓库的第一次版本号上抬。版本字符串散落在多处、全部手改，且没有
任何测试把它们绑在一起——上抬时漏掉任意一处（最典型是 shields.io 徽章与
``web/site.json`` 的 ``implementation_version``）都只能靠肉眼发现。本模块把
「单一来源 = ``blindtaste.__version__``，其余面必须与它一致」固化成断言。

刻意不纳入的两处**历史记录**（它们记录的是过去某次发布的事实，不是当前版本）：

- ``CHANGELOG.md`` 里旧版本号的条目——只断言当前版本有条目，不改写历史；
- ``docs/demo-results.json`` 的 ``implementation_version``——那是 m1 录屏
  发生时的产品版本（与 ``recorded_at`` / ``milestone`` 同属一条 provenance）。

新增「当前版本」版本面时，在这里加一条断言即可。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import blindtaste

REPO = Path(__file__).resolve().parent.parent
VERSION = blindtaste.__version__


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION


def test_pyproject_version_matches_package() -> None:
    match = re.search(r'^version = "([^"]+)"$', _read("pyproject.toml"), re.M)
    assert match is not None, "pyproject.toml 里找不到 version"
    assert match.group(1) == VERSION


def test_web_site_json_implementation_version_matches_package() -> None:
    site = json.loads(_read("web/site.json"))
    assert site["meta"]["implementation_version"] == VERSION


def test_demo_results_records_a_released_version() -> None:
    """站点 demo 区块引用这份录屏（web/site.json 的 meta.demo_source）。

    它是历史记录，不要求等于当前版本，但必须是一个合法的已发布版本号，
    否则站点会展示一条读不出来的 provenance。
    """
    demo = json.loads(_read("docs/demo-results.json"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", demo["implementation_version"])
    assert demo["recorded_at"], "录屏记录必须有时间戳"


def test_readme_badges_show_current_version() -> None:
    for relative_path in ("README.md", "README.en.md"):
        text = _read(relative_path)
        assert f"badge/version-{VERSION}-blue" in text, relative_path
        assert f'alt="version {VERSION}"' in text, relative_path


def test_changelog_documents_current_version() -> None:
    changelog = _read("CHANGELOG.md")
    assert re.search(rf"^## {re.escape(VERSION)} - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M), (
        f"CHANGELOG.md 缺少 {VERSION} 的条目"
    )
