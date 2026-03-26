# 验收测试

本页记录各支持验证码类型的验收目标、测试 URL、site key，以及本地验证运行的观察结果。

## 总览

| 验证码类型 | 目标 | 状态 |
|----------|------|------|
| reCAPTCHA v3 | `https://antcpt.com/score_detector/` | ✅ 已返回令牌 |
| Cloudflare Turnstile | `https://react-turnstile.vercel.app/basic` | ✅ 已返回 Dummy 令牌 |
| reCAPTCHA v2 | `https://www.google.com/recaptcha/api2/demo` | ⚠️ 需要音频挑战（见说明） |
| hCaptcha | `https://accounts.hcaptcha.com/demo` | ✅ 官方测试 key direct-pass |
| Image-to-Text | 本地 base64 图片 | ✅ 视觉模型返回文本 |
| 分类任务 | 本地 base64 网格 | ✅ 视觉模型返回对象索引 |

---

## reCAPTCHA v3 — 主要验收目标

**URL：** `https://antcpt.com/score_detector/`  
**Site key：** `6LcR_okUAAAAAPYrPe-HK_0RULO1aZM15ENyM-Mf`

### 验收步骤

1. 安装依赖和 Playwright Chromium。
2. 启动服务：`python main.py`
3. 确认 `GET /api/v1/health` 返回全部 19 种任务类型。
4. 创建 `RecaptchaV3TaskProxyless` 任务。
5. 轮询 `POST /getTaskResult` 直至 `status=ready`。
6. 确认返回非空的 `solution.gRecaptchaResponse`。

### 已验证结果

- 服务启动：✅
- 健康检查端点：✅（19 种类型已注册）
- 任务创建：✅
- 令牌返回：✅（非空 `gRecaptchaResponse`，长度约 1060 字符）

---

## Cloudflare Turnstile

**URL：** `https://react-turnstile.vercel.app/basic`  
**Site key：** `1x00000000000000000000AA`（Cloudflare 官方测试密钥——始终通过）

### 已验证结果

- 令牌返回：✅ `XXXX.DUMMY.TOKEN.XXXX`（Cloudflare 测试密钥的预期行为）

---

## reCAPTCHA v2

**URL：** `https://www.google.com/recaptcha/api2/demo`  
**Site key：** `6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-`

### 无头浏览器行为

Google 风险分析引擎会检测无头浏览器。复选框点击成功，但会弹出图像挑战，而不是直接签发令牌。

**已实现的缓解措施：** 求解器回退到**音频挑战路径**——在挑战对话框中点击音频按钮，下载 MP3，通过配置的模型转录，并提交转录文本。

### 状态

⚠️ 已实现音频挑战回退。成功率取决于模型的音频处理能力和 Google 当前的挑战难度。

---

## hCaptcha

**URL：** `https://accounts.hcaptcha.com/demo`  
**Site key：** `10000000-ffff-ffff-ffff-000000000001`（hCaptcha 官方测试密钥）

### 行为

现在的 hCaptcha 求解器会先把官方 demo URL 规范化，确保请求里的
`websiteKey` 真正注入为 `?sitekey=...&hl=en` 再打开页面。使用官方公开测试 key
`10000000-ffff-ffff-ffff-000000000001` 时，demo 在无头模式下会返回文档约定的
direct-pass token。

我们也额外测试了默认公开 demo widget 的 sitekey
`a5f74b19-9e45-40e0-b45d-47ff91b7a6c2`，实际落到的是另一条运行分支：
canvas / puzzle challenge，prompt 为
`Place the correct puzzle piece into the correct slot to complete the image`。
这条分支不属于当前项目内置 `HCaptchaClassification` 网格回退链路的支持范围。

### 状态

✅ 已验证的 sanity path（官方公开测试 key）：

- `HCaptchaTaskProxyless` 的 `createTask` 成功
- `getTaskResult` 返回
  `solution.gRecaptchaResponse=10000000-aaaa-bbbb-cccc-000000000001`
- 服务日志出现 `Got hCaptcha token directly after checkbox click`

⚠️ 目前我们仍然没有找到“官方公开、且每次都稳定强制进入网格分类分支”的 URL。
如果你要稳定验证 classification 链路，应使用你自己可控的 hCaptcha 页面和
sitekey。详见 [hCaptcha 使用指南](usage/hcaptcha.md)。

---

## 总结

- ✅ **reCAPTCHA v3** 和 **Turnstile** 完全可用，每次本地测试均通过。
- ⚠️ **reCAPTCHA v2** 仍然受无头检测限制；**hCaptcha** 虽然官方测试 key 的 direct-pass 已验证通过，但公开 demo 仍会出现当前项目不支持的 canvas / puzzle 分支。想稳定测 hCaptcha 网格分类链路，仍需要自控 sitekey / 自控页面。
- 本服务设计为 **flow2api 的后端打码工具**——实际集成中，通常提取图像挑战帧并发送到分类端点，而非完全依赖浏览器自动化通过组件。
