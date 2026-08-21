"""验证单个规则 fixture：`uv run python -m scripts.verify_fixture <RULE-ID> <pass|fail>`

打印该 fixture 是否触发规则、是否报错。供 fixture 生成时快速自检。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from nsc.checker.interpreter import RuleSet, evaluate
from nsc.runtime.ir_io import build_view


def main() -> int:
    rid, which = sys.argv[1], sys.argv[2]
    prof = yaml.safe_load(Path("profiles/short_drama_v1.yaml").read_text("utf-8"))
    brand = yaml.safe_load(Path("brands/demo_tea/brand.yaml").read_text("utf-8"))
    rule_path = next(Path("spec/checks").rglob(f"{rid}.yaml"))
    rule = yaml.safe_load(rule_path.read_text("utf-8"))
    raw = json.loads(Path(f"tests/fixtures/checks/{rid}/{which}.json").read_text("utf-8"))
    view = build_view(raw, prof, brand)
    rs = RuleSet.load(
        profile_id="short_drama_v1",
        industry="beverage",
        brand_id="demo_tea",
        stage=rule["stage"],
        enabled_domains=[rule["domain"]],
    )
    rs.rules = [rule]
    rep = evaluate(rs, view, ctx={"profile": prof, "brand": brand})
    fired = any(f.rule_id == rid for f in rep.findings)
    print(f"{rid}/{which}: errors={rep.errors}")
    print(f"{rid}/{which}: fired={fired} (期望 {which == 'fail'})")
    return 0 if (not rep.errors) and (fired == (which == "fail")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
