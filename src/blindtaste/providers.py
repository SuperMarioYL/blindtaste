"""模型注册表与 OpenAI 兼容适配层。

五家目标模型全部走各自的官方 OpenAI 兼容 chat completions 端点，统一在
:class:`ChatAdapter` 接口后面：session 只依赖这个接口，不感知各家差异。

火山方舟（豆包）的 OpenAI 兼容性从未用真实 key 验证过，因此它的
``ModelRef.verified`` 标记为 False——未配置时给出明确的错误说明，配置了也只
作为 best-effort 参与，失败不会拖垮其余模型的盲测。
"""

from __future__ import annotations

import hashlib
import os
import random
from pathlib import Path
from typing import Mapping, Protocol

import httpx
from pydantic import BaseModel

#: 发给每家模型的抽样参数：盲测要对比的是日常任务上的表现，
#: 用常规温度与受限长度，避免长篇扩散把对比淹没。
REQUEST_MAX_TOKENS = 800
REQUEST_TEMPERATURE = 0.7
REQUEST_TIMEOUT_SECONDS = 60.0


class ProviderError(RuntimeError):
    """适配器失败（网络、鉴权、响应格式）。"""


class ProviderNotConfigured(ProviderError):
    """所选模型没有可用的 API key。"""


class ModelRef(BaseModel):
    """一家参测模型：id 发给 API，其余字段用于展示与配置。"""

    id: str
    label: str
    provider: str
    base_url: str
    key_env: str
    verified: bool = True
    note: str = ""


MODELS: dict[str, ModelRef] = {
    ref.id: ref
    for ref in (
        ModelRef(
            id="glm-4-flash-250414",
            label="智谱 GLM-4-Flash",
            provider="zhipu",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            key_env="ZHIPU_API_KEY",
            note="有免费档",
        ),
        ModelRef(
            id="deepseek-flash",
            label="DeepSeek",
            provider="deepseek",
            base_url="https://api.deepseek.com",
            key_env="DEEPSEEK_API_KEY",
            note="按 token 计费，无免费额度",
        ),
        ModelRef(
            id="qwen3.7-plus",
            label="通义（阿里云百炼）",
            provider="dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            key_env="DASHSCOPE_API_KEY",
        ),
        ModelRef(
            id="kimi-k3",
            label="Kimi",
            provider="moonshot",
            base_url="https://api.moonshot.cn/v1",
            key_env="MOONSHOT_API_KEY",
        ),
        ModelRef(
            id="doubao-pro-32k",
            label="豆包（火山方舟）",
            provider="ark",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            key_env="ARK_API_KEY",
            verified=False,
            note="方舟 OpenAI 兼容性未验证，best-effort 接入",
        ),
    )
}


class ChatAdapter(Protocol):
    """一个模型适配器：同样的 prompt 进，一份回答出。"""

    model_id: str

    def complete(self, prompt: str) -> str: ...


class OpenAICompatAdapter:
    """官方 OpenAI 兼容端点的统一适配器。

    ``client`` 可注入（httpx.MockTransport），测试与演示共用同一请求路径。
    """

    def __init__(
        self,
        ref: ModelRef,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.ref = ref
        self.model_id = ref.id
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def complete(self, prompt: str) -> str:
        url = f"{self.ref.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.ref.id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": REQUEST_MAX_TOKENS,
            "temperature": REQUEST_TEMPERATURE,
        }
        try:
            response = self._client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.ref.label}（{self.ref.id}）请求失败：{exc}"
            ) from exc
        if response.status_code in (401, 403):
            raise ProviderError(
                f"{self.ref.label}（{self.ref.id}）鉴权失败（HTTP {response.status_code}）："
                f"检查 {self.ref.key_env} 是否正确。"
            )
        if response.status_code != 200:
            raise ProviderError(
                f"{self.ref.label}（{self.ref.id}）返回 HTTP {response.status_code}："
                f"{response.text[:200]}"
            )
        try:
            body = response.json()
            return body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.ref.label}（{self.ref.id}）响应不是预期的 chat.completions 结构"
            ) from exc


class DemoAdapter:
    """``run --demo`` 使用的离线模拟适配器。

    不调用任何 API：以模型 id 决定「文风」、(模型 id, prompt) 决定内容要点，
    确定性生成彼此有可见差异的模拟回答——盲选交互因此有真实的区分度可投。
    模拟回答只用于走通交互与票仓流程，不代表任何真实模型的输出质量。
    """

    _STYLES = (
        ("分点式", ("① ", "② ", "③ ")),
        ("结构式", ("一、", "二、", "三、")),
        ("直叙式", ("首先，", "其次，", "最后，")),
        ("清单式", ("1. ", "2. ", "3. ", "4. ")),
        ("骨架式", ("[骨架] ", "[要点] ", "[收尾] ")),
    )

    #: 每家 provider 固定一种文风：演示里每个模型有稳定可辨的「性格」。
    _PROVIDER_STYLE = {
        "zhipu": 0,
        "deepseek": 1,
        "dashscope": 2,
        "moonshot": 3,
        "ark": 4,
    }

    _POINT_POOL = (
        "先界定读者与目标，再决定信息密度",
        "把结论前置，过程证据放后半段",
        "收尾给出一个可执行的下一步",
        "按影响面排序，先处理可量化的部分",
        "保留原始措辞中的关键动作动词",
        "补一条缺失的量化口径建议",
        "从已有材料里提取骨架，不凭空补事实",
        "区分事实陈述与主观判断",
        "标注需要人工确认的假设",
        "每段控制在两行以内，先给改写后给理由",
        "用短句替代从句，砍掉修饰性副词",
        "对照原始素材逐条核对，避免漏项",
    )

    def __init__(self, ref: ModelRef) -> None:
        self.ref = ref
        self.model_id = ref.id
        self._style = self._STYLES[
            self._PROVIDER_STYLE.get(ref.provider, len(self._STYLES) - 1)
        ]

    def complete(self, prompt: str) -> str:
        seed = hashlib.sha256(f"{self.ref.id}\x00{prompt}".encode()).hexdigest()
        rng = random.Random(seed)
        style_name, markers = self._style
        topic = prompt.strip().splitlines()[0][:24]
        point_count = 3 if len(markers) == 3 else rng.randint(2, len(markers))
        points = rng.sample(self._POINT_POOL, point_count)
        body = "\n".join(
            f"{marker}{point}" for marker, point in zip(markers, points)
        )
        opener = rng.choice(
            (
                f"围绕「{topic}」，我的处理思路是：",
                f"拿到「{topic}」这类任务，我会这样拆：",
                f"先说结论，再给方案——针对「{topic}」：",
            )
        )
        return "\n".join(
            [
                f"〔{style_name} · 演示回答〕{opener}",
                body,
                "（--demo 模拟回答，不调用任何 API）",
            ]
        )


def load_keys(path: Path) -> dict[str, str]:
    """解析 keys.env（KEY=VALUE 行，支持 # 注释与空行）；文件不存在返回空表。"""
    keys: dict[str, str] = {}
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        keys[name.strip()] = value.strip().strip("'\"")
    return keys


def effective_keys(keys_env_path: Path) -> dict[str, str]:
    """合并生效的 key：keys.env 优先（用户对本工具的明确配置），进程环境兜底。"""
    merged = {
        name: value
        for name, value in os.environ.items()
        if name.endswith("_API_KEY")
    }
    merged.update(load_keys(keys_env_path))
    return merged


def build_adapters(
    model_ids: list[str],
    keys: Mapping[str, str],
    *,
    demo: bool = False,
) -> dict[str, ChatAdapter]:
    """为选定的模型构建适配器。

    :raises ProviderNotConfigured: 任一模型缺少 key 时整体失败，错误信息列出
        缺的环境变量与 keys.env 路径写法，让用户一次补齐。
    """
    adapters: dict[str, ChatAdapter] = {}
    missing: list[ModelRef] = []
    for model_id in model_ids:
        if model_id not in MODELS:
            raise ProviderError(f"未知模型 {model_id}，可选：{', '.join(MODELS)}")
        ref = MODELS[model_id]
        if demo:
            adapters[model_id] = DemoAdapter(ref)
            continue
        key = keys.get(ref.key_env, "")
        if not key:
            missing.append(ref)
            continue
        adapters[model_id] = OpenAICompatAdapter(ref, key)
    if missing:
        lines = [
            "以下模型缺少 API key，无法开始盲测：",
            *[
                f"  - {ref.label}（{ref.id}）需要 {ref.key_env}"
                + ("（注意：该接入未经验证，属 best-effort）" if not ref.verified else "")
                for ref in missing
            ],
            "把 key 粘贴到 ~/.blindtaste/keys.env，例如：",
            "  ZHIPU_API_KEY=sk-xxx",
            "或以环境变量提供。智谱 glm-4-flash-250414 有免费档，可先只用它跑通流程。",
            "也可以用 `blindtaste run --demo` 在不配 key 的情况下体验盲测交互。",
        ]
        raise ProviderNotConfigured("\n".join(lines))
    return adapters
