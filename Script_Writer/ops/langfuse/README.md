# Langfuse 本地部署（T-01）

观测追踪：每个 LLM 调用写 provenance 并上报 Langfuse trace。

## 启动
```bash
docker compose -f ops/langfuse/docker-compose.yml up -d
```

## 环境变量
- `LANGFUSE_HOST`（默认 `http://localhost:3000`）
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`（首次启动时从 UI 创建项目获取）

## 说明
- 不用 Langfuse 可用 `LANGFUSE_ENABLED=false` 或 `NSC_NO_TELEMETRY=1` 关闭，不影响编译。
- docker 未安装时跳过本目录，不影响 `make ci-local`。