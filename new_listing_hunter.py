import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.toobit.com"
STATE_FILE = Path("new_listing_state.json")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20


def utc_now():
    return datetime.now(timezone.utc)


def load_state():
    default = {
        "initialized": False,
        "items": {}
    }

    if not STATE_FILE.exists():
        return default

    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return default

        initialized = bool(
            data.get(
                "initialized",
                data.get("init", False)
            )
        )

        items = data.get(
            "items",
            {}
        )

        if not isinstance(items, dict):
            items = {}

        return {
            "initialized": initialized,
            "items": items
        }

    except Exception as exc:
        print(
            "STATE_LOAD_ERROR:",
            repr(exc)
        )
        return default


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def detect_chat_id():
    if CHAT_ID:
        return CHAT_ID

    if not TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN_MISSING"
        )
        return ""

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={
                "limit": 100,
                "timeout": 0
            },
            timeout=TIMEOUT
        )

        data = response.json()

        if not data.get("ok"):
            print(
                "TELEGRAM_GETUPDATES_ERROR:",
                data
            )
            return ""

        for update in reversed(
            data.get("result", [])
        ):
            message = (
                update.get("message")
                or update.get(
                    "edited_message"
                )
                or update.get(
                    "channel_post"
                )
            )

            if not message:
                continue

            cid = (
                message
                .get("chat", {})
                .get("id")
            )

            if cid is not None:
                return str(cid)

    except Exception as exc:
        print(
            "TELEGRAM_CHAT_ID_ERROR:",
            repr(exc)
        )

    return ""


def send_telegram(text):
    if not TOKEN:
        print(
            "TELEGRAM_NOT_READY: "
            "token missing"
        )
        return False

    cid = detect_chat_id()

    if not cid:
        print(
            "TELEGRAM_NOT_READY: "
            "chat id missing"
        )
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": cid,
                "text": text
            },
            timeout=TIMEOUT
        )

        data = response.json()

        if not data.get("ok"):
            print(
                "TELEGRAM_SEND_ERROR:",
                data
            )
            return False

        print("TELEGRAM_SENT")
        return True

    except Exception as exc:
        print(
            "TELEGRAM_SEND_EXCEPTION:",
            repr(exc)
        )
        return False


def fetch_contracts():
    response = requests.get(
        f"{BASE}/api/v1/exchangeInfo",
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    result = {}

    for item in data.get(
        "contracts",
        []
    ):
        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        quote_asset = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        status = str(
            item.get(
                "status",
                "UNKNOWN"
            )
        ).upper()

        inverse = bool(
            item.get(
                "inverse",
                False
            )
        )

        categories_raw = (
            item.get("categories")
            or []
        )

        categories = {
            str(x).lower()
            for x in categories_raw
        }

        if quote_asset != "USDT":
            continue

        if not symbol.endswith(
            "-SWAP-USDT"
        ):
            continue

        if inverse:
            continue

        if "tradfi" in categories:
            continue

        result[symbol] = status

    return result


def fetch_15m_klines(
    symbol,
    start_iso
):
    start_dt = datetime.fromisoformat(
        start_iso
    )

    start_ms = int(
        start_dt.timestamp()
        * 1000
    )

    now_ms = int(
        time.time()
        * 1000
    )

    response = requests.get(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": start_ms,
            "endTime": now_ms,
            "limit": 1000
        },
        timeout=TIMEOUT
    )

    response.raise_for_status()

    raw = response.json()

    rows = []

    for candle in raw:
        if (
            not isinstance(
                candle,
                list
            )
            or len(candle) < 7
        ):
            continue

        close_time = int(
            candle[6]
        )

        if close_time > now_ms:
            continue

        rows.append(
            {
                "t": int(
                    candle[0]
                ),
                "o": float(
                    candle[1]
                ),
                "h": float(
                    candle[2]
                ),
                "l": float(
                    candle[3]
                ),
                "c": float(
                    candle[4]
                ),
                "v": float(
                    candle[5]
                )
            }
        )

    rows.sort(
        key=lambda x: x["t"]
    )

    return rows


def analyze(
    symbol,
    trading_since,
    hour
):
    candles = fetch_15m_klines(
        symbol,
        trading_since
    )

    needed = hour * 4

    candles = candles[:needed]

    if len(candles) < needed:
        return (
            "👀 هنوز صبر",
            (
                f"ارز: "
                f"{symbol.replace('-SWAP-USDT', '/USDT')}\n"
                f"بررسی {hour} ساعته\n"
                f"کندل کافی نداریم: "
                f"{len(candles)}/{needed}"
            )
        )

    first_price = (
        candles[0]["o"]
    )

    price = (
        candles[-1]["c"]
    )

    high = max(
        x["h"]
        for x in candles
    )

    low = min(
        x["l"]
        for x in candles
    )

    recent = candles[-4:]

    prior = (
        candles[-8:-4]
        if len(candles) >= 8
        else []
    )

    gain = (
        (
            price
            / first_price
        )
        - 1
    ) * 100

    pullback = (
        (
            price
            / high
        )
        - 1
    ) * 100 if high > 0 else 0

    recent_volume = (
        sum(
            x["v"]
            for x in recent
        )
        / len(recent)
    )

    prior_volume = (
        sum(
            x["v"]
            for x in prior
        )
        / len(prior)
        if prior
        else recent_volume
    )

    volume_ratio = (
        recent_volume
        / prior_volume
        if prior_volume > 0
        else 1.0
    )

    higher_lows = sum(
        b["l"] > a["l"]
        for a, b in zip(
            recent,
            recent[1:]
        )
    )

    higher_highs = sum(
        b["h"] > a["h"]
        for a, b in zip(
            recent,
            recent[1:]
        )
    )

    sma4 = (
        sum(
            x["c"]
            for x in recent
        )
        / len(recent)
    )

    range_pos = (
        (
            price - low
        )
        / (
            high - low
        )
        if high > low
        else 0.5
    )

    score = 0

    if price > sma4:
        score += 1

    if higher_lows >= 2:
        score += 2

    if higher_highs >= 2:
        score += 1

    if volume_ratio >= 1.50:
        score += 2

    elif volume_ratio >= 1.15:
        score += 1

    if 3 <= gain <= 45:
        score += 1

    if range_pos >= 0.65:
        score += 1

    if pullback <= -15:
        score -= 3

    if gain >= 80:
        score -= 2

    if gain <= -12:
        score -= 3

    if score >= 6:
        title = "🟢 آماده لانگ"

    elif score >= 4:
        title = "🟡 ستاپ اولیه"

    elif hour >= 4:
        title = "❌ فعلاً رد شد"

    else:
        title = "👀 هنوز صبر"

    display_symbol = (
        symbol.replace(
            "-SWAP-USDT",
            "/USDT"
        )
    )

    body = (
        f"ارز: {display_symbol}\n"
        f"بررسی: {hour} ساعت بعد از شروع معامله\n"
        f"امتیاز: {score}\n"
        f"قیمت: {price}\n"
        f"رشد از شروع: {gain:+.1f}٪\n"
        f"فاصله از سقف: {pullback:+.1f}٪\n"
        f"نسبت حجم اخیر: {volume_ratio:.2f}x"
    )

    if score >= 6:
        recent_low = min(
            x["l"]
            for x in recent
        )

        sl = max(
            recent_low,
            price * 0.92
        )

        risk = price - sl

        if risk <= 0:
            sl = price * 0.94
            risk = price - sl

        tp1 = (
            price
            + 1.5 * risk
        )

        tp2 = (
            price
            + 2.5 * risk
        )

        tp3 = (
            price
            + 4.0 * risk
        )

        body += (
            f"\n\nورود تقریبی: {price}"
            f"\nحد ضرر: {sl}"
            f"\nهدف ۱: {tp1}"
            f"\nهدف ۲: {tp2}"
            f"\nهدف ۳: {tp3}"
        )

    return title, body


def main():
    state = load_state()

    try:
        current = fetch_contracts()

    except Exception as exc:
        print(
            "TOOBIT_EXCHANGEINFO_ERROR:",
            repr(exc)
        )
        return

    print(
        "CRYPTO_USDT_PERPETUALS:",
        len(current)
    )

    now = utc_now()

    if not state["initialized"]:

        for symbol, status in current.items():

            state["items"][symbol] = {
                "status": status,
                "baseline": True,
                "trading_since": None,
                "sent": []
            }

        state[
            "initialized"
        ] = True

        save_state(state)

        print(
            "BASELINE_SAVED"
        )

        return

    for symbol, status in current.items():

        record = state[
            "items"
        ].get(symbol)

        if record is None:

            record = {
                "status": status,
                "baseline": False,
                "trading_since": (
                    now.isoformat()
                    if status == "TRADING"
                    else None
                ),
                "sent": []
            }

            state[
                "items"
            ][symbol] = record

            status_fa = (
                "معامله شروع شده"
                if status == "TRADING"
                else "هنوز قابل معامله نیست"
            )

            send_telegram(
                "🚨 ارز جدید در فیوچرز توبیت\n"
                f"ارز: "
                f"{symbol.replace('-SWAP-USDT', '/USDT')}\n"
                f"وضعیت: {status_fa}\n"
                "فعلاً ورود نکن؛ "
                "ربات در حال جمع‌آوری داده است."
            )

        old_status = str(
            record.get(
                "status",
                "UNKNOWN"
            )
        ).upper()

        if old_status != status:

            record[
                "status"
            ] = status

            if status == "TRADING":

                record[
                    "trading_since"
                ] = now.isoformat()

                record[
                    "sent"
                ] = []

                send_telegram(
                    "🟢 معامله ارز جدید شروع شد\n"
                    f"ارز: "
                    f"{symbol.replace('-SWAP-USDT', '/USDT')}\n"
                    "ربات ۱، ۲ و ۴ ساعت بعد "
                    "آن را بررسی می‌کند."
                )

        if record.get(
            "baseline"
        ):
            continue

        if (
            status != "TRADING"
            or not record.get(
                "trading_since"
            )
        ):
            continue

        start_time = (
            datetime.fromisoformat(
                record[
                    "trading_since"
                ]
            )
        )

        age_hours = (
            (
                now
                - start_time
            ).total_seconds()
            / 3600
        )

        sent_hours = {
            int(x)
            for x in record.get(
                "sent",
                []
            )
            if str(x).isdigit()
        }

        for hour in (
            1,
            2,
            4
        ):

            if (
                age_hours < hour
                or hour
                in sent_hours
            ):
                continue

            try:
                title, body = analyze(
                    symbol,
                    record[
                        "trading_since"
                    ],
                    hour
                )

                send_telegram(
                    f"{title} | "
                    "شکارچی لیست جدید\n\n"
                    f"{body}\n\n"
                    "⚠️ معامله خودکار "
                    "باز نمی‌شود."
                )

                sent_hours.add(
                    hour
                )

                record[
                    "sent"
                ] = sorted(
                    sent_hours
                )

            except Exception as exc:

                print(
                    "ANALYSIS_ERROR:",
                    symbol,
                    f"{hour}h",
                    repr(exc)
                )

    save_state(state)

    print("DONE")


if __name__ == "__main__":
    main()
