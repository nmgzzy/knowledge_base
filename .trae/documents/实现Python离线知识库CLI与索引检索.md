# 实现 Python 离线知识库 CLI 与索引检索（第一版）

## 核心交付（优先 Python，不做 Flutter）
- 目录结构：`kb/` 源数据、`kb_index/` SQLite+FTS 索引、`kb_vector/` 向量缓存（可重建）、`kb_config.json` 配置。
- CLI：`kb init/add/index/search/ask/repair`。
- 追溯引用：任何 search/ask 输出都包含 `path + heading_path + line_range`。
- 混合检索：FTS5 关键词召回 + 向量召回融合重排。

## 第一版的大模型接口（明确按你要求：OpenAI 兼容、可配置）
### 支持的 API 形态
- **Chat**：`POST {base_url}/v1/chat/completions`
- **Embedding**：`POST {base_url}/v1/embeddings`
- 非流式（第一版先实现同步返回）；超时、重试（指数退避）与错误码处理。

### 可配置项（写入 kb_config.json，允许环境变量覆盖 key）
- `openai_compat.base_url`：例如 `http://localhost:11434` 或任意 OpenAI-compatible 网关
- `openai_compat.api_key_env`：默认 `KB_OPENAI_API_KEY`
- `openai_compat.model_chat`：用于 `kb ask` 与 `kb add --auto`
- `openai_compat.model_embed`：用于向量生成
- `openai_compat.timeout_s`、`openai_compat.max_retries`
- 可选：自定义 header（如某些网关需要额外 header），第一版做简单 key/value 注入

## `kb add --auto`（LLM 自动分类与 meta 生成）
- 启用方式：`kb add <file> --auto`。
- 行为：
  1) 扫描现有目录 `meta.json`，生成候选目录概览（title/summary/tags/keywords/dir_type）。
  2) 读取文档内容（控制长度：frontmatter + 标题列表 + 前 N 行/字符）。
  3) 调用 **OpenAI-compatible chat**，要求输出严格 JSON：
     - `doc_title/doc_summary/tags/keywords`
     - `suggested_rel_dir`（相对 kb 根目录）
     - `suggested_filename`（可选）
     - `dir_meta`（可选：用于生成/补全目标目录 meta.json）
  4) 落盘：创建目录（若不存在）→ 写/合并 `meta.json`（保留手写字段，自动字段合并）→ 将文档存入建议路径。
  5) 若 LLM 未配置或失败：退化为启发式分类（关键词匹配目录 meta），仍保证命令可用。

## 索引与检索实现（SQLite）
- Schema：`docs/chunks/chunks_fts/embeddings/dir_meta_cache/audit_log`。
- Chunk：按 Markdown 标题栈生成 `heading_path`，并记录 chunk 的 `start_line/end_line` 与 `text_hash`。
- 增量更新：以 `content_hash`（sha256）判断变化；事务内替换该 doc 的 chunks/embeddings；缺失文件级联清理。
- 检索：结构召回（目录 meta + doc 标题/摘要/标签）→ 内容召回（FTS topK + 向量 topK）→ 线性融合重排 → 输出引用。

## 代码落地（将新建的主要文件）
- `pyproject.toml`：打包与 console script `kb`。
- `kb/` 包：`cli.py/config.py/store_sqlite.py/chunking.py/scan.py/search.py/embed.py/llm_openai_compat.py/auto_add.py/ask.py/repair.py`。

## 验证（实现后会执行）
- 用几篇示例 Markdown 走通：`kb init → kb add --auto → kb index → kb search/ask --json`。
- 验证引用定位（行号范围正确）、删除文件后的级联清理与 `kb repair --fix`。

## 先不做（但留好扩展点）
- Flutter 前端
- 高级 ANN 向量后端、重排模型、rename 精准识别、wiki link 图谱
