# hCaptcha 使用指南

hCaptcha 通过 iframe 组件展示验证码挑战。求解器使用 Playwright 控制的
Chromium 访问目标页面，点击 hCaptcha 复选框，并提取
`h-captcha-response` 令牌。

如果 hCaptcha 在无头环境升级为图像选择挑战，内置求解链路现在会：

1. 提取 challenge prompt 和候选 tile 图片，
2. 走 `HCaptchaClassification` 推理路径，
3. 在 challenge iframe 内点击模型判断命中的 tile，
4. 提交 challenge，并继续轮询最终 token。

## 支持的任务类型

| 任务类型 | 说明 |
|---------|------|
| `HCaptchaTaskProxyless` | 基于浏览器的 hCaptcha 求解 |

## 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `websiteURL` | string | 包含验证码的页面完整 URL |
| `websiteKey` | string | 页面 HTML 中的 `data-sitekey` 值。对于官方 demo URL，求解器现在会自动把它注入到 query string，确保实际测试的是你请求的 sitekey。 |

## 测试目标

hCaptcha 官方文档提供了可预测行为的测试密钥：

| URL | Site key | 行为 |
|-----|----------|------|
| `https://accounts.hcaptcha.com/demo` | `10000000-ffff-ffff-ffff-000000000001` | 始终通过（测试密钥） |
| `https://accounts.hcaptcha.com/demo` | `20000000-ffff-ffff-ffff-000000000002` | Enterprise safe-user 测试 |
| `https://demo.hcaptcha.com/` | `10000000-ffff-ffff-ffff-000000000001` | 始终通过（测试密钥） |

!!! note "官方 demo URL 自动规范化"
    官方 demo 页面支持 `?sitekey=...`。如果你传的是
    `websiteURL=https://accounts.hcaptcha.com/demo`，同时又提供了
    `websiteKey`，求解器现在会在打开页面前把目标 URL 改写成
    `...?sitekey=<websiteKey>&hl=en`，确保与官方 demo 的真实行为一致。

## 创建任务

```bash
curl -X POST http://localhost:8000/createTask \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-client-key",
    "task": {
      "type": "HCaptchaTaskProxyless",
      "websiteURL": "https://accounts.hcaptcha.com/demo",
      "websiteKey": "10000000-ffff-ffff-ffff-000000000001"
    }
  }'
```

返回：

```json
{
  "errorId": 0,
  "taskId": "uuid-string"
}
```

## 轮询结果

```bash
curl -X POST http://localhost:8000/getTaskResult \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-client-key",
    "taskId": "uuid-from-createTask"
  }'
```

就绪时返回：

```json
{
  "errorId": 0,
  "status": "ready",
  "solution": {
    "gRecaptchaResponse": "P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
  }
}
```

!!! note "字段命名"
    为了兼容 YesCaptcha API，令牌仍然放在
    `solution.gRecaptchaResponse`，尽管 hCaptcha 原生字段名是
    `h-captcha-response`。

## 验收状态

| 目标 | Site key | 状态 | 说明 |
|------|----------|------|------|
| `https://accounts.hcaptcha.com/demo` | `10000000-ffff-ffff-ffff-000000000001` | ✅ 已验证 | 求解器现在会尊重请求中的 demo sitekey，并在无头模式下拿到官方 direct-pass token |

### 无头浏览器说明

如果真实站点在无头环境中升级成 image-selection challenge，求解器会先尝试内置
`HCaptchaClassification` 回退链路。

现在的 `HCaptchaTaskProxyless` 内置求解器，会在直接 token 没出现时，自动尝试
`HCaptchaClassification` 风格的图片选择回退；如果你已经自己提取了 tile，也仍可单独使用
`HCaptchaClassification` 任务类型。详见
[图像分类](classification.md)。

如果 hCaptcha 给出的不是网格图片，而是 canvas / puzzle-piece challenge，
当前实现会明确报“不支持的 challenge 类型”，而不是误报成 DOM 提取失败。

### 可观测性：怎么判断是否真的触发了 classification

当 classification 真正跑起来时，服务日志会出现类似：

- `No direct hCaptcha token after checkbox click, entering classification fallback`
- `Collected hCaptcha image-selection challenge in round ...`
- `Classification request: task_type=HCaptchaClassification ...`
- `Classification raw response: ...`
- `Classification parsed result: ...`

如果你只看到了 `Got hCaptcha token directly after checkbox click`，
那说明这次走的是官方测试 key 的 direct-pass 路径，并没有真的调用图像分类模型。

### 实测中观察到的 challenge 家族

结合官方 demo 和当前开源求解器调研，当前实际见到的主要分支有：

1. direct-pass / 不显示可见 challenge，
2. image-selection 网格挑战（这是 `HCaptchaClassification` 负责的分支），
3. canvas / puzzle-piece 挑战（当前项目还不支持），
4. challenge 菜单里的 accessibility 相关分支。

官方公开测试 key `10000000-ffff-ffff-ffff-000000000001` 非常适合做
service sanity check，但它**不会强制进入图像分类分支**。截至当前调研，
我们还没有找到官方公开、且每次都稳定触发 grid/image-selection 的 URL；
如果你想稳定测试 classification 链路，建议使用你自己可控的 hCaptcha 集成页。

### 本地受控测试怎么做

hCaptcha 官方文档对本地测试有两个关键限制：

1. 普通 widget 测试里，`localhost` 和 `127.0.0.1` 不是可接受 hostname；
2. 公共测试 key 主要用于集成联通性检查，不会帮你稳定触发图像分类分支。

如果你想在本地稳定验证 `HCaptchaClassification`，最可靠的做法是：

1. 自己创建一个 hCaptcha sitekey，用于测试流量；
2. 在 hosts 文件里把自定义域名（例如 `test.mydomain.com`）指向 `127.0.0.1`；
3. 本地起一个最小测试页，嵌入你自己的 sitekey；
4. Enterprise 可以给你的 IP / User-Agent 加 `Challenge` 规则；Pro / 免费版则建议单独准备一个 `Always Challenge` 的 sitekey；
5. 用这个受控页面 URL 跑 `HCaptchaTaskProxyless`，再看上面的 classification 日志链路。

!!! note "Challenge 不等于一定是可见网格"
    官方文档明确写了：`challenge` 并不自动等于 `visual challenge`。
    即便把 sitekey 行为配置成 `Always Challenge`，在 Pro / 免费模式下，你也可能需要多刷新几次，才会真的看到可见 challenge。

## 图像分类（HCaptchaClassification）

如果你已经从 challenge 中提取好了图片，而不想通过浏览器自动化流程去走组件，
请直接看 [图像分类](classification.md)。

## 注意事项

- hCaptcha 一般比 reCAPTCHA v2 更耗时 —— 求解器会先尝试 direct token，再在 challenge iframe 出现后切到 classification 驱动的 tile 点击路径。
- 真实站点如果有更激进的 bot detection，可能仍需要额外的指纹伪装改进。
- 测试密钥（`10000000-ffff-ffff-ffff-000000000001`）始终通过，适合做基础链路验活。
