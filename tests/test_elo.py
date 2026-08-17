"""T-40 验收：Elo 锦标赛（ADR-0014）。

覆盖：Elo 公式（手算数值）、Swiss 相邻配对与确定性、奇数轮空、
run_tournament（fake judge_fn、无平局、3000 字截断、固定偏好排名）、
`nsc eval l1 --tournament` 接线（stub 判官 + stub 编译）。全部无 LLM / 无网络。
"""

from __future__ import annotations

import json

import pytest

from nsc.eval.elo import pair_swiss, run_tournament, update_elo
from nsc.judge.rubric_judge import JudgeDecision


# ---------------------------------------------------------------- Elo 公式（手算）
def test_update_elo_equal_ratings_split():
    elo = {"a": 1500.0, "b": 1500.0}
    update_elo(elo, "a", "b", 1.0, k=32)
    # exp_a = 0.5 → Δa = 32*(1-0.5) = +16
    assert elo["a"] == pytest.approx(1516.0)
    assert elo["b"] == pytest.approx(1484.0)
    assert elo["a"] + elo["b"] == pytest.approx(3000.0)  # 零和


def test_update_elo_upset_hand_computed():
    # 手算：exp_a = 1/(1+10^((1400-1600)/400)) = 1/(1+10^-0.5) ≈ 0.759747
    # a 输：Δ = 32*(0-0.759747) ≈ -24.3119 → a≈1575.688, b≈1424.312
    elo = {"a": 1600.0, "b": 1400.0}
    update_elo(elo, "a", "b", 0.0, k=32)
    assert elo["a"] == pytest.approx(1575.688, abs=1e-2)
    assert elo["b"] == pytest.approx(1424.312, abs=1e-2)


def test_update_elo_expected_win_small_gain():
    # 强者获胜：Δ = 32*(1-0.759747) ≈ +7.688
    elo = {"a": 1600.0, "b": 1400.0}
    update_elo(elo, "a", "b", 1.0, k=32)
    assert elo["a"] == pytest.approx(1607.688, abs=1e-2)


def test_update_elo_symmetric_in_caller_order():
    elo1 = {"a": 1500.0, "b": 1500.0}
    update_elo(elo1, "a", "b", 1.0)
    elo2 = {"a": 1500.0, "b": 1500.0}
    update_elo(elo2, "b", "a", 0.0)
    assert elo1["a"] == pytest.approx(elo2["a"])
    assert elo1["b"] == pytest.approx(elo2["b"])


# ---------------------------------------------------------------- Swiss 配对
def test_pair_swiss_adjacent_by_elo_desc():
    elo = {"x": 1500.0, "w": 1600.0, "z": 1400.0, "y": 1550.0}  # 故意打乱插入序
    pairs = pair_swiss(elo, 0)
    # 降序：w(1600) y(1550) x(1500) z(1400) → 相邻两两
    assert [set(p) for p in pairs] == [{"w", "y"}, {"x", "z"}]


def test_pair_swiss_no_repeat_within_round():
    elo = {f"p{i}": float(i) for i in range(8)}
    pairs = pair_swiss(elo, 0)
    flat = [i for p in pairs for i in p]
    assert len(flat) == len(set(flat)) == 8  # 同一轮内每队只出现一次
    assert len(pairs) == 4


def test_pair_swiss_deterministic():
    elo = {"a": 1500.0, "b": 1500.0, "c": 1500.0, "d": 1500.0}
    assert pair_swiss(elo, 0) == pair_swiss(dict(elo), 0)


def test_pair_swiss_odd_lowest_bye():
    elo = {"a": 3.0, "b": 2.0, "c": 1.0}
    pairs = pair_swiss(elo, 0)
    assert pairs == [("a", "b")]  # 最低分 c 轮空


def test_pair_swiss_does_not_mutate_input():
    elo = {"a": 2.0, "b": 1.0, "c": 0.5}
    pair_swiss(elo, 0)
    assert elo == {"a": 2.0, "b": 1.0, "c": 0.5}


# ---------------------------------------------------------------- run_tournament
def _pref_judge(a_text: str, b_text: str) -> float:
    """固定偏好（无平局）：文本序大者胜。"""
    return 1.0 if a_text > b_text else 0.0


def test_run_tournament_fixed_preference_champion():
    chapters = [{"id": f"c{i}", "text": f"rank-{i}"} for i in range(6)]
    res = run_tournament(chapters, _pref_judge, rounds=4, k=32, seed=0)
    rankings = res["rankings"]
    assert rankings[0]["id"] == "c5"
    assert rankings[0]["rank"] == 1
    assert rankings[0]["wins"] == 4
    elos = [r["elo"] for r in rankings]
    assert elos == sorted(elos, reverse=True)  # 排名按 Elo 降序
    for r in rankings:
        assert r["wins"] + r["losses"] == 4  # 偶数参赛者无轮空，打满 4 轮
    assert len(res["rounds_log"]) == 4
    first = res["rounds_log"][0][0]
    assert {"round", "a", "b", "winner"} <= set(first)


def test_run_tournament_deterministic_same_seed():
    chapters = [{"id": f"c{i}", "text": f"rank-{i}"} for i in range(5)]
    r1 = run_tournament(chapters, _pref_judge, rounds=4, seed=7)
    r2 = run_tournament(chapters, _pref_judge, rounds=4, seed=7)
    assert json.dumps(r1, sort_keys=True, ensure_ascii=False) == json.dumps(
        r2, sort_keys=True, ensure_ascii=False
    )


def test_run_tournament_champion_invariant_to_seed():
    chapters = [{"id": f"c{i}", "text": f"rank-{i}"} for i in range(6)]
    for seed in (0, 1, 42):
        res = run_tournament(chapters, _pref_judge, rounds=4, seed=seed)
        assert res["rankings"][0]["id"] == "c5"


def test_run_tournament_initial_elo_1500():
    def always_a(a_text: str, b_text: str) -> float:
        return 1.0

    chapters = [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]
    res = run_tournament(chapters, always_a, rounds=1, seed=0)
    total = sum(r["elo"] for r in res["rankings"])
    assert total == pytest.approx(3000.0)  # 初始各 1500，零和守恒
    assert sorted(r["elo"] for r in res["rankings"]) == [1484.0, 1516.0]


def test_run_tournament_truncates_3000_chars():
    seen: list[tuple[int, int]] = []

    def len_judge(a_text: str, b_text: str) -> float:
        seen.append((len(a_text), len(b_text)))
        return 1.0 if a_text.startswith("L") else 0.0

    chapters = [
        {"id": "long", "text": "L" + "x" * 5000},
        {"id": "short", "text": "S" + "y" * 10},
    ]
    run_tournament(chapters, len_judge, rounds=2, seed=0)
    assert seen[0] == (3000, 11)
    assert all(ln <= 3000 for pair in seen for ln in pair)


def test_run_tournament_no_draw_scores_binary():
    """judge_fn 返回非 0/1（如 0.9/0.1）→ 规约为无平局二值，强者仍胜。"""

    def fuzzy_judge(a_text: str, b_text: str) -> float:
        return 0.9 if a_text == "GOOD" else 0.1

    chapters = [{"id": "g", "text": "GOOD"}, {"id": "x", "text": "BAD"}]
    res = run_tournament(chapters, fuzzy_judge, rounds=1, seed=0)
    assert res["rankings"][0]["id"] == "g"
    assert res["rankings"][0]["wins"] == 1
    assert res["rankings"][1]["losses"] == 1


# ---------------------------------------------------------------- l1 --tournament 接线
def test_run_l1_tournament_stub(tmp_path):
    from nsc.eval.l1 import run_l1_tournament
    from nsc.judge.rubric_judge import load_rubric

    raw = {
        "episodes": [
            {"id": "e1", "title": "第一集", "logline": "弱开场"},
            {"id": "e2", "title": "第二集", "logline": "WIN 强开场"},
        ],
        "scenes": [],
        "beats": [],
    }

    class FakePairJudge:
        judge_ver = "stub"
        rubric = load_rubric()

        def judge_pair(self, dimension, context, a, b, *, seed=1):
            if "WIN" in a:
                w = "a"
            elif "WIN" in b:
                w = "b"
            else:
                w = "tie"
            call1 = JudgeDecision(winner=w, margin=1, cited_spans=["x"])
            call2 = JudgeDecision(winner="b" if w == "a" else "a", margin=1, cited_spans=["x"])
            return call1, call2, call1

    brief = tmp_path / "b.yaml"
    brief.write_text("profile: short_drama_v1\nbrand: demo_tea\n", "utf-8")
    out = run_l1_tournament(
        briefs=[brief],
        compile_runner=lambda _b: raw,
        judge=FakePairJudge(),
        out_dir=tmp_path,
        rounds=2,
        seed=0,
    )
    data = json.loads(out.read_text("utf-8"))
    assert data["rankings"][0]["id"] == "e2"  # 含 WIN 的章节夺冠
    assert out.name == "l1_tournament.json"


def test_run_l1_tournament_needs_two_chapters(tmp_path):
    from nsc.eval.l1 import run_l1_tournament

    raw = {"episodes": [{"id": "e1", "title": "唯一", "logline": "x"}]}
    brief = tmp_path / "b.yaml"
    brief.write_text("profile: p\nbrand: b\n", "utf-8")

    class AnyJudge:
        judge_ver = "stub"

        def judge_pair(self, dimension, context, a, b, *, seed=1):
            raise AssertionError("不应触发判官调用")

    with pytest.raises(ValueError):
        run_l1_tournament(
            briefs=[brief],
            compile_runner=lambda _b: raw,
            judge=AnyJudge(),
            out_dir=tmp_path,
        )
