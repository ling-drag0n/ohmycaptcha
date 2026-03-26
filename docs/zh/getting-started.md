# 快速开始

## 环境要求

- Python 3.10+
- 通过 Playwright 安装 Chromium
- 具备访问以下资源的网络能力：
  - 目标网站
  - 你配置的 OpenAI-compatible 模型接口

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `LOCAL_BASE_URL` | 本地 / 自托管 OpenAI-compatible 接口，用于图像分类 | `http://localhost:30000/v1` |
| `LOCAL_API_KEY` | 本地接口密钥 | `EMPTY` |
| `LOCAL_MODEL` | 本地多模态模型名 | `Qwen/Qwen3.5-2B` |
| `CLOUD_BASE_URL` | 远程 OpenAI-compatible 接口，用于更重的推理任务 | `https://your-openai-compatible-endpoint/v1` |
| `CLOUD_API_KEY` | 远程接口密钥 | 未设置 |
| `CLOUD_MODEL` | 云端模型名 | `gpt-5.4` |
| `CLIENT_KEY` | 客户端鉴权密钥 | 未设置 |
| `CAPTCHA_RETRIES` | 重试次数 | `3` |
| `CAPTCHA_TIMEOUT` | 模型超时（秒） | `30` |
| `BROWSER_HEADLESS` | 是否无头运行 Chromium | `true` |
| `BROWSER_TIMEOUT` | 浏览器超时（秒） | `30` |
| `SERVER_HOST` | 监听地址 | `0.0.0.0` |
| `SERVER_PORT` | 监听端口 | `8000` |

> 旧版变量（`CAPTCHA_BASE_URL`、`CAPTCHA_API_KEY`、`CAPTCHA_MODEL`、
> `CAPTCHA_MULTIMODAL_MODEL`）仍可作为回退使用；当新旧变量同时存在时，
> `LOCAL_*` / `CLOUD_*` 优先生效。

## 启动服务

```bash
export LOCAL_BASE_URL="http://localhost:30000/v1"
export LOCAL_API_KEY="EMPTY"
export LOCAL_MODEL="Qwen/Qwen3.5-2B"

export CLOUD_BASE_URL="https://your-openai-compatible-endpoint/v1"
export CLOUD_API_KEY="your-api-key"
export CLOUD_MODEL="gpt-5.4"

export CLIENT_KEY="your-client-key"
python main.py
```

### Windows PowerShell 示例

```powershell
$env:LOCAL_BASE_URL = "http://localhost:30000/v1"
$env:LOCAL_API_KEY = "EMPTY"
$env:LOCAL_MODEL = "Qwen/Qwen3.5-2B"

$env:CLOUD_BASE_URL = "https://your-openai-compatible-endpoint/v1"
$env:CLOUD_API_KEY = "your-api-key"
$env:CLOUD_MODEL = "gpt-5.4"

$env:CLIENT_KEY = "your-client-key"
python main.py
```

## 验证启动

### 根接口

```bash
curl http://localhost:8000/
```

### 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

健康检查响应中应包含已注册任务类型以及当前运行时模型配置。

## 本地 / 自托管模型支持

图片识别 / 分类路径基于 **OpenAI-compatible API** 设计。也就是说，
你可以把 `LOCAL_BASE_URL` 指向托管服务、内部网关或本地 / 自托管多模态网关，
再把 `CLOUD_BASE_URL` 指向另一套更强的远程推理端点；前提是它们都提供兼容的
chat-completions 语义，并支持你需要的输入类型。

文档采用通用兼容性表述，而不是对每一种模型服务栈做完整验证承诺。
