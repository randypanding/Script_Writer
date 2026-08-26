"""resolve_pending 的降级语义(round12:NPC 从不补 donor,PENDING 悬空是随机后端最高频死法)。"""

from nsc.passes.p3_beatsheet import resolve_pending


def _sp(ep: str, slug: str, setup_ref, payoff_ref, desc="测试伏笔"):
    return {
        "id": f"sp-{ep}-{slug}",
        "kind": "setup_payoff",
        "_episode_id": ep,
        "_slug": slug,
        "description": desc,
        "setup_beat_id": setup_ref,
        "payoff_beat_id": payoff_ref,
    }


def test_donor_present_resolves():
    sps = [
        _sp("ep1", "s1", "b1", "PENDING:reveal"),
        _sp("ep2", "reveal", "b2", "b3"),  # donor:同 slug,真实 Beat
    ]
    out = resolve_pending(sps)
    assert out[0]["payoff_beat_id"] == "b3"


def test_missing_donor_demotes_instead_of_raise():
    """无 donor 的 PENDING:删除该 setup_payoff 条目而不是 PassFailure(语义降级:
    跨集伏笔契约解除,保留叙事文本;优于全管线死亡)。"""
    sps = [_sp("ep1", "s1", "b1", "PENDING:ghost")]
    out = resolve_pending(sps)
    assert out == []


def test_missing_donor_keeps_others():
    sps = [
        _sp("ep1", "s1", "b1", "PENDING:ghost"),
        _sp("ep2", "s2", "b2", "b3"),
    ]
    out = resolve_pending(sps)
    assert len(out) == 1 and out[0]["id"] == "sp-ep2-s2"  # 幽灵条目被解除,健康条目保留
