import time
import requests
import pandas as pd

BASE_URL = "https://apilist.tronscanapi.com/api/token_trc20/transfers"


def _headers(api_key: str | None) -> dict:
    """
    Tronscan иногда принимает API key в таком заголовке.
    Если ключа нет — просто без заголовка.
    """
    if api_key and str(api_key).strip():
        return {"TRON-PRO-API-KEY": str(api_key).strip()}
    return {}


def _safe_get(url: str, params: dict, headers: dict, timeout: int = 30) -> dict:
    """
    GET с минимальной защитой:
    - ретраи на 429/5xx
    """
    last_err = None
    for attempt in range(1, 6):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            # rate limit
            if r.status_code in (429, 503, 502, 504, 500):
                time.sleep(min(2 ** attempt, 10))
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = str(e)
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Tronscan request failed after retries. Last error: {last_err}")


def fetch_trc20_transfers(wallet: str, start_ts: int, end_ts: int, api_key: str | None = None) -> pd.DataFrame:
    """
    Забирает TRC20 Transfers для адреса за период (timestamp в миллисекундах).

    Возвращает DataFrame со столбцами:
    hash, from, to, amount, timestamp, token_symbol, token_address
    """
    w = str(wallet).strip()
    headers = _headers(api_key)

    all_rows = []
    start = 0
    limit = 50  # Tronscan обычно ок с 50/100. Оставим 50 как стабильное.

    while True:
        params = {
            "relatedAddress": w,
            "start_timestamp": int(start_ts),
            "end_timestamp": int(end_ts),
            "start": start,
            "limit": limit,
            "sort": "-timestamp",  # по убыванию времени
        }

        data = _safe_get(BASE_URL, params=params, headers=headers)

        transfers = data.get("token_transfers") or data.get("data") or []
        if not transfers:
            break

        for t in transfers:
            token_info = t.get("tokenInfo") or {}
            decimals = token_info.get("tokenDecimal", token_info.get("decimals", 6))
            try:
                decimals = int(decimals)
            except Exception:
                decimals = 6

            # quant — обычно строка с целым числом в минимальных единицах
            quant_raw = t.get("quant", t.get("amount", 0))
            try:
                quant_int = float(quant_raw)
            except Exception:
                quant_int = 0.0

            amount = quant_int / (10 ** decimals) if decimals >= 0 else quant_int

            all_rows.append({
                "hash": t.get("transaction_id") or t.get("hash") or "",
                "from": t.get("from_address") or t.get("from") or "",
                "to": t.get("to_address") or t.get("to") or "",
                "amount": float(amount),
                "timestamp": t.get("block_ts") or t.get("timestamp") or 0,
                "token_symbol": token_info.get("tokenAbbr") or token_info.get("symbol") or "",
                "token_address": token_info.get("tokenId") or token_info.get("address") or "",
            })

        start += limit

        total = data.get("total")
        # если total отдан корректно — можем завершить
        if isinstance(total, int) and start >= total:
            break

        # если total нет/не int — просто продолжаем, но перестанем, если пришло меньше limit
        if len(transfers) < limit:
            break

        # анти-бан: маленькая пауза (особенно без API key)
        if not (api_key and str(api_key).strip()):
            time.sleep(0.2)

    df = pd.DataFrame(all_rows)

    # если в выгрузке несколько токенов — это ок, мы дальше суммируем "как есть"
    # при желании можно будет добавить фильтр только на USDT или любой token_address.

    return df
