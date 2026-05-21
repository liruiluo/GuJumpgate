# Checkout Converter Service

把当前项目里的 Plus checkout 创建逻辑抽成一个独立可部署的云端服务。

## 能力范围

- 输入 ChatGPT `accessToken`
- 按当前项目的规则创建 Plus checkout session
- 返回：
  - `checkoutUrl`
  - `chatgptCheckoutUrl`
  - `hostedCheckoutUrl`
  - `preferredCheckoutUrl`

当前实现与项目内 [content/plus-checkout.js](I:\FlowPilot-FlowPilot1.0\FlowPilot-FlowPilot1.0.2\content\plus-checkout.js:978) 保持一致：

- `paypal` 默认 `US / USD`
- `gopay` 默认 `ID / IDR`
- 默认转换后的 `processorEntity` 为 `openai_llc`
- `paypal` 优先返回 `pay.openai.com` 的 hosted checkout 长链

## 接口

### `GET /healthz`

健康检查与当前并发配置概览。

### `POST /api/checkout`

请求头：

```text
Content-Type: application/json
X-API-Key: <你的服务鉴权，可选但强烈建议开启>
```

请求体：

```json
{
  "accessToken": "<chatgpt access token>",
  "paymentMethod": "paypal",
  "country": "US",
  "currency": "USD",
  "processorEntity": "openai_llc",
  "requestId": "req-001"
}
```

返回示例：

```json
{
  "ok": true,
  "requestId": "req-001",
  "paymentMethod": "paypal",
  "checkoutSessionId": "cs_live_xxx",
  "checkoutUrl": "https://chatgpt.com/checkout/openai_ie/cs_live_xxx",
  "chatgptCheckoutUrl": "https://chatgpt.com/checkout/openai_llc/cs_live_xxx",
  "hostedCheckoutUrl": "https://pay.openai.com/c/pay/hosted_cs_live_xxx",
  "preferredCheckoutUrl": "https://pay.openai.com/c/pay/hosted_cs_live_xxx",
  "processorEntity": "openai_llc",
  "upstreamProcessorEntity": "openai_ie",
  "country": "US",
  "currency": "USD",
  "upstreamStatus": 200,
  "durationMs": 742
}
```

## 本地启动

```powershell
cd services/checkout-converter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:CHECKOUT_CONVERTER_API_KEY="replace-me"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## Docker

```powershell
cd services/checkout-converter
docker build -t checkout-converter .
docker run -d `
  -p 8080:8080 `
  -e CHECKOUT_CONVERTER_API_KEY=replace-me `
  -e MAX_OUTBOUND_CONCURRENCY=200 `
  -e SESSION_MAX_CLIENTS=400 `
  --name checkout-converter `
  checkout-converter
```

## 生产部署建议

### 1. 进程模型

推荐用 `gunicorn + uvicorn worker`：

```bash
gunicorn -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8080 app:app
```

如果是 4 核机器，建议从 `2` 或 `3` 个 worker 起步，不要一开始把 worker 开太高。

### 2. 并发参数

- `MAX_OUTBOUND_CONCURRENCY`
  控制单进程同时向 OpenAI 发起多少个 checkout 请求
- `SESSION_MAX_CLIENTS`
  控制 `curl_cffi.AsyncSession` 连接池容量
- `REQUEST_TIMEOUT_SECONDS`
  单次上游请求超时

建议起步值：

```text
MAX_OUTBOUND_CONCURRENCY=200
SESSION_MAX_CLIENTS=400
REQUEST_TIMEOUT_SECONDS=30
```

如果你的机器出口稳定、CPU 余量足，再逐步提高。

### 3. 高并发注意点

- 不要把 access token 打到日志里
- `X-API-Key` 必开
- 入口层建议再加一层 Nginx 限流
- 如需更稳的机房出口，优先通过固定代理或住宅代理出站
- 如果业务会重复提交同一 token，最好在调用方做去重或幂等控制

### 4. Cloudflare 风险

虽然这里用了 `curl_cffi` 的浏览器指纹模拟，但云服务器出口 IP 仍然可能被挑战。

如果你遇到：

- `upstream blocked by Cloudflare challenge`
- 403 / 429 明显增多

优先排查：

1. 服务器出口 IP 质量
2. 是否需要固定代理出站
3. 并发是否过高
4. 是否同一 token 被短时间重复调用

## 环境变量

```text
PORT=8080
BIND_HOST=0.0.0.0
CHECKOUT_CONVERTER_API_KEY=
LOG_LEVEL=INFO
REQUEST_TIMEOUT_SECONDS=30
MAX_OUTBOUND_CONCURRENCY=200
SESSION_MAX_CLIENTS=400
IMPERSONATE_BROWSER=chrome136
OPENAI_PROXY_URL=
SERVICE_NAME=checkout-converter
SERVICE_VERSION=1.0.0
```
