import json
import time
from datetime import datetime, timedelta, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

CHUNK_DAYS = 7
MAX_HISTORY_DAYS = 60

MIN_AGE_HOURS = 76
MAX_CANDIDATE_AGE_DAYS = 45

MAX_OUTPUT = 20


# این ارزها قبلاً در طراحی، تنظیم یا Validation استفاده شده‌اند
# و دیگر Unseen محسوب نمی‌شوند.
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
        "ai-trade-scanner-unseen-candidate-finder-v2"
})


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def from_ms(value):
    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc,
    )


def fmt_time(value):
    return from_ms(value).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def request_json(
    url,
    params=None,
    retries=4,
):
    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):
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
                    1.2 * attempt
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


def token_from_symbol(symbol):
    suffix = "-SWAP-USDT"

    if symbol.endswith(
        suffix
    ):
        return symbol[
            :-len(suffix)
        ]

    return symbol


def eligible_contract(item):
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

    # دسته New فقط برای محدود کردن تعداد قراردادهاست.
    # دیگر فرض نمی‌کنیم New یعنی حتماً زیر 10 روز.
    if "NEW" not in categories:
        return False

    # TradFi / Stock / RWA حذف شود.
    if "TRADFI" in categories:
        return False

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

    # انتهای پنجره را exclusive نگه می‌داریم.
    end_ms = to_ms(
        end_dt
    )

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

    # اگر API داده خارج از محدوده برگرداند،
    # آن را وارد تحلیل نکن.
    rows = [
        row
        for row in rows
        if (
            start_ms
            <= row["t"]
            < end_ms
        )
    ]

    return rows


def real_trade_rows(rows):
    return [
        row
        for row in rows
        if row["v"] > 0
    ]


def verify_first_trade(
    symbol,
    candidate_row,
):
    candidate_dt = from_ms(
        candidate_row["t"]
    )

    start_dt = (
        candidate_dt
        - timedelta(hours=12)
    )

    end_dt = (
        candidate_dt
        + timedelta(hours=1)
    )

    try:
        rows = fetch_window(
            symbol,
            start_dt,
            end_dt,
        )

    except Exception:
        return candidate_row

    active = real_trade_rows(
        rows
    )

    if not active:
        return candidate_row

    return min(
        active,
        key=lambda x: x["t"],
    )


def discover_first_trade(
    symbol,
    now,
):
    collected = {}

    found_any_data = False

    boundary_confirmed = False

    windows_checked = 0

    oldest_limit = (
        now
        - timedelta(
            days=MAX_HISTORY_DAYS
        )
    )

    cursor_end = now

    while cursor_end > oldest_limit:
        cursor_start = max(
            oldest_limit,
            cursor_end
            - timedelta(
                days=CHUNK_DAYS
            ),
        )

        windows_checked += 1

        try:
            rows = fetch_window(
                symbol,
                cursor_start,
                cursor_end,
            )

        except Exception as exc:
            return {
                "status":
                    "REQUEST_ERROR",
                "symbol":
                    symbol,
                "error":
                    repr(exc),
                "windows_checked":
                    windows_checked,
            }

        active = real_trade_rows(
            rows
        )

        if active:
            found_any_data = True

            for row in active:
                collected[
                    row["t"]
                ] = row

            earliest_here = min(
                active,
                key=lambda x: x["t"],
            )

            print(
                "    data:",
                cursor_start.strftime(
                    "%Y-%m-%d"
                ),
                "→",
                cursor_end.strftime(
                    "%Y-%m-%d"
                ),
                "| earliest",
                fmt_time(
                    earliest_here["t"]
                ),
                "| bars",
                len(active),
            )

        else:
            print(
                "    empty:",
                cursor_start.strftime(
                    "%Y-%m-%d"
                ),
                "→",
                cursor_end.strftime(
                    "%Y-%m-%d"
                ),
            )

            # چون از امروز به عقب می‌رویم،
            # اولین پنجره خالی قبل از پنجره‌های دارای دیتا
            # مرز شروع قرارداد را تأیید می‌کند.
            if found_any_data:
                boundary_confirmed = True
                break

        cursor_end = cursor_start

        time.sleep(0.08)

    if not found_any_data:
        return {
            "status":
                "NO_DATA",
            "symbol":
                symbol,
            "windows_checked":
                windows_checked,
        }

    earliest = min(
        collected.values(),
        key=lambda x: x["t"],
    )

    if not boundary_confirmed:
        return {
            "status":
                "OLDER_THAN_HISTORY",
            "symbol":
                symbol,
            "earliest_seen":
                earliest["t"],
            "windows_checked":
                windows_checked,
        }

    earliest = verify_first_trade(
        symbol,
        earliest,
    )

    first_dt = from_ms(
        earliest["t"]
    )

    age_hours = (
        now - first_dt
    ).total_seconds() / 3600

    if age_hours < MIN_AGE_HOURS:
        return {
            "status":
                "TOO_NEW",
            "symbol":
                symbol,
            "first_row":
                earliest,
            "age_hours":
                age_hours,
            "windows_checked":
                windows_checked,
        }

    if (
        age_hours
        > MAX_CANDIDATE_AGE_DAYS
        * 24
    ):
        return {
            "status":
                "TOO_OLD_FOR_BATCH",
            "symbol":
                symbol,
            "first_row":
                earliest,
            "age_hours":
                age_hours,
            "windows_checked":
                windows_checked,
        }

    return {
        "status":
            "USABLE",
        "symbol":
            symbol,
        "first_row":
            earliest,
        "age_hours":
            age_hours,
        "windows_checked":
            windows_checked,
    }


def main():
    print(
        "TOOBIT UNSEEN "
        "CANDIDATE FINDER V2"
    )

    print(
        "Search method: "
        "7-day windows backwards."
    )

    print(
        "Maximum history scan:",
        MAX_HISTORY_DAYS,
        "days",
    )

    print(
        "Minimum listing age:",
        MIN_AGE_HOURS,
        "hours",
    )

    print(
        "Maximum candidate age:",
        MAX_CANDIDATE_AGE_DAYS,
        "days",
    )

    print(
        "Previously used symbols "
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
        if eligible_contract(
            item
        )
    ]

    print(
        "Eligible New crypto "
        "contracts:",
        len(eligible),
    )

    print()

    usable = []

    counts = {
        "USABLE": 0,
        "TOO_NEW": 0,
        "TOO_OLD_FOR_BATCH": 0,
        "OLDER_THAN_HISTORY": 0,
        "NO_DATA": 0,
        "REQUEST_ERROR": 0,
    }

    for number, item in enumerate(
        eligible,
        start=1,
    ):
        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        print(
            "=" * 88
        )

        print(
            f"[{number}/{len(eligible)}] "
            f"{symbol}"
        )

        result = (
            discover_first_trade(
                symbol,
                now,
            )
        )

        status = result[
            "status"
        ]

        if status not in counts:
            counts[
                status
            ] = 0

        counts[
            status
        ] += 1

        if status == "USABLE":
            first = result[
                "first_row"
            ]

            token = (
                token_from_symbol(
                    symbol
                )
            )

            first_dt = from_ms(
                first["t"]
            )

            candidate = {
                "token":
                    token,
                "symbol":
                    symbol,
                "listing_date":
                    first_dt.strftime(
                        "%Y-%m-%d"
                    ),
                "first_traded_utc":
                    fmt_time(
                        first["t"]
                    ),
                "first_price":
                    first["o"],
                "age_hours":
                    result[
                        "age_hours"
                    ],
                "windows_checked":
                    result[
                        "windows_checked"
                    ],
            }

            usable.append(
                candidate
            )

            print(
                "  ✅ USABLE"
            )

            print(
                "  First trade:",
                candidate[
                    "first_traded_utc"
                ],
            )

            print(
                "  Age:",
                f"{candidate['age_hours']:.1f}h",
            )

        elif status == "TOO_NEW":
            print(
                "  🟡 TOO NEW"
            )

            print(
                "  First trade:",
                fmt_time(
                    result[
                        "first_row"
                    ]["t"]
                ),
            )

            print(
                "  Age:",
                f"{result['age_hours']:.1f}h",
            )

        elif (
            status
            == "TOO_OLD_FOR_BATCH"
        ):
            print(
                "  ⚪ TOO OLD FOR "
                "CURRENT BATCH"
            )

            print(
                "  First trade:",
                fmt_time(
                    result[
                        "first_row"
                    ]["t"]
                ),
            )

            print(
                "  Age:",
                f"{result['age_hours']:.1f}h",
            )

        elif (
            status
            == "OLDER_THAN_HISTORY"
        ):
            print(
                "  ⚪ START NOT FOUND "
                "WITHIN HISTORY WINDOW"
            )

            print(
                "  Earliest visible:",
                fmt_time(
                    result[
                        "earliest_seen"
                    ]
                ),
            )

        elif status == "NO_DATA":
            print(
                "  ❌ NO DATA"
            )

        else:
            print(
                "  ❌ REQUEST ERROR"
            )

            print(
                "  ",
                result.get(
                    "error",
                    "",
                ),
            )

        print()

        time.sleep(0.10)

    # قدیمی‌ترهای قابل‌قبول اول،
    # چون پنجره 72H کامل‌تری دارند.
    usable.sort(
        key=lambda x:
            x["age_hours"],
        reverse=True,
    )

    selected = usable[
        :MAX_OUTPUT
    ]

    output = {
        "generated_at_utc":
            now.isoformat(),
        "finder_version":
            "V2",
        "chunk_days":
            CHUNK_DAYS,
        "max_history_days":
            MAX_HISTORY_DAYS,
        "minimum_age_hours":
            MIN_AGE_HOURS,
        "maximum_candidate_age_days":
            MAX_CANDIDATE_AGE_DAYS,
        "excluded_tokens":
            sorted(
                EXCLUDED_TOKENS
            ),
        "usable_count":
            len(usable),
        "selected_count":
            len(selected),
        "candidates":
            selected,
        "status_counts":
            counts,
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
    print(
        "#" * 88
    )

    print(
        "UNSEEN CANDIDATES V2"
    )

    print(
        "#" * 88
    )

    if not selected:
        print(
            "NO USABLE UNSEEN "
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
                f"{item['first_traded_utc']}"
                f" | age "
                f"{item['age_hours']:.1f}h"
            )

    print()
    print(
        "#" * 88
    )

    print(
        "READY-TO-PASTE TESTS BLOCK"
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
        "SUMMARY V2"
    )

    print(
        "#" * 88
    )

    print(
        "Eligible contracts scanned:",
        len(eligible),
    )

    print(
        "Usable unseen candidates:",
        len(usable),
    )

    print(
        "Selected for validation:",
        len(selected),
    )

    print(
        "Too new:",
        counts[
            "TOO_NEW"
        ],
    )

    print(
        "Too old for batch:",
        counts[
            "TOO_OLD_FOR_BATCH"
        ],
    )

    print(
        "Start older than "
        "history window:",
        counts[
            "OLDER_THAN_HISTORY"
        ],
    )

    print(
        "No data:",
        counts[
            "NO_DATA"
        ],
    )

    print(
        "Request errors:",
        counts[
            "REQUEST_ERROR"
        ],
    )

    print(
        "Output file: "
        "unseen_candidates.json"
    )

    if len(selected) >= 5:
        print(
            "STATUS: READY FOR "
            "V1.2 UNSEEN VALIDATION"
        )

    else:
        print(
            "STATUS: INSUFFICIENT "
            "USABLE CANDIDATES"
        )

        print(
            "Do not judge V1.2 yet."
        )


if __name__ == "__main__":
    main()
