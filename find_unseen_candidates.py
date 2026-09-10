import json
import time
from datetime import datetime, timedelta, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

LOOKBACK_DAYS = 10
MIN_AGE_HOURS = 76
MAX_AGE_HOURS = LOOKBACK_DAYS * 24
MAX_OUTPUT = 20

# هر ارزی که تا الان در ساخت، تنظیم یا Validation استفاده کرده‌ایم
# از تست Unseen بعدی حذف می‌شود.
EXCLUDED_TOKENS = {
    "RE",
    "GRVT",
    "DOS",
    "MARSCOIN",
    "CASHCAT",
    "PONS",
    "CAPAPP",
    "GRAM",
    "DATAIP",
    "ZEST",
    "BTW",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ai-trade-scanner-unseen-candidate-finder/1.0"
})


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def fmt_time(ms_value):
    return datetime.fromtimestamp(
        ms_value / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")


def request_json(url, params=None, retries=4):
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
                f"REQUEST ERROR {attempt}/{retries}: "
                f"{repr(exc)}"
            )

            if attempt < retries:
                time.sleep(1.2 * attempt)

    raise RuntimeError(
        f"Request failed after {retries} attempts: "
        f"{last_error!r}"
    )


def get_contracts():
    payload = request_json(
        f"{BASE}/api/v1/exchangeInfo"
    )

    if not isinstance(payload, dict):
        return []

    contracts = payload.get("contracts")

    if isinstance(contracts, list):
        return contracts

    data = payload.get("data")

    if isinstance(data, dict):
        contracts = data.get("contracts")

        if isinstance(contracts, list):
            return contracts

    return []


def normalize_categories(item):
    raw = item.get("categories", [])

    if not isinstance(raw, list):
        return []

    return [
        str(x).strip()
        for x in raw
        if str(x).strip()
    ]


def token_from_symbol(symbol):
    suffix = "-SWAP-USDT"

    if symbol.endswith(suffix):
        return symbol[:-len(suffix)]

    return symbol


def eligible_contract(item):
    if not isinstance(item, dict):
        return False

    symbol = str(
        item.get("symbol", "")
    ).upper()

    status = str(
        item.get("status", "")
    ).upper()

    quote = str(
        item.get("quoteAsset", "")
    ).upper()

    categories = [
        x.upper()
        for x in normalize_categories(item)
    ]

    if not symbol.endswith("-SWAP-USDT"):
        return False

    if status != "TRADING":
        return False

    if quote and quote != "USDT":
        return False

    # فقط قراردادهایی که خود Toobit در دسته New گذاشته.
    if "NEW" not in categories:
        return False

    # Stock / TradFi وارد تست کریپتو نشود.
    if "TRADFI" in categories:
        return False

    if item.get("isRwa") is True:
        return False

    rwa_type = str(
        item.get("rwaType", "")
    ).strip()

    if rwa_type:
        return False

    token = token_from_symbol(symbol)

    if token in EXCLUDED_TOKENS:
        return False

    return True


def extract_rows(payload):
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

    for item in raw:
        if not isinstance(item, list):
            continue

        if len(item) < 6:
            continue

        try:
            row = {
                "t": int(item[0]),
                "o": float(item[1]),
                "h": float(item[2]),
                "l": float(item[3]),
                "c": float(item[4]),
                "v": float(item[5]),
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

    rows.sort(
        key=lambda x: x["t"]
    )

    return rows


def fetch_recent_15m(symbol, start_dt, end_dt):
    payload = request_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": to_ms(start_dt),
            "endTime": to_ms(end_dt),
            "limit": 1000,
        },
    )

    return extract_rows(payload)


def first_real_trade(rows):
    for row in rows:
        if row["v"] > 0:
            return row

    return None


def detect_candidate(symbol, now):
    window_start = now - timedelta(
        days=LOOKBACK_DAYS
    )

    try:
        rows = fetch_recent_15m(
            symbol,
            window_start,
            now,
        )

    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "REQUEST_ERROR",
            "error": repr(exc),
        }

    if not rows:
        return {
            "symbol": symbol,
            "status": "NO_DATA",
        }

    first = first_real_trade(rows)

    if first is None:
        return {
            "symbol": symbol,
            "status": "NO_VOLUME_DATA",
        }

    first_dt = datetime.fromtimestamp(
        first["t"] / 1000,
        tz=timezone.utc,
    )

    # اگر اولین کندل تقریباً از ابتدای پنجره 10 روزه باشد،
    # احتمالاً قرارداد قدیمی‌تر از 10 روز است.
    boundary_gap = (
        first_dt - window_start
    ).total_seconds() / 60

    if boundary_gap <= 45:
        return {
            "symbol": symbol,
            "status": "OLDER_THAN_LOOKBACK",
            "first_seen": first_dt,
            "bars": len(rows),
        }

    age_hours = (
        now - first_dt
    ).total_seconds() / 3600

    if age_hours < MIN_AGE_HOURS:
        return {
            "symbol": symbol,
            "status": "TOO_NEW",
            "first_seen": first_dt,
            "age_hours": age_hours,
            "bars": len(rows),
        }

    if age_hours > MAX_AGE_HOURS:
        return {
            "symbol": symbol,
            "status": "TOO_OLD",
            "first_seen": first_dt,
            "age_hours": age_hours,
            "bars": len(rows),
        }

    token = token_from_symbol(
        symbol
    )

    return {
        "token": token,
        "symbol": symbol,
        "status": "USABLE",
        "first_traded_ms": first["t"],
        "first_traded_utc": fmt_time(
            first["t"]
        ),
        "listing_date": first_dt.strftime(
            "%Y-%m-%d"
        ),
        "age_hours": age_hours,
        "bars": len(rows),
        "first_price": first["o"],
    }


def main():
    print(
        "TOOBIT UNSEEN CANDIDATE FINDER"
    )

    print(
        "Goal: find genuinely new crypto "
        "perpetuals with usable 15m history."
    )

    print(
        f"Lookback: {LOOKBACK_DAYS} days"
    )

    print(
        f"Minimum age: {MIN_AGE_HOURS} hours"
    )

    print(
        "Previously used tuning/test symbols "
        "are excluded."
    )

    print()

    now = datetime.now(
        timezone.utc
    )

    contracts = get_contracts()

    print(
        "Contracts discovered:",
        len(contracts),
    )

    eligible = [
        item
        for item in contracts
        if eligible_contract(item)
    ]

    print(
        "New crypto USDT contracts "
        "after filters:",
        len(eligible),
    )

    print()

    usable = []
    rejected = []

    for number, item in enumerate(
        eligible,
        start=1,
    ):
        symbol = str(
            item.get("symbol", "")
        ).upper()

        categories = normalize_categories(
            item
        )

        print(
            f"[{number}/{len(eligible)}] "
            f"Checking {symbol} ..."
        )

        result = detect_candidate(
            symbol,
            now,
        )

        result["categories"] = categories

        status = result[
            "status"
        ]

        if status == "USABLE":
            usable.append(result)

            print(
                "  ✅ USABLE |",
                result[
                    "first_traded_utc"
                ],
                "| age",
                f"{result['age_hours']:.1f}h",
                "| bars",
                result["bars"],
            )

        elif status == "TOO_NEW":
            rejected.append(result)

            print(
                "  🟡 TOO NEW | age",
                f"{result['age_hours']:.1f}h",
            )

        elif status == "OLDER_THAN_LOOKBACK":
            rejected.append(result)

            print(
                "  ⚪ OLDER THAN LOOKBACK"
            )

        elif status == "NO_DATA":
            rejected.append(result)

            print(
                "  ❌ NO DATA"
            )

        else:
            rejected.append(result)

            print(
                "  ❌",
                status,
            )

        time.sleep(0.08)

    # قدیمی‌ترها اول؛ چون Future window کامل‌تری دارند.
    usable.sort(
        key=lambda x: x[
            "age_hours"
        ],
        reverse=True,
    )

    selected = usable[
        :MAX_OUTPUT
    ]

    output = {
        "generated_at_utc": now.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "minimum_age_hours": MIN_AGE_HOURS,
        "excluded_tokens": sorted(
            EXCLUDED_TOKENS
        ),
        "usable_count": len(
            usable
        ),
        "selected_count": len(
            selected
        ),
        "candidates": selected,
    }

    with open(
        "unseen_candidates.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("#" * 88)
    print("UNSEEN CANDIDATES")
    print("#" * 88)

    if not selected:
        print(
            "NO USABLE UNSEEN CANDIDATES FOUND"
        )

    else:
        for i, item in enumerate(
            selected,
            start=1,
        ):
            print(
                f"{i}. "
                f"{item['symbol']}"
                f" | first "
                f"{item['first_traded_utc']}"
                f" | age "
                f"{item['age_hours']:.1f}h"
                f" | 15m bars "
                f"{item['bars']}"
            )

    print()
    print("#" * 88)
    print("READY-TO-PASTE TESTS BLOCK")
    print("#" * 88)

    print("TESTS = {")

    for item in selected:
        print(
            f'    "{item["token"]}": {{'
        )

        print(
            f'        "symbol": '
            f'"{item["symbol"]}",'
        )

        print(
            f'        "listing_date": '
            f'"{item["listing_date"]}",'
        )

        print(
            "    },"
        )

    print("}")

    print()
    print("#" * 88)
    print("SUMMARY")
    print("#" * 88)

    print(
        "Eligible New contracts scanned:",
        len(eligible),
    )

    print(
        "Usable unseen candidates:",
        len(usable),
    )

    print(
        "Selected for next validation:",
        len(selected),
    )

    print(
        "Output file: unseen_candidates.json"
    )

    if len(selected) < 5:
        print(
            "STATUS: INSUFFICIENT CANDIDATES"
        )
        print(
            "Need at least 5 usable symbols "
            "for a meaningful validation batch."
        )

    else:
        print(
            "STATUS: READY FOR V1.2 "
            "UNSEEN VALIDATION"
        )


if __name__ == "__main__":
    main()
