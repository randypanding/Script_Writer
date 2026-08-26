"""ir_io.save 的 datetime 序列化回归(实证 round20 南浪仔 attempt1:全部门禁通过后
死于 ir.json 导出 TypeError: Object of type datetime is not JSON serializable)。"""

import json
from datetime import UTC, datetime

from nsc.runtime.ir_io import save
from spec.ir.container import NarrativeIR, Project, Provenance


def _ir_with_provenance() -> NarrativeIR:
    project = Project(
        id="01M0TEST000000000000000001",
        title="测试",
        profile_id="pp",
        brand_id="bb",
        provenance_id="r1",
        logline="测试故事",
    )
    prov = Provenance(
        run_id="r1",
        pass_name="p0_intake",
        spec_sha="s",
        profile_ver="1",
        brand_ver="1",
        ruleset_ver="1",
        promptset_ver="1",
        model_id="m",
        temperature=0.7,
        seed=1,
        input_hash="h",
        created_at=datetime.now(UTC),
    )
    return NarrativeIR(project=project, provenance=[prov])


def test_save_serializes_datetime_provenance(tmp_path):
    out = tmp_path / "ir.json"
    save(_ir_with_provenance(), out)
    data = json.loads(out.read_text("utf-8"))
    assert data["provenance"][0]["created_at"]  # datetime → ISO 字符串,不再 TypeError
    assert isinstance(data["provenance"][0]["created_at"], str)
