# 本地知识库工具（第一版：Python CLI）

本仓库实现一个离线优先的本地知识库：Markdown 作为源数据，SQLite+FTS5 作为全文索引，可选 OpenAI-compatible embedding/chat 用于语义检索与问答。

## 快速开始

```bash
python -m kb init /path/to/my_kb
python -m kb add /path/to/doc.md --kb-root /path/to/my_kb
python -m kb index --kb-root /path/to/my_kb
python -m kb search "你的问题" --kb-root /path/to/my_kb --top 10
```

## 配置

初始化会生成 `kb_config.json`。如需启用问答或语义检索，配置：

- `openai_compat.base_url`
- `openai_compat.api_key_env`（默认 `KB_OPENAI_API_KEY`）
- `openai_compat.model_chat`
- `openai_compat.model_embed`

## 引用

任何 search/ask 输出都包含：

- `path`
- `heading_path`
- `line_range`

