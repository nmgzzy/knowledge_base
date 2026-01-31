# 本地知识库工具（Python CLI，离线优先）

一个可本地运行、可用 Git 管理的知识库工具：用文件夹树 + Markdown 存储“源数据”，用 SQLite（FTS5）做全文检索，并提供按段落 chunk 的引用定位；可选接入 OpenAI-compatible 的 embedding/chat，用于语义检索与强制带引用的问答。

相关设计与进度文档：
- 需求说明： [doc/需求文档.md](doc/需求文档.md)
- 当前实现进度： [doc/实现进度.md](doc/实现进度.md)

## 特性

- 离线优先：默认不依赖任何在线服务（不启用语义/问答即可）
- 源数据可控：Markdown + 目录 `meta.json`，可读可编辑、可备份/可迁移
- 可追溯引用：检索/问答返回 `path + heading_path + line_range`
- 增量更新：按内容 hash 检测变更；删除会级联清理 chunks/fts/embeddings
- 多种检索方式：
  - 全文：SQLite FTS5（BM25）
  - 语义（可选）：OpenAI-compatible embeddings（第一版为全表扫描）
  - 融合（可选）：FTS + 向量分数简单融合
- 自动归档（可选）：`kb add --auto` 调用 LLM 生成摘要/关键词并推荐目录，失败自动降级到 inbox

## 快速开始

本仓库既支持直接以模块方式运行，也支持安装成命令 `kb`。

```bash
# 方式 A：直接运行（无需安装）
python -m kb init /path/to/my_kb
python -m kb add /path/to/doc.md --kb-root /path/to/my_kb
python -m kb index --kb-root /path/to/my_kb
python -m kb search "你的问题" --kb-root /path/to/my_kb --top 10

# 方式 B：安装后使用 kb 命令（见下文“安装”）
# kb init /path/to/my_kb
```

## 目录结构

### 仓库结构（本项目代码）

- `kb/`：CLI 与核心实现（索引、检索、问答、导入、chunk 切分、SQLite 存储）
- `scripts/`：打包与安装脚本（PyInstaller）
- `tests/`：单元测试与端到端测试
- `doc/`：需求与实现进度文档

### 初始化后的知识库根目录（你的知识库数据）

执行 `kb init <kb_root>` 会创建（名称可在 `kb_config.json` 配置）：

```
<kb_root>/
  kb/            # 知识树源数据（Markdown + 每目录 meta.json）
  kb_index/      # 索引数据库（SQLite，可重建）
  kb_vector/     # 预留向量缓存目录（第一版主要写入 SQLite 的 embeddings 表）
  kb_config.json # 全局配置
```

## 用法

### 命令概览

| 命令 | 作用 | 备注 |
| --- | --- | --- |
| `kb init <kb_root>` | 初始化知识库根目录结构 | `--force` 覆盖配置 |
| `kb add <path> --kb-root <kb_root>` | 导入文件或目录到知识树 | `--dest` 指定目标目录；`--auto` 自动归档；`--move` 移动源文件 |
| `kb index --kb-root <kb_root>` | 构建/增量更新索引 | `--rebuild` 重建；`--embed` 写入 embedding；`--only` 仅更新指定 rel_path |
| `kb search "<query>" --kb-root <kb_root>` | 检索 chunk 段落 | 默认全文；`--semantic` 语义；`--hybrid` 融合 |
| `kb ask "<query>" --kb-root <kb_root>` | 问答（强制带引用） | `--top-context` 控制检索条数 |
| `kb tree --kb-root <kb_root>` | 列出知识树文档 | `--depth` 限制深度 |
| `kb repair --kb-root <kb_root>` | 修复一致性（第一版=重建） | 可配合 `--embed` |
| `kb doctor --kb-root <kb_root>` | 检测 OpenAI-compatible 接口可用性 | 默认检测 chat+embeddings，可用 `--chat/--embed` |

所有命令均支持 `--json` 方便脚本集成。

### 常见示例

导入一个目录（递归）并增量索引：

```bash
kb add /path/to/docs --kb-root /path/to/my_kb
kb index --kb-root /path/to/my_kb
```

查看目录树（纯文本）：

```bash
kb tree --kb-root /path/to/my_kb --depth 2
```

以 JSON 形式检索并拿到引用定位信息：

```bash
kb search "向量检索" --kb-root /path/to/my_kb --top 5 --json
```

返回结构（节选）：

```json
{
  "query": "向量检索",
  "results": [
    {
      "path": "项目/设计.md",
      "heading_path": "H1 > H2",
      "line_range": [120, 168],
      "score": 0.42,
      "source": "fts",
      "text": "..."
    }
  ]
}
```

启用问答（需要配置 OpenAI-compatible chat）：

```bash
kb ask "这个项目的索引是怎么做增量更新的？" --kb-root /path/to/my_kb --hybrid --json
```

## 运行环境

- Python >= 3.9
- `sqlite3` 需支持 FTS5（大多数官方 Python 发行版默认支持）；若遇到 `no such module: fts5`，请更换带 FTS5 的 Python/SQLite

## 安装

### 方式 1：作为 Python 包安装（推荐用于开发/可编辑安装）

本项目无强制第三方依赖，要求 Python >= 3.9。

```bash
python -m pip install -e .
kb --help
```

### 方式 2：打包成可执行文件并安装到 PATH（可选）

仓库提供一键脚本把 CLI 打包并安装到 PATH 目录（默认 `/usr/local/bin`）。默认使用 `onedir`（一个运行目录 + 一个入口软链接）以提升启动速度；如需单文件可切换为 `onefile`。

```bash
bash scripts/build_and_install.sh
```

常用环境变量：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `INSTALL_DIR` | 安装目录 | `/usr/local/bin` |
| `INSTALL_PAYLOAD_DIR` | `onedir` 运行目录 | 根据 `INSTALL_DIR` 推导（通常是 `/usr/local/lib/kb`） |
| `NO_SUDO=1` | 不使用 sudo（安装到用户目录常用） | 空 |
| `KEEP_BUILD=1` | 保留临时目录便于排查 | 空 |
| `STAGING_DIR` | 临时目录 | `.build/kb-packaging` |
| `BUNDLE_MODE` | `onedir` 或 `onefile` | `onedir` |

例如不使用 sudo，安装到项目内的 `.local/bin`：

```bash
NO_SUDO=1 INSTALL_DIR="$PWD/.local/bin" bash scripts/build_and_install.sh
```

卸载：

```bash
bash scripts/build_and_install.sh uninstall
```

## 配置

初始化会生成 `<kb_root>/kb_config.json`。不配置任何在线模型也能使用全文检索；仅当启用 `--embed / --semantic / --hybrid / ask / add --auto` 时才需要配置 OpenAI-compatible 接口。

### `kb_config.json` 关键字段

```json
{
  "schema_version": 1,
  "paths": { "kb": "kb", "index": "kb_index", "vector": "kb_vector" },
  "meta_filename": "meta.json",
  "chunking": { "max_chars": 1200, "overlap_chars": 150, "min_chars": 20 },
  "openai_compat": {
    "base_url": "",
    "api_key_env": "KB_OPENAI_API_KEY",
    "model_chat": "",
    "model_embed": "",
    "timeout_s": 60,
    "max_retries": 2,
    "extra_headers": {}
  }
}
```

### OpenAI-compatible（语义检索/问答/自动归档）

- `openai_compat.base_url`：例如 `https://api.openai.com` 或任何兼容 `/v1/embeddings`、`/v1/chat/completions` 的服务
- `openai_compat.model_embed`：embedding 模型名（用于 `kb index --embed`、`kb search --semantic/--hybrid`）
- `openai_compat.model_chat`：chat 模型名（用于 `kb ask`、`kb add --auto`）
- API Key：默认从环境变量读取（`openai_compat.api_key_env`，默认 `KB_OPENAI_API_KEY`）

```bash
export KB_OPENAI_API_KEY="***"
```

## 工作原理（简述）

- 源数据：知识以 `kb/` 下的 Markdown 文件保存，每个目录维护一个 `meta.json`
- Chunk 切分：按标题栈（`H1 > H2 > ...`）与段落切分，并记录 `start_line/end_line`
- 索引：写入 `kb_index/index.sqlite`，包含 docs/chunks/FTS 表，以及可选的 embeddings 表
- 检索：
  - 默认使用 FTS5（BM25）召回 chunk
  - 语义检索（可选）对已存 embedding 计算相似度（第一版为全表扫描）
  - 融合检索对两路结果做轻量合并与排序
- 引用：所有 search/ask 返回都带 `path / heading_path / line_range`，便于跳回原文

## 开发与测试

运行全部测试：

```bash
python -m unittest discover -s tests
```

覆盖率（标准库 `trace`，输出 `kb.*` 模块统计）：

```bash
python tests/run_coverage_trace.py
```

## Roadmap / TODO

来自 [doc/实现进度.md](doc/实现进度.md) 的后续计划（摘选）：

- 索引一致性与更强原子切换（双库/版本表/临时表切换）
- 更完整的变更检测（rename/move 识别、扫描缓存）
- 可插拔向量后端与 ANN 加速（当前语义检索为全表扫描）
- 结构召回与 rerank（先缩小候选再重排）
- 链接关系解析增强与图谱导航
- `kb repair` 更精细的健康检查与修复能力
- 安全与可观测性增强（避免日志输出敏感内容）
- Flutter 前端与稳定本地接口（后续）

## License

MIT License，见 [LICENSE](LICENSE)。
