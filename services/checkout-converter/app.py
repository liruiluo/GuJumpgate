import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from curl_cffi import requests as curl_requests
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


OPENAI_CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"
DEFAULT_CONVERTED_CHECKOUT_PROCESSOR_ENTITY = "openai_llc"
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
PAY_OPENAI_URL_PATTERN = re.compile(r"^https://(?:pay\.openai\.com|checkout\.stripe\.com)/c/pay/", re.I)
SUPPORTED_PAYMENT_METHODS = ("paypal", "gopay")

PAYMENT_METHOD_CONFIGS = {
    "paypal": {
        "checkout_merchant_path": "openai_ie",
        "billing_details": {"country": "US", "currency": "USD"},
        "checkout_ui_mode": "hosted",
    },
    "gopay": {
        "checkout_merchant_path": "openai_llc",
        "billing_details": {"country": "ID", "currency": "IDR"},
        "checkout_ui_mode": "custom",
    },
}

PLUS_CHECKOUT_PAYLOAD_BASE = {
    "entry_point": "all_plans_pricing_modal",
    "plan_name": "chatgptplusplan",
    "promo_campaign": {
        "promo_campaign_id": "plus-1-month-free",
        "is_coupon_from_query_param": False,
    },
}

logger = logging.getLogger("checkout_converter")


class Settings(BaseModel):
    bind_host: str = Field(default=os.getenv("BIND_HOST", "0.0.0.0"))
    bind_port: int = Field(default=int(os.getenv("PORT", "8080")))
    api_key: str = Field(default=os.getenv("CHECKOUT_CONVERTER_API_KEY", "").strip())
    log_level: str = Field(default=os.getenv("LOG_LEVEL", "INFO").upper())
    request_timeout_seconds: float = Field(default=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")))
    max_outbound_concurrency: int = Field(default=max(1, int(os.getenv("MAX_OUTBOUND_CONCURRENCY", "200"))))
    session_max_clients: int = Field(default=max(1, int(os.getenv("SESSION_MAX_CLIENTS", "400"))))
    impersonate_browser: str = Field(default=os.getenv("IMPERSONATE_BROWSER", "chrome136").strip())
    fallback_impersonate_browser: str = Field(default=os.getenv("FALLBACK_IMPERSONATE_BROWSER", "chrome133a").strip())
    default_proxy_url: str = Field(default=os.getenv("OPENAI_PROXY_URL", "").strip())
    service_name: str = Field(default=os.getenv("SERVICE_NAME", "checkout-converter"))
    service_version: str = Field(default=os.getenv("SERVICE_VERSION", "1.0.0"))


class CheckoutConvertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str | None = Field(default=None, alias="accessToken")
    token: str | None = None
    payment_method: Literal["paypal", "gopay"] = Field(default="paypal", alias="paymentMethod")
    country: str | None = None
    currency: str | None = None
    processor_entity: str | None = Field(default=None, alias="processorEntity")
    proxy_url: str | None = Field(default=None, alias="proxyUrl")
    request_id: str | None = Field(default=None, alias="requestId")


class CheckoutConvertResponse(BaseModel):
    ok: bool
    request_id: str = Field(alias="requestId")
    payment_method: str = Field(alias="paymentMethod")
    checkout_session_id: str = Field(alias="checkoutSessionId")
    checkout_url: str = Field(alias="checkoutUrl")
    chatgpt_checkout_url: str = Field(alias="chatgptCheckoutUrl")
    hosted_checkout_url: str = Field(alias="hostedCheckoutUrl")
    preferred_checkout_url: str = Field(alias="preferredCheckoutUrl")
    processor_entity: str = Field(alias="processorEntity")
    upstream_processor_entity: str = Field(alias="upstreamProcessorEntity")
    country: str
    currency: str
    upstream_status: int = Field(alias="upstreamStatus")
    duration_ms: int = Field(alias="durationMs")


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def extract_access_token(raw_value: str | None) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", text):
        return text
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ("accessToken", "access_token", "token"):
                candidate = str(parsed.get(key) or "").strip()
                if candidate:
                    return extract_access_token(candidate)
    except json.JSONDecodeError:
        pass
    match = JWT_PATTERN.search(text)
    return match.group(0) if match else ""


def normalize_proxy_url(value: str | None) -> str:
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    if not re.match(r"^(https?|socks4a?|socks5h?)://", proxy, re.I):
        raise HTTPException(status_code=400, detail="proxyUrl 格式不支持，请使用 http://、https://、socks5:// 或 socks5h://")
    return proxy


def normalize_payment_method(value: str | None) -> str:
    method = str(value or "").strip().lower()
    if method not in SUPPORTED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"paymentMethod 仅支持: {', '.join(SUPPORTED_PAYMENT_METHODS)}")
    return method


def build_plus_checkout_payload(request_body: CheckoutConvertRequest, payment_method: str) -> dict[str, Any]:
    config = PAYMENT_METHOD_CONFIGS[payment_method]
    country = str(request_body.country or config["billing_details"]["country"]).strip().upper()
    currency = str(request_body.currency or config["billing_details"]["currency"]).strip().upper()
    return {
        **json.loads(json.dumps(PLUS_CHECKOUT_PAYLOAD_BASE)),
        "checkout_ui_mode": config["checkout_ui_mode"],
        "billing_details": {
            "country": country,
            "currency": currency,
        },
    }


def build_checkout_url(checkout_session_id: str, payment_method: str) -> str:
    session_id = str(checkout_session_id or "").strip()
    if not session_id:
        raise ValueError("missing checkout_session_id")
    merchant_path = PAYMENT_METHOD_CONFIGS[payment_method]["checkout_merchant_path"]
    return f"https://chatgpt.com/checkout/{merchant_path}/{session_id}"


def build_converted_chatgpt_checkout_url(checkout_session_id: str, processor_entity: str) -> str:
    session_id = str(checkout_session_id or "").strip()
    entity = str(processor_entity or "").strip() or DEFAULT_CONVERTED_CHECKOUT_PROCESSOR_ENTITY
    if not session_id:
        raise ValueError("missing checkout_session_id")
    return f"https://chatgpt.com/checkout/{entity}/{session_id}"


def find_hosted_checkout_url(payload: Any) -> str:
    stack = [payload]
    while stack:
        current = stack.pop(0)
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        for value in current.values():
            if isinstance(value, str) and PAY_OPENAI_URL_PATTERN.match(value.strip()):
                return value.strip()
            if isinstance(value, (dict, list)):
                stack.append(value)
    return ""


def build_request_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
    }


def looks_like_cloudflare_challenge(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "_cf_chl_opt" in lowered
        or "enable javascript and cookies to continue" in lowered
        or "cf-chl" in lowered
    )


def parse_response_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except json.JSONDecodeError:
        return {"detail": text or "upstream returned non-json response"}


def choose_error_status(upstream_status: int) -> int:
    if upstream_status in (400, 401, 403, 404, 409, 422, 429):
        return upstream_status
    return 502


def require_api_key(settings: Settings, provided_api_key: str | None) -> None:
    if not settings.api_key:
        return
    if str(provided_api_key or "").strip() != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid api key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    configure_logging(settings.log_level)
    session = curl_requests.AsyncSession(
        max_clients=settings.session_max_clients,
        timeout=settings.request_timeout_seconds,
        headers={"Accept": "application/json"},
    )
    app.state.settings = settings
    app.state.checkout_session = session
    app.state.outbound_limiter = asyncio.Semaphore(settings.max_outbound_concurrency)
    logger.info(
        "checkout converter service starting service=%s version=%s max_outbound_concurrency=%s session_max_clients=%s api_key_enabled=%s",
        settings.service_name,
        settings.service_version,
        settings.max_outbound_concurrency,
        settings.session_max_clients,
        bool(settings.api_key),
    )
    try:
        yield
    finally:
        await session.close()
        logger.info("checkout converter service stopped")


app = FastAPI(title="Checkout Converter", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_process_timing(request: Request, call_next):
    started_at = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.exception(
            "request failed request_id=%s method=%s path=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            duration_ms,
        )
        raise
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    logger.info(
        "request completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "requestId": request_id,
            "detail": exc.detail,
        },
    )


@app.get("/healthz")
async def healthz(request: Request):
    settings: Settings = request.app.state.settings
    semaphore: asyncio.Semaphore = request.app.state.outbound_limiter
    active_estimate = settings.max_outbound_concurrency - getattr(semaphore, "_value", settings.max_outbound_concurrency)
    return {
        "ok": True,
        "service": settings.service_name,
        "version": settings.service_version,
        "maxOutboundConcurrency": settings.max_outbound_concurrency,
        "sessionMaxClients": settings.session_max_clients,
        "activeOutboundEstimate": max(0, active_estimate),
        "apiKeyEnabled": bool(settings.api_key),
    }


@app.post("/api/checkout", response_model=CheckoutConvertResponse)
async def convert_checkout(
    payload: CheckoutConvertRequest,
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None),
):
    settings: Settings = request.app.state.settings
    require_api_key(settings, x_api_key)

    request_id = payload.request_id or getattr(request.state, "request_id", uuid.uuid4().hex)
    payment_method = normalize_payment_method(payload.payment_method)
    access_token = extract_access_token(payload.access_token or payload.token)
    if not access_token:
        raise HTTPException(status_code=400, detail="missing valid access token")

    processor_entity = str(payload.processor_entity or DEFAULT_CONVERTED_CHECKOUT_PROCESSOR_ENTITY).strip() or DEFAULT_CONVERTED_CHECKOUT_PROCESSOR_ENTITY
    proxy_url = normalize_proxy_url(payload.proxy_url or settings.default_proxy_url)
    checkout_payload = build_plus_checkout_payload(payload, payment_method)
    session: curl_requests.AsyncSession = request.app.state.checkout_session
    limiter: asyncio.Semaphore = request.app.state.outbound_limiter

    started_at = time.perf_counter()
    request_options = {
        "json": checkout_payload,
        "headers": build_request_headers(access_token),
        "proxy": proxy_url or None,
    }
    if settings.impersonate_browser:
        request_options["impersonate"] = settings.impersonate_browser

    async def post_checkout(options: dict[str, Any]):
        return await session.post(
            OPENAI_CHECKOUT_URL,
            **options,
        )

    async with limiter:
        try:
            upstream_response = await post_checkout(request_options)
        except Exception as exc:
            logger.warning(
                "upstream checkout request failed request_id=%s error_type=%s error=%s",
                request_id,
                type(exc).__name__,
                str(exc),
            )
            raise HTTPException(
                status_code=502,
                detail=f"upstream checkout request failed: {type(exc).__name__}: {exc}",
            ) from exc

    raw_text = upstream_response.text
    if (
        looks_like_cloudflare_challenge(raw_text)
        and settings.fallback_impersonate_browser
        and settings.fallback_impersonate_browser != settings.impersonate_browser
    ):
        logger.info(
            "upstream returned Cloudflare challenge; retrying with fallback impersonate request_id=%s fallback=%s",
            request_id,
            settings.fallback_impersonate_browser,
        )
        retry_options = {
            **request_options,
            "impersonate": settings.fallback_impersonate_browser,
        }
        async with limiter:
            try:
                upstream_response = await post_checkout(retry_options)
            except Exception as exc:
                logger.warning(
                    "upstream checkout retry failed request_id=%s error_type=%s error=%s",
                    request_id,
                    type(exc).__name__,
                    str(exc),
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"upstream checkout retry failed: {type(exc).__name__}: {exc}",
                ) from exc
        raw_text = upstream_response.text

    if looks_like_cloudflare_challenge(raw_text):
        raise HTTPException(status_code=502, detail="upstream blocked by Cloudflare challenge")

    upstream_data = parse_response_json(raw_text)
    upstream_status = int(upstream_response.status_code)
    checkout_session_id = str(upstream_data.get("checkout_session_id") or "").strip()
    if upstream_status >= 400 or not checkout_session_id:
        detail = upstream_data.get("detail") or upstream_data.get("message") or upstream_data.get("error") or f"upstream returned HTTP {upstream_status}"
        raise HTTPException(status_code=choose_error_status(upstream_status), detail=detail)

    hosted_checkout_url = find_hosted_checkout_url(upstream_data)
    checkout_url = build_checkout_url(checkout_session_id, payment_method)
    chatgpt_checkout_url = build_converted_chatgpt_checkout_url(checkout_session_id, processor_entity)
    preferred_checkout_url = hosted_checkout_url if payment_method == "paypal" and hosted_checkout_url else chatgpt_checkout_url
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    response.headers["X-Upstream-Status"] = str(upstream_status)
    return CheckoutConvertResponse(
        ok=True,
        requestId=request_id,
        paymentMethod=payment_method,
        checkoutSessionId=checkout_session_id,
        checkoutUrl=checkout_url,
        chatgptCheckoutUrl=chatgpt_checkout_url,
        hostedCheckoutUrl=hosted_checkout_url,
        preferredCheckoutUrl=preferred_checkout_url,
        processorEntity=processor_entity,
        upstreamProcessorEntity=str(upstream_data.get("processor_entity") or "").strip(),
        country=str(checkout_payload["billing_details"]["country"]),
        currency=str(checkout_payload["billing_details"]["currency"]),
        upstreamStatus=upstream_status,
        durationMs=duration_ms,
    )
