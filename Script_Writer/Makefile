.PHONY: install lint fmt typecheck spec-guard test test-fast golden ci-local \
        db-rebuild db-export eval-l1 judge-cal mine optimize prompts-verify budgets dash

install:            ; uv sync --all-extras
fmt:                ; uv run ruff format . && uv run ruff check --fix .
lint:               ; uv run ruff format --check . && uv run ruff check .
typecheck:          ; uv run pyright

spec-guard:         ## 资产层完整性门禁（无 LLM）
	uv run python -m nsc.guards.spec_reduction     # D2：每条 spec 语句必须可归约
	uv run python -m nsc.guards.checks_schema      # 规则 schema + ID 唯一 + evidence 必填
	uv run python -m nsc.guards.prompts_untouched  # prompts/ 未被手改
	uv run python -m nsc.guards.ir_schema_diff     # IR breaking change 必须带 migration+ADR
	uv run python -m nsc.guards.budgets            # 行数预算 D21
	uv run python -m nsc.guards.rules_conflict     # canonical 规则冲突/重复
	uv run python -m nsc.guards.db_export_fresh    # db ↔ jsonl 一致（ADR-0006）

budgets:            ; uv run python -m nsc.guards.budgets
prompts-verify:     ; uv run python -m nsc.guards.prompts_untouched
db-export-fresh:    ; uv run python -m nsc.guards.db_export_fresh

test-fast:          ## PR 阻塞集：无 LLM
	uv run pytest -m "not llm" -n auto
golden:             ; uv run pytest -m golden -n auto
test:               ; uv run pytest -n auto

ci-local: lint typecheck spec-guard test-fast

db-rebuild:         ; uv run nsc db rebuild        # cases/export/*.jsonl -> cases/cases.db
db-export:          ; uv run nsc db export         # cases.db -> cases/export/*.jsonl (git 真相)

eval-l1:            ; uv run nsc eval l1 --sample $${SAMPLE:-12}
judge-cal:          ; uv run nsc judge calibrate --report out/judge_calibration.md
mine:               ; uv run nsc mine run --open-pr
optimize:           ; uv run nsc optimize --pass $${PASS:-p5_dialogue} --auto light
dash:               ; uv run nsc metrics weekly --write docs/metrics/