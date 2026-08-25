"""round19:CMP-001 绝对化用语机械替换 + p1 必填 str 空串占位(实证 round18
attempt2 全量产物死于 final 门「唯一」;round18 attempt1 characters.4.need 空串)。"""
from nsc.passes.p1_bible import _null_str_fields_to_default
from nsc.passes.pipeline import _absolute_terms, _sanitize_absolute_terms
from spec.ir.overlays import Character


def _st():
    return {
        "lines": [{"id": "l1", "text": "这是唯一不加糖的茶", "character_id": "唯一不动id键"}],
        "beats": [{"id": "b1", "summary": "唯一的转折", "beat_kind": "climax"}],
        "scenes": [{"id": "s1", "goal": "绝无仅有的目标"}],
        "chapters": [{"id": "c1", "title": "唯一的一章", "paragraphs": ["唯一真爱", "普通段落"]}],
        "episodes": [{"id": "e1", "title": "最佳下午"}],
    }


def test_sanitize_replaces_all_text_fields():
    n = _sanitize_absolute_terms(_st(), ["唯一", "绝无", "最佳"])
    st = _st()
    n = _sanitize_absolute_terms(st, ["唯一", "绝无", "最佳"])
    assert n == 6  # lines 1 + beats 1 + scenes 1 + chapters(title 1+paragraph 1) + episodes 1
    assert "少有" in st["lines"][0]["text"]
    assert "少有" in st["beats"][0]["summary"]
    assert "难有" in st["scenes"][0]["goal"]
    assert st["chapters"][0]["title"] == "少有的一章"
    assert st["chapters"][0]["paragraphs"][0] == "少有真爱"
    assert st["episodes"][0]["title"] == "上佳下午"


def test_sanitize_never_touches_id_like_keys():
    st = _st()
    _sanitize_absolute_terms(st, ["唯一"])
    assert st["lines"][0]["character_id"] == "唯一不动id键"
    assert st["lines"][0]["id"] == "l1"


def test_sanitize_no_match_returns_zero():
    assert _sanitize_absolute_terms({"lines": [{"text": "普通文本"}]}, ["唯一"]) == 0


def test_absolute_terms_loads_yaml():
    terms = _absolute_terms()
    assert "唯一" in terms  # spec/checks/compliance/_absolute_terms.yaml 词表


def test_p1_empty_string_required_str_placeholder():
    chars = [{"name": "小满", "need": "", "role": "protagonist"}]
    out = _null_str_fields_to_default(chars, Character)
    assert out[0]["need"] == "（未填）"  # 必填 str 空串 → 占位(string_too_short 实证)
    assert out[0]["name"] == "小满"  # 非空不动


def test_p1_null_still_default():
    chars = [{"name": "小满", "need": None, "role": "protagonist"}]
    out = _null_str_fields_to_default(chars, Character)
    # Optional 字段(need 默认 None)的 null 原样保留——pydantic 接受 None,无需归一
    assert out[0]["need"] is None
