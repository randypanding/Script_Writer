"""历史压缩（T-33 / ADR-0013；机制来源 StoryWriter MessageRedact）。

compress_history 是纯编排：远端集走注入的 summarize（测试传 stub，生产用工厂），
近端集保原文片段；同 text 内容寻址去重，同输入不重复调用。
make_llm_summarizer 是生产实现：LLM 出口走 nsc.runtime.models 路由（AGENTS.md §2），
摘要结果按 sha(text) 写 runtime.cache 内容寻址缓存（跨进程持久）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

__all__ = ["compress_history", "make_llm_summarizer"]

_RECENT_CLIP_CHARS = 2000  # 近端集原文截断长度（机制常量：防单集超长撑爆上下文）

_router_instance: Any = None


def compress_history(
    episodes: list[dict],
    current_no: int,
    summarize: Callable[[str, int], str],
    keep_recent: int = 1,
    ratio: float = 0.1,
) -> str:
    """把 no < current_no 的历史集压成 "【前情】…\\n【上一集】…" 一段文本。

    - 远端集（no <= current_no−1−keep_recent）：summarize(text, int(len(text)*ratio))；
      目标长度由本函数计算，长度达标由调用方注入的 summarize 保证。
    - 近端 keep_recent 集（current_no−keep_recent <= no <= current_no−1）：
      保留原文前 _RECENT_CLIP_CHARS 字符。
    - 同 text 只调一次 summarize（内容寻址 sha→result 去重）。
    - no >= current_no 的集不属于历史，忽略；无历史内容时返回空串。
    """
    far = sorted(
        (ep for ep in episodes if ep["no"] <= current_no - 1 - keep_recent),
        key=lambda ep: ep["no"],
    )
    recent = sorted(
        (ep for ep in episodes if current_no - keep_recent <= ep["no"] <= current_no - 1),
        key=lambda ep: ep["no"],
    )
    memo: dict[str, str] = {}

    def _sum(text: str) -> str:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key not in memo:
            memo[key] = summarize(text, max(1, int(len(text) * ratio)))
        return memo[key]

    parts: list[str] = []
    if far:
        parts.append("【前情】\n" + "\n".join(_sum(ep["text"]) for ep in far))
    if recent:
        parts.append("【上一集】\n" + "\n".join(ep["text"][:_RECENT_CLIP_CHARS] for ep in recent))
    return "\n".join(parts)


def make_llm_summarizer(router: Any = None, tier: str = "tier_bulk") -> Callable[[str, int], str]:
    """生产用 summarize 工厂：LLM 走 nsc.runtime.models 路由 + 内容寻址缓存。

    router 可注入（测试传 fake，协议同 PassContext.router）；缺省懒建 ModelRouter。
    缓存两级：闭包 dict（进程内）+ runtime.cache 的 diskcache（跨进程），
    键均为 "context/compress/" + sha256(text)——同 text 不重复调用。
    """

    local: dict[str, str] = {}

    def summarize(text: str, target_len: int) -> str:
        from nsc.runtime.cache import _cache  # 调用时取，兼容测试 monkeypatch

        key = "context/compress/" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key in local:
            return local[key]
        if key in _cache:
            local[key] = str(_cache[key])
            return local[key]
        res = _router(router).complete(
            tier,
            [
                {
                    "role": "system",
                    "content": (
                        f"把用户给出的剧集原文压缩成不超过 {target_len} 字的剧情摘要，"
                        "保留人物状态变化与因果链，不得发明新信息。只输出摘要正文。"
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        local[key] = res.text
        _cache[key] = res.text
        return res.text

    return summarize


def _router(router: Any = None) -> Any:
    global _router_instance
    if router is not None:
        return router
    if _router_instance is None:
        from nsc.runtime.models import ModelRouter

        _router_instance = ModelRouter()
    return _router_instance
