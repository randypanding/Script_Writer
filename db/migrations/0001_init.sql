-- db/migrations/0001_init.sql
-- A4 证据层。真相在 cases/export/*.jsonl（D28），本库是可重建的工作副本。
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);

-- 一次交付 = 一个 case
CREATE TABLE cases (
  case_id       TEXT PRIMARY KEY,             -- 'case:0142'
  brand_id      TEXT NOT NULL,
  profile_id    TEXT NOT NULL,
  industry      TEXT NOT NULL,
  title         TEXT NOT NULL,
  source        TEXT NOT NULL CHECK(source IN ('client','reverse_annotation','synthetic')),
  source_url    TEXT DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','delivered','accepted','rejected','archived')),
  accepted_at   TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE ir_snapshots (
  snapshot_id   TEXT PRIMARY KEY,
  case_id       TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK(kind IN ('generated','human_revised','golden','annotated')),
  round         INTEGER NOT NULL DEFAULT 1,
  ir_json       TEXT NOT NULL,
  spec_sha      TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

-- 扁平节点表：让"按节点检索/统计"变成 SQL 而不是 Python 遍历
CREATE TABLE nodes (
  node_id       TEXT NOT NULL,
  snapshot_id   TEXT NOT NULL REFERENCES ir_snapshots(snapshot_id) ON DELETE CASCADE,
  case_id       TEXT NOT NULL,
  kind          TEXT NOT NULL,
  parent_id     TEXT,
  linear_index  INTEGER,
  episode_no    INTEGER,
  beat_kind     TEXT,
  payload_json  TEXT NOT NULL,
  text          TEXT DEFAULT '',
  PRIMARY KEY (snapshot_id, node_id)
);
CREATE INDEX idx_nodes_case_kind ON nodes(case_id, kind);
CREATE INDEX idx_nodes_beatkind ON nodes(beat_kind);

-- D9 反馈五元组
CREATE TABLE feedback (
  feedback_id     TEXT PRIMARY KEY,
  case_id         TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  target_node_id  TEXT,
  anchor_level    TEXT NOT NULL CHECK(anchor_level IN ('bookmark','appendix','fuzzy','failed')),
  anchor_conf     REAL NOT NULL DEFAULT 0,
  dimension       TEXT NOT NULL CHECK(dimension IN
                    ('structural','character','placement','dialogue','factual',
                     'compliance','producibility','taste')),
  verdict         TEXT NOT NULL CHECK(verdict IN ('accept','reject','revise','praise')),
  severity        INTEGER NOT NULL CHECK(severity BETWEEN 1 AND 5),
  rationale_nl    TEXT DEFAULT '',
  original_text   TEXT DEFAULT '',
  revised_text    TEXT DEFAULT '',
  edit_type       TEXT,
  author          TEXT DEFAULT '',
  confirmed_by    TEXT DEFAULT '',              -- 人工确认者；空 = 仅 LLM 猜测，不得进 L1 聚类
  created_at      TEXT NOT NULL
);
CREATE INDEX idx_feedback_dim ON feedback(dimension, created_at);

CREATE TABLE revision_pairs (
  pair_id     TEXT PRIMARY KEY,
  feedback_id TEXT NOT NULL REFERENCES feedback(feedback_id) ON DELETE CASCADE,
  unit_kind   TEXT NOT NULL,
  context_json TEXT NOT NULL,
  before_text TEXT NOT NULL,
  after_text  TEXT NOT NULL,
  dimension   TEXT NOT NULL,
  split       TEXT NOT NULL DEFAULT 'train' CHECK(split IN ('train','val','test'))
);

CREATE TABLE preference_pairs (
  pair_id    TEXT PRIMARY KEY,
  case_id    TEXT NOT NULL,
  unit_kind  TEXT NOT NULL,
  a_text     TEXT NOT NULL,
  b_text     TEXT NOT NULL,
  context_json TEXT NOT NULL,
  human_pref TEXT NOT NULL CHECK(human_pref IN ('a','b','tie')),
  dimension  TEXT NOT NULL,
  origin     TEXT NOT NULL CHECK(origin IN ('revision','regeneration','counterexample')),
  split      TEXT NOT NULL DEFAULT 'train' CHECK(split IN ('train','val','test'))
);

CREATE TABLE judge_scores (
  score_id   TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  pair_id    TEXT,
  unit_id    TEXT,
  dimension  TEXT NOT NULL,
  mode       TEXT NOT NULL CHECK(mode IN ('pairwise','absolute')),
  verdict    TEXT NOT NULL,
  margin     INTEGER,
  rationale  TEXT DEFAULT '',
  cited_spans_json TEXT DEFAULT '[]',
  judge_ver  TEXT NOT NULL,
  model_id   TEXT NOT NULL,
  swapped    INTEGER NOT NULL DEFAULT 0,
  invalid    INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE judge_calibration (
  item_id     TEXT PRIMARY KEY,
  pair_id     TEXT,
  dimension   TEXT NOT NULL,
  human_verdict TEXT NOT NULL,
  human_score  INTEGER,
  source      TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

-- A5 规则台账（git 中的 yaml 是真相，此表用于命中统计）
CREATE TABLE rules (
  rule_id     TEXT PRIMARY KEY,
  level       TEXT NOT NULL,
  statement   TEXT NOT NULL,
  scope_kind  TEXT NOT NULL,
  scope_value TEXT DEFAULT '',
  form        TEXT NOT NULL,
  target      TEXT DEFAULT '',
  dimension   TEXT DEFAULT '',
  hit_count   INTEGER NOT NULL DEFAULT 0,
  effect_size REAL,
  created_at  TEXT NOT NULL,
  last_fired_at TEXT,
  superseded_by TEXT
);

CREATE TABLE rule_hits (
  hit_id    TEXT PRIMARY KEY,
  rule_id   TEXT NOT NULL,
  check_id  TEXT NOT NULL,
  case_id   TEXT NOT NULL,
  node_id   TEXT,
  run_id    TEXT NOT NULL,
  severity  TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_rule_hits_rule ON rule_hits(rule_id, created_at);

-- D20 Provenance
CREATE TABLE runs (
  run_id        TEXT PRIMARY KEY,
  case_id       TEXT,
  pass_name     TEXT NOT NULL,
  spec_sha      TEXT NOT NULL,
  profile_ver   TEXT NOT NULL,
  brand_ver     TEXT NOT NULL,
  ruleset_ver   TEXT NOT NULL,
  promptset_ver TEXT NOT NULL,
  model_id      TEXT NOT NULL,
  temperature   REAL NOT NULL,
  seed          INTEGER,
  input_hash    TEXT NOT NULL,
  cache_hit     INTEGER NOT NULL DEFAULT 0,
  tokens_in     INTEGER DEFAULT 0,
  tokens_out    INTEGER DEFAULT 0,
  cost_usd      REAL DEFAULT 0,
  wall_ms       INTEGER DEFAULT 0,
  langfuse_trace_id TEXT DEFAULT '',
  created_at    TEXT NOT NULL
);

-- 1 档检索池
CREATE TABLE retrieval_items (
  item_id     TEXT PRIMARY KEY,
  case_id     TEXT NOT NULL,
  node_id     TEXT,
  unit_kind   TEXT NOT NULL,          -- beat_sequence | scene_card | dialogue_block | chapter
  industry    TEXT NOT NULL,
  profile_id  TEXT NOT NULL,
  brand_id    TEXT DEFAULT '',
  quality     REAL NOT NULL DEFAULT 0,   -- 人类接受 = 1.0；判官高分 = 0.6…
  content     TEXT NOT NULL,
  meta_json   TEXT NOT NULL DEFAULT '{}',
  usable_as_example INTEGER NOT NULL DEFAULT 1,  -- COMPLIANCE：逆向标注片段=0
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_retrieval ON retrieval_items(unit_kind, industry, profile_id, quality DESC);

CREATE VIRTUAL TABLE retrieval_vec USING vec0(
  item_id TEXT PRIMARY KEY, embedding FLOAT[1024]
);

CREATE TABLE observations_index (
  obs_id     TEXT PRIMARY KEY,
  feedback_id TEXT NOT NULL,
  cluster_id TEXT,
  yaml_path  TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE metrics_weekly (
  week          TEXT PRIMARY KEY,          -- '2025-W03'
  structural_edit_rate REAL,               -- D22 北极星
  first_pass_rate      REAL,
  edit_rate_json       TEXT,               -- 按 D11 八类分解
  judge_agreement_json TEXT,
  rule_net_gain_json   TEXT,
  retrieval_hit_rate   REAL,
  retrieval_gain       REAL,
  cost_per_episode_usd REAL,
  minutes_per_episode  REAL,
  computed_at   TEXT NOT NULL
);

INSERT OR REPLACE INTO schema_meta(version, applied_at) VALUES (1, datetime('now'));