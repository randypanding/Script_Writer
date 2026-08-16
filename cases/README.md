# cases/ —— A4 证据层

## 真相在 `export/`，不在 `cases.db`（D28）
```
cases/
  export/
    cases.jsonl              # 一行一个 case
    ir_snapshots.jsonl       # 一行一个 IR 快照（ir_json 内联）
    feedback.jsonl
    revision_pairs.jsonl
    preference_pairs.jsonl
    judge_calibration.jsonl
    retrieval_items.jsonl
  attachments/               # git-lfs：客户回收的 docx、原始批注截图
  cases.db                   # gitignored，由 make db-rebuild 生成
```

`make db-export` 在每次写入后自动调用（CLI 内置），所以 git 里始终是最新真相。
`make db-rebuild` 在任何机器上从 jsonl 重建 db。**重装机器 / 换语言重写系统时，只需要 export/ 这一个目录。**

## 为什么不用 Postgres
1 人开发、单机、数据量 <10 万行、需要进 git 做 review。SQLite 是唯一正确答案（D-技术栈）。

## 编号
`case:NNNN` 四位递增，由 `nsc db next-case-id` 分配。**永不复用。**