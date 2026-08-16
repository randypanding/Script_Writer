"""分镜 CSV（T-08）。

按 Scene → Beat → Line 展开成逐行分镜表，供拍摄执行。列尽量贴近制作流程：
集/场/拍/类型/时长/情绪(效价,唤醒)/文本/角色/地点/日景夜。
"""

from __future__ import annotations

import csv
import io

from spec.ir.container import NarrativeIR

_HEADERS = [
    "ep_no", "scene", "beat_kind", "line_type", "est_duration_s",
    "valence", "arousal", "character", "location", "time_of_day", "text",
]


def _char_name(ir: NarrativeIR, char_id: str | None) -> str:
    if not char_id:
        return ""
    ch = next((c for c in ir.characters if c.id == char_id), None)
    return ch.name if ch else ""


def _loc_name(ir: NarrativeIR, loc_id: str) -> str:
    loc = next((x for x in ir.locations if x.id == loc_id), None)
    return loc.name if loc else ""


def to_storyboard_csv(ir: NarrativeIR) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_HEADERS)
    for ep in ir.episodes:
        for sc in (s for s in ir.scenes if s.parent_id == ep.id):
            sc_no = sc.order + 1
            for beat in (b for b in ir.beats if b.parent_id == sc.id):
                lines = [ln for ln in ir.lines if ln.parent_id == beat.id]
                if not lines:
                    writer.writerow(
                        [ep.no, sc_no, beat.beat_kind, "", round(beat.est_duration_s, 1),
                         round(beat.emotion.valence, 2), round(beat.emotion.arousal, 2),
                         "", _loc_name(ir, sc.location_id), sc.time_of_day, beat.summary]
                    )
                    continue
                for ln in lines:
                    writer.writerow(
                        [ep.no, sc_no, beat.beat_kind, ln.line_type, round(beat.est_duration_s, 1),
                         round(beat.emotion.valence, 2), round(beat.emotion.arousal, 2),
                         _char_name(ir, ln.character_id), _loc_name(ir, sc.location_id),
                         sc.time_of_day, ln.text]
                    )
    return buf.getvalue()