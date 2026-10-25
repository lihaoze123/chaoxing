# chaoxing

超星课程学习命令行工具，支持视频、音频、文档、阅读和空章节访问，并可通过 Telegram 推送学习结果。

测验、直播及其他不支持的任务会跳过并列入结果汇总。需要先完成测验才能解锁的章节，由你手动处理后重新运行。

## 运行

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)。项目使用 Python 3.13+，uv 可自动安装所需 Python。

```sh
uv sync --locked
cp config.example.toml config.toml
# 编辑 config.toml，填写账号及需要的课程 ID
uv run chaoxing --list-courses
uv run chaoxing
```

默认读取当前目录的 `config.toml`。使用其他路径：

```sh
uv run chaoxing --config /path/to/config.toml
uv run chaoxing --courses 2151141,189191 --speed 1.5
uv run chaoxing --help
```

`study.course_ids = []` 表示处理所有课程。指定了不存在的课程 ID 会报错。同一课程在不同班级下分别处理。

账号密码可以写在 TOML 或环境变量中。交互运行缺少凭证时会提示输入，密码隐藏；非交互运行缺少凭证直接退出。启用 `account.use_cookies = true` 后，从 `cookies_file` 读取浏览器 Cookie；Cookie 失效且已配置账号密码时，尝试重新登录。密码登录成功会保存 Cookie。相对 Cookie 路径以配置文件所在目录为基准；未使用配置文件时以当前目录为基准。

## 环境变量

优先级：默认值 < TOML < 环境变量 < 显式命令行参数。不会自动读取 `.env`；需要时使用 `uv run --env-file .env chaoxing`。

| 变量 | 对应配置 |
| --- | --- |
| `CHAOXING_USERNAME` | `account.username` |
| `CHAOXING_PASSWORD` | `account.password` |
| `CHAOXING_USE_COOKIES` | `account.use_cookies` |
| `CHAOXING_COOKIES_FILE` | `account.cookies_file` |
| `CHAOXING_COURSE_IDS` | `study.course_ids`，逗号分隔 |
| `CHAOXING_SPEED` | `study.speed`，1 到 2 |
| `CHAOXING_MAX_ATTEMPTS` | `study.max_attempts`，至少 1 |
| `CHAOXING_RETRY_INTERVAL` | `study.retry_interval`，非负秒数 |
| `TELEGRAM_BOT_TOKEN` | `telegram.bot_token` |
| `TELEGRAM_CHAT_ID` | `telegram.chat_id` |
| `TELEGRAM_API_BASE` | `telegram.api_base` |

## Telegram 与 OCR

Telegram 是唯一的推送方式。`bot_token` 和 `chat_id` 同时留空则关闭推送；两项必须同时配置，`chat_id` 在 TOML 中也要加引号。每轮结束发送结果和未完成项；启动失败或手动中断也会通知。推送失败只记日志，不影响学习结果。消息使用纯文本，过长时自动分段。

学习接口和 Telegram 均支持标准 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 环境变量，包括 SOCKS 代理。需要中转时设置 `telegram.api_base` 为 Bot API 基础地址。

默认安装不含 OCR。遇到验证码或 403 拦截会记录失败，继续处理其余任务。需要自动识别时：

```sh
uv sync --locked --extra ocr
uv run --extra ocr chaoxing
```

OCR 仅在遇到拦截时初始化，最多尝试三次。识别失败需要手动验证。完成手动测验、解锁或验证后再次运行，会读取平台当前完成状态和媒体进度。

交互终端显示课程表格、媒体进度条和结果表格，非交互运行输出普通日志。最终汇总包含完成、跳过和失败项；有未完成项时会明确提示。媒体到结尾后最多上报五次。

| 退出码 | 含义 |
| --- | --- |
| `0` | 本轮所选任务均处理成功，或仅列出课程 |
| `1` | 配置、登录或启动失败 |
| `2` | 本轮结束，但有跳过或失败项 |
| `130` | 手动中断 |

## 开发

使用 uv 管理依赖及构建、ruff 格式化与检查、ty 类型检查、pytest 离线测试。配置通过 Pydantic v2 校验，命令行使用 Typer + Rich，网络请求使用 HTTPX。

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
uv build
```

`uv.lock` 纳入版本管理。CI 在 Linux 和 Windows 上运行检查和离线测试，使用模拟 HTTP 响应，不登录真实账号、不发送真实通知。

## Docker

默认镜像不安装 OCR 和开发工具。将配置及 Cookie 放在同一挂载目录：

```sh
mkdir -p runtime
cp config.example.toml runtime/config.toml
# 编辑 runtime/config.toml
docker build -t chaoxing .
docker run --rm -it -v "$PWD/runtime:/config" chaoxing
```

需要代理或用环境变量配置凭证时，使用 Docker 的 `--env-file` 或 `-e` 参数。镜像只复制构建所需文件，配置和凭证不会打包进镜像。

## 许可

[GPL-3.0](LICENSE)。请遵守平台和课程的使用规则。
