#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import io
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from contextlib import redirect_stdout

try:
    from twelvedata import TDClient
except Exception:
    TDClient = None

try:
    import tushare as ts
except Exception:
    ts = None

try:
    import akshare as ak
except Exception:
    ak = None

try:
    import baostock as bs
except Exception:
    bs = None


YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

CRYPTO_ALIASES = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "ripple": "XRPUSDT",
    "xrp": "XRPUSDT",
    "dogecoin": "DOGEUSDT",
    "doge": "DOGEUSDT",
    "cardano": "ADAUSDT",
    "ada": "ADAUSDT",
    "bnb": "BNBUSDT",
    "chainlink": "LINKUSDT",
    "link": "LINKUSDT",
    "avalanche": "AVAXUSDT",
    "avax": "AVAXUSDT",
    "toncoin": "TONUSDT",
    "ton": "TONUSDT",
    "sui": "SUIUSDT",
}

TIMEFRAME_TO_YAHOO = {
    "1d": "1d",
    "1h": "60m",
}

TIMEFRAME_TO_TWELVEDATA = {
    "1d": "1day",
    "1h": "1h",
}

TIMEFRAME_TO_TUSHARE = {
    "1d": "daily",
    "1h": "60min",
}

TIMEFRAME_TO_BINANCE = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

DEFAULT_STATE_DIR = Path(
    os.environ.get("QUANT_SKILL_HOME", str(Path.home() / ".quant-trading-analyst"))
)

TUSHARE_API_URL = os.environ.get("TUSHARE_API_URL", "http://api.tushare.pro")
US_EQUITY_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "NYSE American"}
CN_EQUITY_EXCHANGES = {"SSE", "SZSE", "BSE"}


def ensure_state_dir() -> Path:
    DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_STATE_DIR


def default_memory_path() -> Path:
    return ensure_state_dir() / "learning_memory.json"


def default_monitor_state_path() -> Path:
    return ensure_state_dir() / "monitor_state.json"


@lru_cache(maxsize=1)
def get_twelvedata_client():
    api_key = os.environ.get("TWELVEDATA_API_KEY")
    if not api_key or TDClient is None:
        return None
    return TDClient(apikey=api_key)


@lru_cache(maxsize=1)
def get_tushare_pro_client():
    token = os.environ.get("TUSHARE_TOKEN")
    if not token or ts is None:
        return None
    return ts.pro_api(token)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def normalize_tushare_mode(mode: str | None) -> str:
    normalized = (mode or "http").strip().lower()
    if normalized not in {"http", "sdk"}:
        raise ValueError("Tushare mode must be either 'http' or 'sdk'.")
    return normalized


def cn_stock_provider_order(tushare_mode: str = "http") -> list[str]:
    normalized = normalize_tushare_mode(tushare_mode)
    return [f"tushare-{normalized}", "akshare", "baostock"]


def is_tushare_permission_error(error: Exception) -> bool:
    message = str(error).lower()
    return "没有接口访问权限" in str(error) or "doc_id=108" in message or "permission" in message


def safe_float(value, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    return float(value)


def fetch_json(url: str, headers: dict | None = None, timeout: int = 20):
    attempts = [url]
    if "query1.finance.yahoo.com" in url:
        attempts.append(url.replace("query1.finance.yahoo.com", "query2.finance.yahoo.com"))
    last_error = None
    for attempt in attempts:
        for delay in (0.0, 0.8, 1.6):
            if delay:
                time.sleep(delay)
            request = urllib.request.Request(attempt, headers=headers or {})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in {429, 500, 502, 503, 504}:
                    raise
            except Exception as error:
                last_error = error
                break
    if last_error:
        raise last_error
    raise RuntimeError("Request failed without a captured error.")


def post_json(url: str, payload: dict, timeout: int = 20):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def looks_like_cn_stock_query(query: str) -> bool:
    cleaned = query.strip().upper()
    if contains_cjk(query):
        return True
    if re.fullmatch(r"\d{6}", cleaned):
        return True
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", cleaned):
        return True
    return False


def infer_cn_ts_code(query: str) -> str:
    cleaned = query.strip().upper()
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", cleaned):
        return cleaned
    if not re.fullmatch(r"\d{6}", cleaned):
        return cleaned
    if cleaned.startswith(("5", "6", "9")):
        suffix = "SH"
    elif cleaned.startswith(("4", "8")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{cleaned}.{suffix}"


def infer_cn_exchange(ts_code: str | None) -> str | None:
    if not ts_code or "." not in ts_code:
        return None
    suffix = ts_code.rsplit(".", 1)[1].upper()
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix)


def parse_cn_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def parse_cn_trade_time(value: str) -> datetime:
    normalized = value.replace("T", " ")
    return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")


def tushare_request(
    api_name: str,
    params: dict | None = None,
    fields: str | None = None,
    mode: str = "http",
) -> list[dict]:
    mode = normalize_tushare_mode(mode)
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not set. It is required for A-share analysis and monitoring.")
    if mode == "sdk":
        client = get_tushare_pro_client()
        if client is None:
            raise RuntimeError(
                "Tushare SDK mode requested, but the optional 'tushare' package is not installed."
            )
        request_params = dict(params or {})
        if fields:
            request_params["fields"] = fields
        method = getattr(client, api_name, None)
        frame = method(**request_params) if callable(method) else client.query(api_name, **request_params)
        if frame is None:
            return []
        return frame.to_dict("records")
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params or {},
    }
    if fields:
        payload["fields"] = fields
    raw = post_json(TUSHARE_API_URL, payload)
    response = json.loads(raw)
    if response.get("code") != 0:
        raise RuntimeError(f"Tushare {api_name} failed: {response.get('msg') or response.get('code')}")
    data = response.get("data") or {}
    result_fields = data.get("fields") or []
    return [dict(zip(result_fields, item)) for item in data.get("items", [])]


def tushare_stock_cache_path() -> Path:
    return ensure_state_dir() / "tushare_stock_basic_cache.json"


def load_tushare_stock_basic(mode: str = "http") -> list[dict]:
    mode = normalize_tushare_mode(mode)
    cache_path = tushare_stock_cache_path()
    cache = load_json(cache_path, {})
    fetched_at = cache.get("fetched_at", 0)
    if cache.get("rows") and cache.get("mode") == mode and (time.time() - fetched_at) < 86400:
        return cache["rows"]
    rows = tushare_request(
        "stock_basic",
        params={"exchange": "", "list_status": "L"},
        fields="ts_code,symbol,name,area,industry,market,exchange,cnspell,list_date,act_name",
        mode=mode,
    )
    write_json(cache_path, {"fetched_at": int(time.time()), "mode": mode, "rows": rows})
    return rows


def akshare_stock_cache_path() -> Path:
    return ensure_state_dir() / "akshare_stock_basic_cache.json"


def baostock_stock_cache_path() -> Path:
    return ensure_state_dir() / "baostock_stock_basic_cache.json"


@lru_cache(maxsize=1)
def _baostock_session_started() -> bool:
    if bs is None:
        raise RuntimeError("BaoStock fallback requested, but the optional 'baostock' package is not installed.")
    with redirect_stdout(io.StringIO()):
        result = bs.login()
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {result.error_msg}")
    return True


def load_akshare_stock_basic() -> list[dict]:
    if ak is None:
        raise RuntimeError("AkShare fallback requested, but the optional 'akshare' package is not installed.")
    cache_path = akshare_stock_cache_path()
    cache = load_json(cache_path, {})
    fetched_at = cache.get("fetched_at", 0)
    if cache.get("rows") and (time.time() - fetched_at) < 86400:
        return cache["rows"]
    frame = ak.stock_info_a_code_name()
    rows = []
    for item in frame.to_dict("records"):
        symbol = str(item.get("code") or "").zfill(6)
        if not symbol:
            continue
        ts_code = infer_cn_ts_code(symbol)
        rows.append(
            {
                "ts_code": ts_code,
                "symbol": symbol,
                "name": item.get("name") or ts_code,
                "exchange": infer_cn_exchange(ts_code),
                "source": "akshare",
            }
        )
    write_json(cache_path, {"fetched_at": int(time.time()), "rows": rows})
    return rows


def load_baostock_stock_basic(day: str | None = None) -> list[dict]:
    _baostock_session_started()
    cache_path = baostock_stock_cache_path()
    cache = load_json(cache_path, {})
    fetched_at = cache.get("fetched_at", 0)
    current_day = day or datetime.utcnow().strftime("%Y-%m-%d")
    if cache.get("rows") and cache.get("day") == current_day and (time.time() - fetched_at) < 86400:
        return cache["rows"]
    result = bs.query_all_stock(day=current_day)
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock query_all_stock failed: {result.error_msg}")
    rows = []
    while result.next():
        code, _, name = result.get_row_data()
        symbol = code.split(".", 1)[1].upper()
        ts_code = infer_cn_ts_code(symbol)
        rows.append(
            {
                "ts_code": ts_code,
                "symbol": symbol,
                "name": name or ts_code,
                "exchange": infer_cn_exchange(ts_code),
                "source": "baostock",
            }
        )
    write_json(cache_path, {"fetched_at": int(time.time()), "day": current_day, "rows": rows})
    return rows


def round_price(value: float | None) -> float | None:
    if value is None:
        return None
    if value >= 1000:
        return round(value, 2)
    if value >= 1:
        return round(value, 2)
    return round(value, 4)


def pct_change(current: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return ((current / previous) - 1.0) * 100.0


def sma(values: list[float], period: int) -> list[float | None]:
    results = []
    window_sum = 0.0
    for index, value in enumerate(values):
        window_sum += value
        if index >= period:
            window_sum -= values[index - period]
        if index + 1 < period:
            results.append(None)
        else:
            results.append(window_sum / period)
    return results


def ema(values: list[float], period: int) -> list[float | None]:
    results: list[float | None] = [None] * len(values)
    if len(values) < period:
        return results
    seed = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1)
    results[period - 1] = seed
    prev = seed
    for index in range(period, len(values)):
        prev = ((values[index] - prev) * multiplier) + prev
        results[index] = prev
    return results


def rolling_std(values: list[float], period: int) -> list[float | None]:
    results: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            results.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        results.append(math.sqrt(variance))
    return results


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    results: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return results
    gains = []
    losses = []
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    results[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
    for index in range(period + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss == 0:
            results[index] = 100.0
        else:
            rs = avg_gain / avg_loss
            results[index] = 100.0 - (100.0 / (1.0 + rs))
    return results


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    if not highs:
        return []
    true_ranges = []
    for index in range(len(highs)):
        if index == 0:
            true_ranges.append(highs[index] - lows[index])
            continue
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    results: list[float | None] = [None] * len(highs)
    if len(true_ranges) < period:
        return results
    avg_tr = sum(true_ranges[:period]) / period
    results[period - 1] = avg_tr
    for index in range(period, len(true_ranges)):
        avg_tr = ((avg_tr * (period - 1)) + true_ranges[index]) / period
        results[index] = avg_tr
    return results


def macd(values: list[float]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_line: list[float | None] = []
    for left, right in zip(ema12, ema26):
        if left is None or right is None:
            macd_line.append(None)
        else:
            macd_line.append(left - right)
    macd_values = [value if value is not None else 0.0 for value in macd_line]
    signal_line = ema(macd_values, 9)
    histogram: list[float | None] = []
    for left, right in zip(macd_line, signal_line):
        if left is None or right is None:
            histogram.append(None)
        else:
            histogram.append(left - right)
    return macd_line, signal_line, histogram


def bollinger(values: list[float], period: int = 20, width: float = 2.0):
    middle = sma(values, period)
    std = rolling_std(values, period)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for center, deviation in zip(middle, std):
        if center is None or deviation is None:
            upper.append(None)
            lower.append(None)
        else:
            upper.append(center + (deviation * width))
            lower.append(center - (deviation * width))
    return lower, middle, upper


def normalize_interval(timeframe: str, market: str) -> str:
    normalized = timeframe.lower()
    if market == "stock":
        if normalized not in TIMEFRAME_TO_YAHOO:
            raise ValueError("Stocks currently support 1d and 1h timeframes.")
        return TIMEFRAME_TO_YAHOO[normalized]
    if normalized not in TIMEFRAME_TO_BINANCE:
        raise ValueError("Crypto currently supports 1h, 4h, and 1d timeframes.")
    return TIMEFRAME_TO_BINANCE[normalized]


def normalize_td_rows(payload) -> list[dict]:
    if isinstance(payload, tuple):
        rows = list(payload)
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = payload.get("values", [])
    return rows


def parse_td_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S" if " " in value else "%Y-%m-%d")


def score_td_symbol_match(query: str, item: dict) -> tuple[int, int]:
    query_lower = query.strip().lower()
    symbol = (item.get("symbol") or "").lower()
    name = (item.get("instrument_name") or "").lower()
    country = item.get("country")
    exchange = item.get("exchange")
    score = 0
    if country == "United States":
        score += 20
    if exchange in US_EQUITY_EXCHANGES:
        score += 10
    if symbol == query_lower:
        score += 10
    if name == query_lower:
        score += 9
    if name.startswith(query_lower):
        score += 6
    if query_lower in name:
        score += 4
    return score, len(name or symbol)


def score_cn_stock_match(query: str, item: dict) -> tuple[int, int]:
    query_lower = query.strip().lower()
    ts_code = (item.get("ts_code") or "").lower()
    symbol = (item.get("symbol") or "").lower()
    name = (item.get("name") or "").lower()
    cnspell = (item.get("cnspell") or "").lower()
    score = 0
    if item.get("exchange") in CN_EQUITY_EXCHANGES:
        score += 10
    if ts_code == query_lower:
        score += 20
    if symbol == query_lower:
        score += 18
    if name == query_lower:
        score += 18
    if cnspell == query_lower:
        score += 14
    if name.startswith(query_lower) or cnspell.startswith(query_lower):
        score += 8
    if query_lower in name or query_lower in cnspell:
        score += 5
    return score, -len(name or ts_code)


def resolve_cn_stock_from_rows(query: str, rows: list[dict], source: str) -> dict:
    if not rows:
        raise RuntimeError(f"{source} returned no listed A-share symbols.")
    normalized_code = infer_cn_ts_code(query)
    exact_candidates = []
    query_upper = query.strip().upper()
    query_lower = query.strip().lower()
    for row in rows:
        if normalized_code == str(row.get("ts_code", "")).upper():
            exact_candidates.append(row)
        elif query_upper == str(row.get("symbol", "")).upper():
            exact_candidates.append(row)
        elif query_lower == str(row.get("name") or "").lower():
            exact_candidates.append(row)
        elif query_lower == str(row.get("cnspell") or "").lower():
            exact_candidates.append(row)
    candidates = exact_candidates or rows
    best = sorted(candidates, key=lambda item: score_cn_stock_match(query, item), reverse=True)[0]
    return {
        "market": "stock",
        "region": "CN",
        "source": source,
        "symbol": best.get("ts_code", normalized_code),
        "display_name": best.get("name") or best.get("ts_code", normalized_code),
        "exchange": best.get("exchange") or infer_cn_exchange(best.get("ts_code")),
        "industry": best.get("industry"),
    }


def load_cn_stock_catalog(provider: str, tushare_mode: str = "http") -> list[dict]:
    if provider.startswith("tushare-"):
        return load_tushare_stock_basic(tushare_mode)
    if provider == "akshare":
        return load_akshare_stock_basic()
    if provider == "baostock":
        return load_baostock_stock_basic()
    raise ValueError(f"Unsupported CN stock provider: {provider}")


def resolve_cn_stock_symbol(query: str, tushare_mode: str = "http") -> dict:
    tushare_mode = normalize_tushare_mode(tushare_mode)
    normalized_code = infer_cn_ts_code(query)
    query_is_code = bool(re.fullmatch(r"\d{6}(\.(SH|SZ|BJ))?", query.strip().upper()))
    fallback_code_result = {
        "market": "stock",
        "region": "CN",
        "source": "code-inference",
        "symbol": normalized_code,
        "display_name": normalized_code,
        "exchange": infer_cn_exchange(normalized_code),
    }
    if query_is_code:
        return fallback_code_result
    errors = []
    for provider in cn_stock_provider_order(tushare_mode):
        try:
            rows = load_cn_stock_catalog(provider, tushare_mode=tushare_mode)
            return resolve_cn_stock_from_rows(query, rows, provider)
        except Exception as error:
            errors.append(f"{provider}: {error}")
            if query_is_code:
                continue
    if query_is_code:
        return fallback_code_result
    raise RuntimeError("Failed to resolve A-share symbol. " + " | ".join(errors[:3]))


def resolve_stock_symbol(query: str) -> dict:
    query = query.strip()
    td = get_twelvedata_client()
    ticker_like = (
        query.upper() == query
        and query.replace(".", "").replace("-", "").isalnum()
        and " " not in query
        and len(query) <= 8
    )
    if ticker_like:
        if td is not None:
            try:
                payload = td.quote(symbol=query.upper()).as_json()
                return {
                    "market": "stock",
                    "region": "US",
                    "source": "twelvedata",
                    "symbol": payload.get("symbol", query.upper()),
                    "display_name": payload.get("name") or payload.get("symbol", query.upper()),
                    "exchange": payload.get("exchange"),
                }
            except Exception:
                pass
        else:
            return {
                "market": "stock",
                "region": "US",
                "source": "ticker-input",
                "symbol": query.upper(),
                "display_name": query.upper(),
                "exchange": None,
            }
    if td is not None:
        try:
            payload = td.symbol_search(symbol=query).as_json()
            candidates = [
                item
                for item in payload
                if item.get("instrument_type") in {"Common Stock", "ETF", "Index"}
            ]
            if candidates:
                us_candidates = [
                    item
                    for item in candidates
                    if item.get("country") == "United States" or item.get("exchange") in US_EQUITY_EXCHANGES
                ]
                if us_candidates:
                    candidates = us_candidates
                best = sorted(candidates, key=lambda item: score_td_symbol_match(query, item), reverse=True)[0]
                return {
                    "market": "stock",
                    "region": "US",
                    "source": "twelvedata",
                    "symbol": best.get("symbol", query.upper()),
                    "display_name": best.get("instrument_name") or best.get("symbol", query.upper()),
                    "exchange": best.get("exchange"),
                }
        except Exception:
            pass
    api_key = os.environ.get("TWELVEDATA_API_KEY", "demo")
    search_url = f"https://api.twelvedata.com/symbol_search?symbol={urllib.parse.quote(query)}&apikey={api_key}"
    encoded = urllib.parse.quote(query)
    yahoo_search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=8&newsCount=0"
    try:
        payload = fetch_json(search_url, headers=YAHOO_HEADERS)
        for item in payload.get("data", []):
            if item.get("instrument_type") not in {"Common Stock", "ETF", "Index"}:
                continue
            return {
                "market": "stock",
                "region": "US",
                "source": "twelvedata-http",
                "symbol": item.get("symbol", query.upper()),
                "display_name": item.get("instrument_name") or item.get("symbol", query.upper()),
                "exchange": item.get("exchange"),
            }
    except Exception:
        pass
    try:
        payload = fetch_json(yahoo_search_url, headers=YAHOO_HEADERS)
        for item in payload.get("quotes", []):
            quote_type = (item.get("quoteType") or "").upper()
            if quote_type not in {"EQUITY", "ETF", "MUTUALFUND", "INDEX"}:
                continue
            return {
                "market": "stock",
                "region": "US",
                "source": "yahoo",
                "symbol": item.get("symbol", query.upper()),
                "display_name": item.get("shortname") or item.get("longname") or item.get("symbol", query.upper()),
                "exchange": item.get("exchange"),
            }
    except Exception:
        pass
    return {
        "market": "stock",
        "region": "US",
        "source": "fallback",
        "symbol": query.upper(),
        "display_name": query.upper(),
        "exchange": None,
    }


def resolve_crypto_symbol(query: str) -> dict:
    cleaned = query.strip().lower().replace("/", "").replace("-", "")
    if cleaned in CRYPTO_ALIASES:
        symbol = CRYPTO_ALIASES[cleaned]
    else:
        upper = query.strip().upper().replace("/", "").replace("-", "")
        symbol = upper if upper.endswith("USDT") else f"{upper}USDT"
    return {
        "market": "crypto",
        "region": "global",
        "source": "binance",
        "symbol": symbol,
        "display_name": symbol,
        "exchange": "Binance",
    }


def resolve_asset(query: str, market: str = "auto", tushare_mode: str = "http") -> dict:
    tushare_mode = normalize_tushare_mode(tushare_mode)
    requested = market.lower()
    if requested == "cn-stock":
        return resolve_cn_stock_symbol(query, tushare_mode=tushare_mode)
    if requested == "us-stock":
        return resolve_stock_symbol(query)
    if requested == "stock":
        if looks_like_cn_stock_query(query):
            return resolve_cn_stock_symbol(query, tushare_mode=tushare_mode)
        return resolve_stock_symbol(query)
    if requested == "crypto":
        return resolve_crypto_symbol(query)
    lowered = query.strip().lower()
    if looks_like_cn_stock_query(query):
        return resolve_cn_stock_symbol(query, tushare_mode=tushare_mode)
    if lowered in CRYPTO_ALIASES or lowered.endswith("usdt") or lowered.endswith("usd"):
        return resolve_crypto_symbol(query)
    if " " in lowered:
        stock_result = resolve_stock_symbol(query)
        if stock_result.get("symbol"):
            return stock_result
        return resolve_crypto_symbol(query)
    try:
        return resolve_stock_symbol(query)
    except Exception:
        return resolve_crypto_symbol(query)


def fetch_stock_candles(symbol: str, timeframe: str) -> list[dict]:
    td = get_twelvedata_client()
    interval = TIMEFRAME_TO_TWELVEDATA.get(timeframe)
    outputsize = 260 if timeframe == "1d" else 500
    if td is not None and interval:
        try:
            payload = td.time_series(
                symbol=symbol,
                interval=interval,
                outputsize=outputsize,
                timezone="America/New_York",
            ).as_json()
            rows = normalize_td_rows(payload)
            if rows:
                candles = []
                for row in reversed(rows):
                    dt = parse_td_datetime(row["datetime"])
                    candles.append(
                        {
                            "timestamp": int(dt.timestamp()),
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume", 0.0)),
                        }
                    )
                return candles
        except Exception:
            pass

    api_key = os.environ.get("TWELVEDATA_API_KEY", "demo")
    if interval:
        url = (
            "https://api.twelvedata.com/time_series"
            f"?symbol={urllib.parse.quote(symbol)}&interval={interval}&outputsize={outputsize}&apikey={api_key}"
        )
        try:
            payload = fetch_json(url, headers=YAHOO_HEADERS)
            if payload.get("status") != "error" and payload.get("values"):
                candles = []
                for row in reversed(payload["values"]):
                    dt = parse_td_datetime(row["datetime"])
                    candles.append(
                        {
                            "timestamp": int(dt.timestamp()),
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume", 0.0)),
                        }
                    )
                return candles
        except Exception:
            pass

    interval = normalize_interval(timeframe, "stock")
    price_range = "60d" if interval == "60m" else "1y"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?range={price_range}&interval={interval}&includePrePost=false&events=div%2Csplits"
    )
    payload = fetch_json(url, headers=YAHOO_HEADERS)
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    candles = []
    for timestamp, open_value, high_value, low_value, close_value, volume_value in zip(
        result.get("timestamp", []),
        quote.get("open", []),
        quote.get("high", []),
        quote.get("low", []),
        quote.get("close", []),
        quote.get("volume", []),
    ):
        if None in (open_value, high_value, low_value, close_value):
            continue
        candles.append(
            {
                "timestamp": int(timestamp),
                "open": float(open_value),
                "high": float(high_value),
                "low": float(low_value),
                "close": float(close_value),
                "volume": float(volume_value or 0.0),
            }
        )
    return candles


def fetch_cn_stock_candles_from_tushare(symbol: str, timeframe: str, tushare_mode: str = "http") -> list[dict]:
    tushare_mode = normalize_tushare_mode(tushare_mode)
    normalized_symbol = infer_cn_ts_code(symbol)
    if timeframe == "1d":
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=540)
        rows = tushare_request(
            "daily",
            params={
                "ts_code": normalized_symbol,
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            },
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
            mode=tushare_mode,
        )
        candles = []
        for row in reversed(rows):
            trade_date = row.get("trade_date")
            if not trade_date:
                continue
            dt = parse_cn_date(trade_date)
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("vol", 0.0)),
                }
            )
        return candles
    if timeframe == "1h":
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=180)
        rows = tushare_request(
            "stk_mins",
            params={
                "ts_code": normalized_symbol,
                "freq": TIMEFRAME_TO_TUSHARE[timeframe],
                "start_date": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            fields="ts_code,trade_time,open,high,low,close,vol,amount",
            mode=tushare_mode,
        )
        candles = []
        for row in reversed(rows):
            trade_time = row.get("trade_time")
            if not trade_time:
                continue
            dt = parse_cn_trade_time(trade_time)
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("vol", 0.0)),
                }
            )
        return candles
    raise ValueError("A-share stocks currently support 1d and 1h timeframes.")


def fetch_cn_stock_candles_from_akshare(symbol: str, timeframe: str) -> list[dict]:
    if ak is None:
        raise RuntimeError("AkShare fallback requested, but the optional 'akshare' package is not installed.")
    normalized_symbol = infer_cn_ts_code(symbol)
    pure_symbol = normalized_symbol.split(".", 1)[0]
    if timeframe == "1d":
        end_date = datetime.utcnow().strftime("%Y%m%d")
        start_date = (datetime.utcnow() - timedelta(days=540)).strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist(
            symbol=pure_symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
        candles = []
        for row in frame.to_dict("records"):
            dt_value = row.get("日期")
            if not dt_value:
                continue
            dt = datetime.combine(dt_value, datetime.min.time()) if not isinstance(dt_value, str) else datetime.strptime(dt_value, "%Y-%m-%d")
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": safe_float(row.get("开盘")),
                    "high": safe_float(row.get("最高")),
                    "low": safe_float(row.get("最低")),
                    "close": safe_float(row.get("收盘")),
                    "volume": safe_float(row.get("成交量")),
                }
            )
        return candles
    if timeframe == "1h":
        end_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        start_date = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
        frame = ak.stock_zh_a_hist_min_em(
            symbol=pure_symbol,
            period="60",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
        candles = []
        for row in frame.to_dict("records"):
            dt_value = row.get("时间")
            if not dt_value:
                continue
            dt = parse_cn_trade_time(str(dt_value))
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": safe_float(row.get("开盘")),
                    "high": safe_float(row.get("最高")),
                    "low": safe_float(row.get("最低")),
                    "close": safe_float(row.get("收盘")),
                    "volume": safe_float(row.get("成交量")),
                }
            )
        return candles
    raise ValueError("A-share stocks currently support 1d and 1h timeframes.")


def fetch_cn_stock_candles_from_baostock(symbol: str, timeframe: str) -> list[dict]:
    _baostock_session_started()
    normalized_symbol = infer_cn_ts_code(symbol)
    suffix = normalized_symbol.rsplit(".", 1)[1].lower()
    provider_symbol = f"{suffix}.{normalized_symbol.split('.', 1)[0]}"
    if timeframe == "1d":
        result = bs.query_history_k_data_plus(
            provider_symbol,
            "date,code,open,high,low,close,volume,amount",
            start_date=(datetime.utcnow() - timedelta(days=540)).strftime("%Y-%m-%d"),
            end_date=datetime.utcnow().strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="3",
        )
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock daily failed: {result.error_msg}")
        candles = []
        while result.next():
            row = result.get_row_data()
            dt = datetime.strptime(row[0], "%Y-%m-%d")
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": safe_float(row[2]),
                    "high": safe_float(row[3]),
                    "low": safe_float(row[4]),
                    "close": safe_float(row[5]),
                    "volume": safe_float(row[6]),
                }
            )
        return candles
    if timeframe == "1h":
        result = bs.query_history_k_data_plus(
            provider_symbol,
            "date,time,code,open,high,low,close,volume,amount",
            start_date=(datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"),
            end_date=datetime.utcnow().strftime("%Y-%m-%d"),
            frequency="60",
            adjustflag="3",
        )
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock 60min failed: {result.error_msg}")
        candles = []
        while result.next():
            row = result.get_row_data()
            dt = datetime.strptime(row[1][:14], "%Y%m%d%H%M%S")
            candles.append(
                {
                    "timestamp": int(dt.timestamp()),
                    "open": safe_float(row[3]),
                    "high": safe_float(row[4]),
                    "low": safe_float(row[5]),
                    "close": safe_float(row[6]),
                    "volume": safe_float(row[7]),
                }
            )
        return candles
    raise ValueError("A-share stocks currently support 1d and 1h timeframes.")


def fetch_cn_stock_candles(symbol: str, timeframe: str, tushare_mode: str = "http") -> tuple[list[dict], str]:
    errors = []
    for provider in cn_stock_provider_order(tushare_mode):
        try:
            if provider.startswith("tushare-"):
                return fetch_cn_stock_candles_from_tushare(symbol, timeframe, tushare_mode), provider
            if provider == "akshare":
                return fetch_cn_stock_candles_from_akshare(symbol, timeframe), provider
            if provider == "baostock":
                return fetch_cn_stock_candles_from_baostock(symbol, timeframe), provider
        except Exception as error:
            errors.append(f"{provider}: {error}")
            continue
    raise RuntimeError("Failed to fetch A-share candles. " + " | ".join(errors[:3]))


def fetch_crypto_candles(symbol: str, timeframe: str) -> list[dict]:
    interval = normalize_interval(timeframe, "crypto")
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={urllib.parse.quote(symbol)}&interval={interval}&limit=500"
    )
    payload = fetch_json(url)
    candles = []
    for row in payload:
        candles.append(
            {
                "timestamp": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return candles


def fetch_candles(asset: dict, timeframe: str, tushare_mode: str = "http") -> tuple[list[dict], str | None]:
    if asset["market"] == "stock":
        if asset.get("region") == "CN" or str(asset.get("source", "")).startswith("tushare"):
            return fetch_cn_stock_candles(asset["symbol"], timeframe, tushare_mode=tushare_mode)
        return fetch_stock_candles(asset["symbol"], timeframe), asset.get("source")
    return fetch_crypto_candles(asset["symbol"], timeframe), asset.get("source")


def summarize_learning(memory: dict, tags: list[str]) -> list[str]:
    insights = []
    stats = memory.get("tag_stats", {})
    for tag in tags:
        tag_stat = stats.get(tag)
        if not tag_stat:
            continue
        total = tag_stat.get("wins", 0) + tag_stat.get("losses", 0) + tag_stat.get("invalidated", 0)
        if total < 3:
            continue
        win_rate = tag_stat.get("wins", 0) / total
        insights.append(
            f"Workspace memory on {tag}: {tag_stat.get('wins', 0)}/{total} labeled cases succeeded ({win_rate:.0%})."
        )
    return insights[:2]


def classify_regimes(score: int, rsi_value: float | None, volume_ratio: float | None, close: float, resistance: float, support: float) -> list[str]:
    tags = []
    if score >= 20:
        tags.append("trend-following")
    if score <= -20:
        tags.append("risk-off")
    if rsi_value is not None and rsi_value < 35:
        tags.append("mean-reversion")
    if rsi_value is not None and rsi_value > 70:
        tags.append("overbought")
    if volume_ratio is not None and volume_ratio >= 1.5 and close >= resistance * 0.995:
        tags.append("breakout")
    if close <= support * 1.005:
        tags.append("support-test")
    return tags


def _snapshot(candles: list[dict], timeframe: str) -> dict:
    closes = [candle["close"] for candle in candles]
    highs = [candle["high"] for candle in candles]
    lows = [candle["low"] for candle in candles]
    volumes = [candle["volume"] for candle in candles]
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    rsi14 = rsi(closes, 14)
    macd_line, signal_line, macd_hist = macd(closes)
    bb_lower, bb_middle, bb_upper = bollinger(closes, 20, 2.0)
    atr14 = atr(highs, lows, closes, 14)
    avg_volume20 = sma(volumes, 20)

    close = closes[-1]
    volume = volumes[-1]
    support_window = lows[-21:-1] if len(lows) > 21 else lows[:-1] or lows
    resistance_window = highs[-21:-1] if len(highs) > 21 else highs[:-1] or highs
    support = min(support_window)
    resistance = max(resistance_window)
    atr_value = atr14[-1]
    atr_pct = ((atr_value / close) * 100.0) if atr_value else None
    volume_ratio = (volume / avg_volume20[-1]) if avg_volume20[-1] else None

    score = 0
    reasons = []
    risks = []

    if sma50[-1] is not None:
        if close > sma50[-1]:
            score += 18
            reasons.append("Price is holding above the 50-period average, which supports trend continuation.")
        else:
            score -= 18
            risks.append("Price is below the 50-period average, which weakens trend quality.")

    if sma20[-1] is not None and sma50[-1] is not None:
        if sma20[-1] > sma50[-1]:
            score += 12
            reasons.append("The short-term trend is stronger than the medium-term trend.")
        else:
            score -= 12
            risks.append("The short-term average remains below the medium-term average.")

    if sma200[-1] is not None and sma50[-1] is not None:
        if sma50[-1] > sma200[-1]:
            score += 10
            reasons.append("The medium-term trend still sits above the long-term baseline.")
        else:
            score -= 10
            risks.append("The medium-term trend is below the long-term baseline.")

    if macd_hist[-1] is not None:
        if macd_hist[-1] > 0:
            score += 12
            reasons.append("MACD momentum is positive.")
        else:
            score -= 12
            risks.append("MACD momentum is negative.")

    if rsi14[-1] is not None:
        if rsi14[-1] < 32:
            score += 16
            reasons.append("RSI is in an oversold zone, which supports a rebound setup.")
        elif rsi14[-1] > 72:
            score -= 16
            risks.append("RSI is stretched into an overbought zone.")
        elif 45 <= rsi14[-1] <= 65:
            score += 8
            reasons.append("RSI is in a healthy momentum range rather than at an exhaustion extreme.")

    if volume_ratio is not None and volume_ratio >= 1.5 and close >= resistance * 0.995:
        score += 18
        reasons.append("Price is pressing resistance with above-average volume, which supports a breakout thesis.")
    elif volume_ratio is not None and volume_ratio < 0.8:
        risks.append("Volume is light relative to the recent average, so conviction is weaker.")

    if close <= support * 1.005 and macd_hist[-1] is not None and macd_hist[-1] < 0:
        score -= 18
        risks.append("Price is leaning on support while momentum remains negative.")

    volatility_limit = {"1h": 3.0, "4h": 4.5, "1d": 6.0}.get(timeframe, 5.0)
    if atr_pct is not None and atr_pct > volatility_limit:
        score -= 8
        risks.append("ATR volatility is elevated, which makes precise entries harder.")

    score = max(-100, min(100, score))
    tags = classify_regimes(score, rsi14[-1], volume_ratio, close, resistance, support)
    confidence = "high" if abs(score) >= 55 else "medium" if abs(score) >= 25 else "low"

    if score >= 45:
        recommendation = "buy-or-add"
    elif score >= 20:
        recommendation = "watch-for-buy-confirmation"
    elif score <= -45:
        recommendation = "sell-or-avoid"
    elif score <= -20:
        recommendation = "reduce-or-tighten-risk"
    else:
        recommendation = "hold-and-wait"

    buy_candidates = [support, sma20[-1], bb_middle[-1], bb_lower[-1]]
    pullback_candidates = [value for value in buy_candidates if value is not None and value <= close]
    reclaim_candidates = [value for value in [sma20[-1], bb_middle[-1], resistance * 1.002] if value is not None and value > close]
    pullback_buy = max(pullback_candidates) if pullback_candidates else None
    first_buy = pullback_buy
    confirmation_buy = min(reclaim_candidates) if reclaim_candidates else resistance * 1.002
    breakout_buy = resistance * 1.002
    defensive_sell = support * 0.998
    take_profit_1 = resistance if close < resistance else close + (atr_value or close * 0.02) * 1.5
    take_profit_2 = close + (atr_value or close * 0.02) * 3.0
    reclaim_level = resistance * 1.002
    stop_loss = min(
        value for value in [support, sma20[-1], bb_lower[-1]] if value is not None
    ) - ((atr_value or close * 0.02) * 0.5)

    if recommendation in {"buy-or-add", "watch-for-buy-confirmation"}:
        best_buy = breakout_buy if "breakout" in tags else (first_buy or confirmation_buy)
        best_sell = take_profit_1
    elif recommendation in {"sell-or-avoid", "reduce-or-tighten-risk"}:
        best_buy = confirmation_buy
        best_sell = close
    else:
        best_buy = first_buy or confirmation_buy
        best_sell = take_profit_1

    return {
        "price": close,
        "score": int(score),
        "confidence": confidence,
        "recommendation": recommendation,
        "best_buy_level": round_price(best_buy),
        "first_buy_level": round_price(first_buy),
        "confirmation_buy_level": round_price(confirmation_buy),
        "best_sell_level": round_price(best_sell),
        "stop_loss": round_price(stop_loss),
        "defensive_sell_trigger": round_price(defensive_sell),
        "take_profit_2": round_price(take_profit_2),
        "support": round_price(support),
        "resistance": round_price(resistance),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "atr_percent": round(atr_pct, 2) if atr_pct is not None else None,
        "rsi14": round(rsi14[-1], 2) if rsi14[-1] is not None else None,
        "macd_histogram": round(macd_hist[-1], 4) if macd_hist[-1] is not None else None,
        "sma20": round_price(sma20[-1]),
        "sma50": round_price(sma50[-1]),
        "sma200": round_price(sma200[-1]),
        "reasons": reasons[:5],
        "risks": risks[:5],
        "tags": tags,
    }


def backtest_snapshot(candles: list[dict], timeframe: str) -> dict:
    horizon = {"1h": 12, "4h": 6, "1d": 5}.get(timeframe, 5)
    min_history = 60
    bullish_returns = []
    bearish_returns = []
    for index in range(min_history, len(candles) - horizon):
        subset = candles[: index + 1]
        snapshot = _snapshot(subset, timeframe)
        current = subset[-1]["close"]
        future = candles[index + horizon]["close"]
        if snapshot["score"] >= 35:
            bullish_returns.append(((future / current) - 1.0) * 100.0)
        elif snapshot["score"] <= -35:
            bearish_returns.append((1.0 - (future / current)) * 100.0)

    def summarize(values: list[float]) -> dict:
        if not values:
            return {"count": 0, "win_rate": None, "avg_return": None}
        wins = sum(1 for value in values if value > 0)
        return {
            "count": len(values),
            "win_rate": round((wins / len(values)) * 100.0, 1),
            "avg_return": round(sum(values) / len(values), 2),
        }

    return {
        "horizon_bars": horizon,
        "bullish": summarize(bullish_returns),
        "bearish": summarize(bearish_returns),
    }


def analyze(
    asset_query: str,
    market: str = "auto",
    timeframe: str = "1d",
    memory_file: Path | None = None,
    tushare_mode: str = "http",
) -> dict:
    tushare_mode = normalize_tushare_mode(tushare_mode)
    asset = resolve_asset(asset_query, market, tushare_mode=tushare_mode)
    candles, data_source = fetch_candles(asset, timeframe, tushare_mode=tushare_mode)
    if data_source and asset.get("region") == "CN":
        asset = {**asset, "data_source": data_source}
    if len(candles) < 60:
        raise RuntimeError("Not enough market data was returned to compute the strategy stack.")
    snapshot = _snapshot(candles, timeframe)
    memory_path = memory_file or default_memory_path()
    memory = load_json(memory_path, {"feedback": [], "tag_stats": {}})
    learning_insights = summarize_learning(memory, snapshot["tags"])
    backtest = backtest_snapshot(candles, timeframe)
    change_5 = pct_change(candles[-1]["close"], candles[-6]["close"] if len(candles) >= 6 else None)
    change_20 = pct_change(candles[-1]["close"], candles[-21]["close"] if len(candles) >= 21 else None)
    return {
        "generated_at": int(time.time()),
        "asset": asset,
        "data_source": data_source,
        "timeframe": timeframe,
        "current_price": round_price(snapshot["price"]),
        "price_change_5_bars_pct": round(change_5, 2) if change_5 is not None else None,
        "price_change_20_bars_pct": round(change_20, 2) if change_20 is not None else None,
        "recommendation": snapshot["recommendation"],
        "confidence": snapshot["confidence"],
        "score": snapshot["score"],
        "levels": {
            "best_buy_level": snapshot["best_buy_level"],
            "first_buy_level": snapshot["first_buy_level"],
            "confirmation_buy_level": snapshot["confirmation_buy_level"],
            "best_sell_level": snapshot["best_sell_level"],
            "stop_loss": snapshot["stop_loss"],
            "defensive_sell_trigger": snapshot["defensive_sell_trigger"],
            "take_profit_2": snapshot["take_profit_2"],
            "support": snapshot["support"],
            "resistance": snapshot["resistance"],
        },
        "signals": {
            "rsi14": snapshot["rsi14"],
            "macd_histogram": snapshot["macd_histogram"],
            "atr_percent": snapshot["atr_percent"],
            "volume_ratio": snapshot["volume_ratio"],
            "sma20": snapshot["sma20"],
            "sma50": snapshot["sma50"],
            "sma200": snapshot["sma200"],
        },
        "reasons": snapshot["reasons"],
        "risks": snapshot["risks"],
        "tags": snapshot["tags"],
        "learning_insights": learning_insights,
        "backtest": backtest,
        "disclaimer": (
            "Research support only. Quant signals can fail during news shocks, earnings, "
            "macro events, or liquidity stress."
        ),
    }


def recommendation_label(value: str) -> str:
    return {
        "buy-or-add": "Buy / Add",
        "watch-for-buy-confirmation": "Watch For Buy Confirmation",
        "hold-and-wait": "Hold / Wait",
        "reduce-or-tighten-risk": "Reduce / Tighten Risk",
        "sell-or-avoid": "Sell / Avoid",
    }.get(value, value)


def format_markdown(report: dict) -> str:
    levels = report["levels"]
    market_label = report["asset"]["market"]
    if report["asset"].get("region"):
        market_label = f"{market_label} ({report['asset']['region']})"
    lines = [
        f"# {report['asset']['display_name']} ({report['asset']['symbol']})",
        "",
        f"- Market: {market_label}",
        f"- Data source: {report.get('data_source') or report['asset'].get('data_source') or report['asset'].get('source')}",
        f"- Timeframe: {report['timeframe']}",
        f"- Current price: {report['current_price']}",
        f"- Recommendation: {recommendation_label(report['recommendation'])}",
        f"- Confidence: {report['confidence']}",
        f"- Composite score: {report['score']}",
        "",
        "## Levels",
        "",
        f"- Best buy level: {levels['best_buy_level']}",
        f"- First buy level: {levels.get('first_buy_level')}",
        f"- Confirmation buy level: {levels.get('confirmation_buy_level')}",
        f"- Best sell level: {levels['best_sell_level']}",
        f"- Stop loss: {levels['stop_loss']}",
        f"- Defensive sell trigger: {levels['defensive_sell_trigger']}",
        f"- Secondary take-profit: {levels['take_profit_2']}",
        "",
        "## Why",
        "",
    ]
    for reason in report["reasons"]:
        lines.append(f"- {reason}")
    if report["risks"]:
        lines.extend(["", "## Risks", ""])
        for risk in report["risks"]:
            lines.append(f"- {risk}")
    signals = report["signals"]
    lines.extend(
        [
            "",
            "## Signal Snapshot",
            "",
            f"- RSI14: {signals['rsi14']}",
            f"- MACD histogram: {signals['macd_histogram']}",
            f"- ATR percent: {signals['atr_percent']}",
            f"- Volume ratio: {signals['volume_ratio']}",
            f"- SMA20 / SMA50 / SMA200: {signals['sma20']} / {signals['sma50']} / {signals['sma200']}",
        ]
    )
    backtest = report["backtest"]
    lines.extend(
        [
            "",
            "## Walk-Forward Check",
            "",
            f"- Bullish signals: {backtest['bullish']['count']} samples, win rate {backtest['bullish']['win_rate']}%, average return {backtest['bullish']['avg_return']}%",
            f"- Bearish signals: {backtest['bearish']['count']} samples, win rate {backtest['bearish']['win_rate']}%, average return {backtest['bearish']['avg_return']}%",
        ]
    )
    if report["learning_insights"]:
        lines.extend(["", "## Workspace Memory", ""])
        for insight in report["learning_insights"]:
            lines.append(f"- {insight}")
    lines.extend(["", f"_Disclaimer: {report['disclaimer']}_"])
    return "\n".join(lines) + "\n"


def update_learning(report: dict, outcome: str, realized_return: float | None, notes: str, memory_file: Path | None = None) -> dict:
    path = memory_file or default_memory_path()
    memory = load_json(path, {"feedback": [], "tag_stats": {}})
    record = {
        "generated_at": report.get("generated_at"),
        "asset": report.get("asset", {}),
        "timeframe": report.get("timeframe"),
        "recommendation": report.get("recommendation"),
        "score": report.get("score"),
        "tags": report.get("tags", []),
        "outcome": outcome,
        "realized_return": realized_return,
        "notes": notes,
        "recorded_at": int(time.time()),
    }
    memory.setdefault("feedback", []).append(record)
    stats = memory.setdefault("tag_stats", {})
    for tag in record["tags"]:
        tag_stat = stats.setdefault(tag, {"wins": 0, "losses": 0, "invalidated": 0, "average_return": None, "return_samples": []})
        if outcome == "win":
            tag_stat["wins"] += 1
        elif outcome == "loss":
            tag_stat["losses"] += 1
        else:
            tag_stat["invalidated"] += 1
        if realized_return is not None:
            tag_stat.setdefault("return_samples", []).append(realized_return)
            samples = tag_stat["return_samples"]
            tag_stat["average_return"] = round(sum(samples) / len(samples), 2)
    write_json(path, memory)
    return memory


def send_notification(notifier: dict, message: str, payload: dict | None = None) -> None:
    notifier_type = notifier.get("type", "stdout")
    if notifier_type == "stdout":
        print(message)
        return
    if notifier_type == "webhook":
        url = notifier["url"]
        post_json(url, payload or {"message": message, "text": message})
        return
    if notifier_type == "openclaw":
        command = ["openclaw", "message", "send", "--target", notifier["target"], "--message", message]
        channel = notifier.get("channel")
        if channel:
            command.extend(["--channel", channel])
        subprocess.run(command, check=True)
        return
    raise ValueError(f"Unsupported notifier type: {notifier_type}")
