import json
import time
from datetime import datetime, timedelta, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

REFERENCE_SYMBOLS = [
    "BTC-SWAP-USDT",
    "ETH-SWAP-USDT",
]

REFERENCE_SCAN_DAYS = 60
REFERENCE_CHUNK_DAYS = 7

BASELINE_PROBE_HOURS = 24
SEARCH_CHUNK_DAYS = 7

MIN_AGE_HOURS = 76
MAX_CANDIDATE_AGE_DAYS = 30

MAX_OUTPUT = 20
MAX_REQUESTS = 900


# ارزهایی که قبلاً در Tune / Replay / Validation
# استفاده شده‌اند و دیگر Unseen نیستند.
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
    "User-Agent":
        "ai-trade-scanner-unseen-candidate-finder-v3"
})


REQUEST_COUNT = 0


def to_ms(dt):
    return int(
        dt.timestamp() * 1000
    )


def from_ms(value):
    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc,
    )


def fmt_dt(dt):
    return dt.strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def fmt_ms(value):
    return fmt_dt(
        from_ms(value)
    )


def token_from_symbol(symbol):
    suffix = "-SWAP-USDT"

    if symbol.endswith(suffix):
        return symbol[
            :-len(suffix)
        ]

    return symbol


def request_json(
    url,
    params=None,
    retries=4,
):
    global REQUEST_COUNT

    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):
        if (
            REQUEST_COUNT
            >= MAX_REQUESTS
        ):
            raise RuntimeError(
                "Request budget reached: "
                f"{MAX_REQUESTS}"
            )

        REQUEST_COUNT += 1

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
                f"REQUEST ERROR "
                f"{attempt}/{retries}: "
                f"{repr(exc)}"
            )

            if attempt < retries:
                time.sleep(
                    1.0 * attempt
                )

    raise RuntimeError(
        f"Request failed after "
        f"{retries} attempts: "
        f"{last_error!r}"
    )


def get_contracts():
    payload = request_json(
        f"{BASE}/api/v1/exchangeInfo"
    )

    if not isinstance(
        payload,
        dict,
    ):
        return []

    contracts = payload.get(
        "contracts"
    )

    if isinstance(
        contracts,
        list,
    ):
        return contracts

    data = payload.get(
        "data"
    )

    if isinstance(
        data,
        dict,
    ):
        contracts = data.get(
            "contracts"
        )

        if isinstance(
            contracts,
            list,
        ):
            return contracts

    return []


def normalize_categories(item):
    raw = item.get(
        "categories",
        [],
    )

    if not isinstance(
        raw,
        list,
    ):
        return []

    return [
        str(x).strip()
        for x in raw
        if str(x).strip()
    ]


def is_crypto_usdt_contract(item):
    if not isinstance(
        item,
        dict,
    ):
        return False

    symbol = str(
        item.get(
            "symbol",
            "",
        )
    ).upper()

    status = str(
        item.get(
            "status",
            "",
        )
    ).upper()

    quote = str(
        item.get(
            "quoteAsset",
            "",
        )
    ).upper()

    categories = [
        x.upper()
        for x in
        normalize_categories(item)
    ]

    if not symbol.endswith(
        "-SWAP-USDT"
    ):
        return False

    if status != "TRADING":
        return False

    if (
        quote
        and quote != "USDT"
    ):
        return False

    if item.get(
        "inverse"
    ) is True:
        return False

    # Stock / RWA / TradFi حذف شود.
    if item.get(
        "isRwa"
    ) is True:
        return False

    rwa_type = str(
        item.get(
            "rwaType",
            "",
        )
    ).strip()

    if rwa_type:
        return False

    blocked_words = (
        "TRADFI",
        "STOCK",
        "FOREX",
        "COMMODITY",
        "RWA",
    )

    joined_categories = " ".join(
        categories
    )

    if any(
        word in joined_categories
        for word in blocked_words
    ):
        return False

    token = token_from_symbol(
        symbol
    )

    if token in EXCLUDED_TOKENS:
        return False

    return True


def extract_rows(payload):
    if isinstance(
        payload,
        list,
    ):
        raw = payload

    elif isinstance(
        payload,
        dict,
    ):
        raw = payload.get(
            "data",
            [],
        )

        if isinstance(
            raw,
            dict,
        ):
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
        if not isinstance(
            item,
            list,
        ):
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

        except (
            TypeError,
            ValueError,
        ):
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


def fetch_window(
    symbol,
    start_dt,
    end_dt,
):
    start_ms = to_ms(
        start_dt
    )

    end_ms = to_ms(
        end_dt
    )

    if end_ms <= start_ms:
        return []

    payload = request_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": start_ms,
            "endTime": end_ms - 1,
            "limit": 1000,
        },
    )

    rows = extract_rows(
        payload
    )

    # اگر API داده خارج از بازه داد،
    # اجازه نمی‌دهیم وارد تحلیل شود.
    return [
        row
        for row in rows
        if (
            start_ms
            <= row["t"]
            < end_ms
        )
    ]


def find_reference_floor(
    symbol,
    now,
):
    oldest_limit = (
        now
        - timedelta(
            days=REFERENCE_SCAN_DAYS
        )
    )

    cursor_end = now

    found_any = False
    earliest = None
    windows_checked = 0

    while (
        cursor_end
        > oldest_limit
    ):
        cursor_start = max(
            oldest_limit,
            cursor_end
            - timedelta(
                days=REFERENCE_CHUNK_DAYS
            ),
        )

        rows = fetch_window(
            symbol,
            cursor_start,
            cursor_end,
        )

        windows_checked += 1

        if rows:
            found_any = True

            here = rows[0]

            if (
                earliest is None
                or here["t"]
                < earliest["t"]
            ):
                earliest = here

            print(
                f"  {symbol} data "
                f"{cursor_start:%Y-%m-%d}"
                f" -> "
                f"{cursor_end:%Y-%m-%d}"
                f" | earliest "
                f"{fmt_ms(here['t'])}"
                f" | bars "
                f"{len(rows)}"
            )

        else:
            print(
                f"  {symbol} empty "
                f"{cursor_start:%Y-%m-%d}"
                f" -> "
                f"{cursor_end:%Y-%m-%d}"
            )

            # چون از امروز به عقب می‌رویم،
            # بعد از دیدن دیتا، اولین بازه خالی
            # مرز تاریخچه API را مشخص می‌کند.
            if found_any:
                break

        cursor_end = cursor_start

        time.sleep(0.03)

    if earliest is None:
        raise RuntimeError(
            "No reference Kline history "
            f"found for {symbol}"
        )

    return {
        "symbol":
            symbol,
        "floor_ms":
            earliest["t"],
        "floor_dt":
            from_ms(
                earliest["t"]
            ),
        "windows_checked":
            windows_checked,
    }


def find_common_reference_floor(
    now,
):
    refs = []

    print(
        "REFERENCE HISTORY CHECK"
    )

    print(
        "-" * 88
    )

    for symbol in (
        REFERENCE_SYMBOLS
    ):
        result = (
            find_reference_floor(
                symbol,
                now,
            )
        )

        refs.append(
            result
        )

        print(
            f"  -> {symbol} floor: "
            f"{fmt_dt(result['floor_dt'])}"
        )

        print()

    # محافظه‌کارانه:
    # اگر BTC و ETH کمی فرق داشتند،
    # دیرترین مرز را انتخاب می‌کنیم.
    common_floor = max(
        x["floor_dt"]
        for x in refs
    )

    spread_hours = (
        max(
            x["floor_dt"]
            for x in refs
        )
        -
        min(
            x["floor_dt"]
            for x in refs
        )
    ).total_seconds() / 3600

    return (
        refs,
        common_floor,
        spread_hours,
    )


def find_first_kline_after_floor(
    symbol,
    floor_dt,
    now,
):
    # اول فقط 24 ساعت اول بعد از
    # مرز مشترک BTC/ETH را نگاه می‌کنیم.
    baseline_end = min(
        floor_dt
        + timedelta(
            hours=BASELINE_PROBE_HOURS
        ),
        now,
    )

    baseline_rows = (
        fetch_window(
            symbol,
            floor_dt,
            baseline_end,
        )
    )

    # اگر در همان ابتدای مرز تاریخچه
    # دیتا دارد، این ارز جدید محسوب نمی‌شود.
    if baseline_rows:
        return {
            "status":
                "PREEXISTING_AT_FLOOR",
            "first_row":
                baseline_rows[0],
        }

    cursor = baseline_end

    # اگر در 24 ساعت اول دیتا نداشت،
    # به جلو حرکت می‌کنیم تا اولین
    # Kline واقعی API را پیدا کنیم.
    while cursor < now:
        chunk_end = min(
            cursor
            + timedelta(
                days=SEARCH_CHUNK_DAYS
            ),
            now,
        )

        rows = fetch_window(
            symbol,
            cursor,
            chunk_end,
        )

        if rows:
            first = rows[0]

            first_dt = from_ms(
                first["t"]
            )

            # یک بررسی دوباره در 24 ساعت
            # قبل از اولین کندل پیدا شده.
            verify_start = max(
                floor_dt,
                first_dt
                - timedelta(
                    hours=24
                ),
            )

            if (
                verify_start
                < first_dt
            ):
                verify_rows = (
                    fetch_window(
                        symbol,
                        verify_start,
                        first_dt,
                    )
                )

                if verify_rows:
                    first = (
                        verify_rows[0]
                    )

            return {
                "status":
                    "API_NEW_CANDIDATE",
                "first_row":
                    first,
            }

        cursor = chunk_end

        time.sleep(0.03)

    return {
        "status":
            "NO_DATA_AFTER_FLOOR",
    }


def main():
    print(
        "TOOBIT UNSEEN "
        "CANDIDATE FINDER V3"
    )

    print(
        "Method: compare each active "
        "crypto contract against the "
        "common BTC/ETH 15m history floor."
    )

    print(
        "A symbol is NOT considered new "
        "if it already has Klines in the "
        "first 24h of that floor."
    )

    print(
        "Previously used tuning/test "
        "symbols are excluded."
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

    print()

    refs, common_floor, spread_hours = (
        find_common_reference_floor(
            now
        )
    )

    print(
        "=" * 88
    )

    print(
        "COMMON REFERENCE FLOOR:",
        fmt_dt(
            common_floor
        ),
    )

    print(
        "Reference floor spread:",
        f"{spread_hours:.2f}h",
    )

    print(
        "=" * 88
    )

    print()

    if spread_hours > 6:
        print(
            "WARNING: BTC/ETH history "
            "floors differ by more "
            "than 6 hours."
        )

        print(
            "Results will be treated "
            "as diagnostic only."
        )

        print()

    eligible = [
        item
        for item in contracts
        if is_crypto_usdt_contract(
            item
        )
    ]

    # دسته New اول اسکن می‌شود،
    # ولی دیگر محدود به New نیستیم.
    eligible.sort(
        key=lambda item: (
            "NEW"
            not in [
                x.upper()
                for x in
                normalize_categories(
                    item
                )
            ],
            str(
                item.get(
                    "symbol",
                    "",
                )
            ),
        )
    )

    print(
        "Active crypto USDT "
        "contracts to scan:",
        len(eligible),
    )

    print(
        "Request budget:",
        MAX_REQUESTS,
    )

    print()

    candidates = []

    counts = {
        "PREEXISTING_AT_FLOOR":
            0,
        "API_NEW_CANDIDATE":
            0,
        "TOO_NEW":
            0,
        "TOO_OLD_FOR_BATCH":
            0,
        "NO_DATA_AFTER_FLOOR":
            0,
        "REQUEST_ERROR":
            0,
    }

    for number, item in enumerate(
        eligible,
        start=1,
    ):
        if (
            REQUEST_COUNT
            >= MAX_REQUESTS - 5
        ):
            print(
                "REQUEST BUDGET "
                "NEAR LIMIT - "
                "STOPPING SCAN"
            )

            break

        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        token = (
            token_from_symbol(
                symbol
            )
        )

        categories = (
            normalize_categories(
                item
            )
        )

        print(
            f"[{number}/"
            f"{len(eligible)}] "
            f"{symbol}"
        )

        try:
            result = (
                find_first_kline_after_floor(
                    symbol,
                    common_floor,
                    now,
                )
            )

        except Exception as exc:
            counts[
                "REQUEST_ERROR"
            ] += 1

            print(
                "  ❌ REQUEST ERROR:",
                repr(exc),
            )

            print()

            continue

        status = result[
            "status"
        ]

        if (
            status
            == "PREEXISTING_AT_FLOOR"
        ):
            counts[
                "PREEXISTING_AT_FLOOR"
            ] += 1

            print(
                "  ⚪ PREEXISTING AT "
                "API HISTORY FLOOR"
            )

            print()

            continue

        if (
            status
            == "NO_DATA_AFTER_FLOOR"
        ):
            counts[
                "NO_DATA_AFTER_FLOOR"
            ] += 1

            print(
                "  ❌ NO DATA AFTER "
                "REFERENCE FLOOR"
            )

            print()

            continue

        first = result[
            "first_row"
        ]

        first_dt = from_ms(
            first["t"]
        )

        age_hours = (
            now - first_dt
        ).total_seconds() / 3600

        # برای ارزیابی 72 ساعته
        # هنوز بیش از حد جدید است.
        if (
            age_hours
            < MIN_AGE_HOURS
        ):
            counts[
                "TOO_NEW"
            ] += 1

            print(
                "  🟡 TOO NEW FOR "
                "72H VALIDATION"
            )

            print(
                "  API first Kline:",
                fmt_dt(
                    first_dt
                ),
            )

            print(
                "  Age:",
                f"{age_hours:.1f}h",
            )

            print()

            continue

        # فقط لیستینگ‌های نسبتاً جدید
        # وارد Batch فعلی شوند.
        if (
            age_hours
            > MAX_CANDIDATE_AGE_DAYS
            * 24
        ):
            counts[
                "TOO_OLD_FOR_BATCH"
            ] += 1

            print(
                "  ⚪ API START TOO OLD "
                "FOR CURRENT BATCH"
            )

            print(
                "  API first Kline:",
                fmt_dt(
                    first_dt
                ),
            )

            print(
                "  Age:",
                f"{age_hours:.1f}h",
            )

            print()

            continue

        counts[
            "API_NEW_CANDIDATE"
        ] += 1

        candidate = {
            "token":
                token,
            "symbol":
                symbol,
            "api_first_kline_utc":
                fmt_dt(
                    first_dt
                ),
            "listing_date":
                first_dt.strftime(
                    "%Y-%m-%d"
                ),
            "age_hours":
                age_hours,
            "first_price":
                first["o"],
            "categories":
                categories,
        }

        candidates.append(
            candidate
        )

        print(
            "  ✅ API NEW CANDIDATE"
        )

        print(
            "  First Kline:",
            candidate[
                "api_first_kline_utc"
            ],
        )

        print(
            "  Age:",
            f"{age_hours:.1f}h",
        )

        print(
            "  Categories:",
            categories,
        )

        print()

        if (
            len(candidates)
            >= MAX_OUTPUT
        ):
            print(
                f"Reached MAX_OUTPUT="
                f"{MAX_OUTPUT}; "
                "stopping candidate "
                "collection."
            )

            break

        time.sleep(0.03)

    # قدیمی‌ترهای واجد شرایط اول،
    # چون Future 72H کامل‌تری دارند.
    candidates.sort(
        key=lambda x:
            x["age_hours"],
        reverse=True,
    )

    selected = candidates[
        :MAX_OUTPUT
    ]

    output = {
        "generated_at_utc":
            now.isoformat(),
        "finder_version":
            "V3",
        "reference_symbols":
            [
                {
                    "symbol":
                        x["symbol"],
                    "floor_utc":
                        fmt_dt(
                            x["floor_dt"]
                        ),
                }
                for x in refs
            ],
        "common_reference_floor_utc":
            fmt_dt(
                common_floor
            ),
        "reference_floor_spread_hours":
            spread_hours,
        "baseline_probe_hours":
            BASELINE_PROBE_HOURS,
        "minimum_age_hours":
            MIN_AGE_HOURS,
        "maximum_candidate_age_days":
            MAX_CANDIDATE_AGE_DAYS,
        "excluded_tokens":
            sorted(
                EXCLUDED_TOKENS
            ),
        "request_count":
            REQUEST_COUNT,
        "selected_count":
            len(selected),
        "candidates":
            selected,
        "status_counts":
            counts,
    }

    with open(
        "unseen_candidates_v3.json",
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

    print(
        "#" * 88
    )

    print(
        "UNSEEN CANDIDATES V3"
    )

    print(
        "#" * 88
    )

    if not selected:
        print(
            "NO API-NEW USABLE "
            "CANDIDATES FOUND"
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
                f"{item['api_first_kline_utc']}"
                f" | age "
                f"{item['age_hours']:.1f}h"
                f" | categories "
                f"{item['categories']}"
            )

    print()

    print(
        "#" * 88
    )

    print(
        "READY-TO-PASTE "
        "TESTS BLOCK"
    )

    print(
        "#" * 88
    )

    print(
        "TESTS = {"
    )

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

    print(
        "}"
    )

    print()

    print(
        "#" * 88
    )

    print(
        "SUMMARY V3"
    )

    print(
        "#" * 88
    )

    print(
        "Common BTC/ETH history floor:",
        fmt_dt(
            common_floor
        ),
    )

    print(
        "Active crypto contracts "
        "considered:",
        len(eligible),
    )

    print(
        "Preexisting at history floor:",
        counts[
            "PREEXISTING_AT_FLOOR"
        ],
    )

    print(
        "API-new candidates:",
        counts[
            "API_NEW_CANDIDATE"
        ],
    )

    print(
        "Too new for 72H validation:",
        counts[
            "TOO_NEW"
        ],
    )

    print(
        "Too old for current batch:",
        counts[
            "TOO_OLD_FOR_BATCH"
        ],
    )

    print(
        "No data after floor:",
        counts[
            "NO_DATA_AFTER_FLOOR"
        ],
    )

    print(
        "Request errors:",
        counts[
            "REQUEST_ERROR"
        ],
    )

    print(
        "Requests used:",
        REQUEST_COUNT,
        "/",
        MAX_REQUESTS,
    )

    print(
        "Selected for next step:",
        len(selected),
    )

    print(
        "Output file: "
        "unseen_candidates_v3.json"
    )

    if len(selected) >= 5:
        print(
            "STATUS: CANDIDATE "
            "SHORTLIST READY"
        )

        print(
            "NEXT: verify official "
            "Toobit listing dates "
            "before V1.2 validation."
        )

    else:
        print(
            "STATUS: INSUFFICIENT "
            "API CANDIDATES"
        )

        print(
            "Do not judge V1.2 yet."
        )


if __name__ == "__main__":
    main()
