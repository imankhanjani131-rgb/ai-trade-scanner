import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://api.toobit.com"
TIMEOUT = 25
INTERVAL = "15m"

OUT_FILE = Path("snapshot_new_listings.json")

TESTS = {
    "RE": {
        "wanted_symbol": "RE-SWAP-USDT",
        "listing_date": "2026-06-18",
    },
    "GRVT": {
        "wanted_symbol": "GRVT-SWAP-USDT",
        "listing_date": "2026-08-03",
    },
    "DOS": {
        "wanted_symbol": "DOS-SWAP-USDT",
        "listing_date": "2026-08-12",
    },
    "MARSCOIN": {
        "wanted_symbol": "MARSCOIN-SWAP-USDT",
        "listing_date": "2026-09-01",
    },
    "CASHCAT": {
        "wanted_symbol": "CASHCAT-SWAP-USDT",
        "listing_date": "2026-09-04",
    },
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ai-trade-scanner-new-listing-snapshot/1.0"
})


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def iso_utc(ms):
    return datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_json(url, params=None, retries=4):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except Exception as exc:
            last_error = exc
            print(
                f"REQUEST ERROR attempt {attempt}/{retries}:",
                repr(exc),
            )

            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(
        f"Request failed after {retries} attempts: {last_error!r}"
    )


def extract_contracts(payload):
    if isinstance(payload, dict):
        contracts = payload.get("contracts")

        if isinstance(contracts, list):
            return contracts

        data = payload.get("data")

        if isinstance(data, dict):
            contracts = data.get("contracts")

            if isinstance(contracts, list):
                return contracts

    return []


def fetch_contracts():
    payload = get_json(
        f"{BASE}/api/v1/exchangeInfo"
    )
    return extract_contracts(payload)


def resolve_symbol(wanted_symbol, token, contracts):
    wanted_upper = wanted_symbol.upper()
    token_upper = token.upper()

    all_symbols = []

    for item in contracts:
        symbol = str(
            item.get("symbol", "")
        ).upper()

        if symbol:
            all_symbols.append(symbol)

        if symbol == wanted_upper:
            return symbol, []

    candidates = []

    for symbol in all_symbols:
        if (
            token_upper in symbol
            and symbol.endswith("-SWAP-USDT")
        ):
            candidates.append(symbol)

    if len(candidates) == 1:
        return candidates[0], candidates

    return wanted_upper, candidates


def extract_kline_rows(payload):
    if isinstance(payload, list):
        raw = payload

    elif isinstance(payload, dict):
        raw = payload.get("data", [])

        if isinstance(raw, dict):
            raw = (
                raw.get("list")
                or raw.get("rows")
                or raw.get("klines")
                or []
            )

    else:
        raw = []

    rows = []

    for x in raw:
        if not isinstance(x, list) or len(x) < 6:
            continue

        try:
            row = {
                "t": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5]),
            }

        except (TypeError, ValueError):
            continue

        if min(
            row["o"],
            row["h"],
            row["l"],
            row["c"],
        ) <= 0:
            continue

        rows.append(row)

    return rows


def fetch_chunk(symbol, start_dt, end_dt):
    payload = get_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": to_ms(start_dt),
            "endTime": to_ms(end_dt),
            "limit": 1000,
        },
    )

    return extract_kline_rows(payload)


def fetch_snapshot_window(symbol, listing_date):
    listing = datetime.fromisoformat(
        listing_date
    ).replace(tzinfo=timezone.utc)

    # یک روز قبل تا هفت روز بعد
    start = listing - timedelta(days=1)
    end = listing + timedelta(days=8)

    # درخواست‌های ۶ ساعته برای ثبات بیشتر
    chunk = timedelta(hours=6)

    by_time = {}
    cursor = start

    while cursor < end:
        chunk_end = min(
            cursor + chunk,
            end,
        )

        print(
            f"Fetch {symbol}: "
            f"{cursor.isoformat()} -> {chunk_end.isoformat()}"
        )

        rows = fetch_chunk(
            symbol,
            cursor,
            chunk_end,
        )

        for row in rows:
            t = row["t"]

            if (
                to_ms(start)
                <= t
                < to_ms(end)
            ):
                by_time[t] = row

        cursor = chunk_end
        time.sleep(0.12)

    rows = sorted(
        by_time.values(),
        key=lambda x: x["t"],
    )

    return rows


def first_traded_index(rows):
    for i, row in enumerate(rows):
        if row["v"] > 0:
            return i

    return None


def stable_hash(rows):
    compact = [
        [
            x["t"],
            x["o"],
            x["h"],
            x["l"],
            x["c"],
            x["v"],
        ]
        for x in rows
    ]

    raw = json.dumps(
        compact,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(
        raw
    ).hexdigest()


def main():
    print("NEW LISTING DATA SNAPSHOT")
    print("Live Hunter is NOT changed.")
    print()

    contracts
