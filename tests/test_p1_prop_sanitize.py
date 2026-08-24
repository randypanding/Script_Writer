"""p1_bible Prop 归一(round12b:NPC 显式 sku_ref=null 致 NarrativeIR ValidationError)。"""
from nsc.passes.p1_bible import _sanitize_props


def test_sku_ref_none_filled():
    props = [{"name": "茶叶罐", "sku_ref": None}, {"name": "茶壶", "sku_ref": "tea-01"}]
    out = _sanitize_props(props)
    assert out[0]["sku_ref"] == "" and out[1]["sku_ref"] == "tea-01"


def test_non_list_passthrough():
    assert _sanitize_props(None) is None
    assert _sanitize_props("x") == "x"
