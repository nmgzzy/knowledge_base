# 本地知识库工具（第一版：Python CLI）

本仓库实现一个离线优先的本地知识库：Markdown 作为源数据，SQLite+FTS5 作为全文索引，可选 OpenAI-compatible embedding/chat 用于语义检索与问答。

## 快速开始

```bash
python -m kb init /path/to/my_kb
python -m kb add /path/to/doc.md --kb-root /path/to/my_kb
python -m kb index --kb-root /path/to/my_kb
python -m kb search "你的问题" --kb-root /path/to/my_kb --top 10
```

## 安装可执行文件（可选）

仓库提供一键脚本把 CLI 打包并安装到 PATH 目录（默认 `/usr/local/bin`）。为提升启动速度，默认使用 `onedir` 方案（安装一个运行目录 + 在 `INSTALL_DIR` 放一个 `kb` 入口软链接）。如需单文件，可切换为 `onefile`。

```bash
bash scripts/build_and_install.sh
```

常用环境变量：

- `INSTALL_DIR`：安装目录（默认 `/usr/local/bin`）
- `INSTALL_PAYLOAD_DIR`：`onedir` 运行目录（默认根据 `INSTALL_DIR` 推导为 `/usr/local/lib/kb`）
- `NO_SUDO=1`：不使用 sudo（适合安装到用户目录）
- `KEEP_BUILD=1`：保留临时目录用于排查（默认安装成功后会清理）
- `STAGING_DIR`：临时目录（默认 `.build/kb-packaging`）
- `BUNDLE_MODE`：打包模式 `onedir|onefile`（默认 `onedir`）

例如不使用 sudo，安装到项目内的 `.local/bin`：

```bash
NO_SUDO=1 INSTALL_DIR="$PWD/.local/bin" bash scripts/build_and_install.sh
```

如果你需要单文件（启动通常更慢）：

```bash
BUNDLE_MODE=onefile bash scripts/build_and_install.sh
```

卸载：

```bash
bash scripts/build_and_install.sh uninstall
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
