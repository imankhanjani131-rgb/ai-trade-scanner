import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE = "https://api.toobit.com"
STATE = Path("new_listing_state.json")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20


def now():
    return datetime.now(timezone.utc)


def load_state():
    if not STATE.exists():
        return {
            "init": False,
            "items": {}
        }

    try:
        return json.loads(
            STATE.read_text(encoding="utf-8")
        )
    except Exception as e:
        print("State load error:", e)
        return {
            "init": False,
            "items": {}
        }


def save_state(state):
    STATE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def get_chat_id():
    # اگر Secret جدا برای Chat ID داشته باشیم
    if CHAT_ID:
        print("Using TELEGRAM_CHAT_ID secret.")
        return CHAT_ID

    # اگر توکن نباشد
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN is missing.")
        return ""

    # پیدا کردن Chat ID از آخرین پیام کاربر به ربات
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
                "Telegram getUpdates error:",
                data
            )
            return ""

        updates = data.get("result", [])

        for update in reversed(updates):
            message = (
                update.get("message")
                or update.get("channel_post")
                or update.get("edited_message")
            )

            if not message:
                continue

            chat = message.get("chat", {})
            cid = chat.get("id")

            if cid is not None:
                print(
                    "Telegram chat id detected."
                )
                return str(cid)

    except Exception as e:
        print(
            "Telegram chat id error:",
            repr(e)
        )

    print(
        "Telegram chat id not found."
    )
    return ""


def send(text):
    if not TOKEN:
        print(
            "Telegram not ready: "
            "TELEGRAM_BOT_TOKEN missing."
        )
        return False

    cid = get_chat_id()

    if not cid:
        print(
            "Telegram not ready: "
            "chat id missing."
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
                "Telegram send error:",
                data
            )
            return False

        print("Telegram sent successfully.")
        return True

    except Exception as e:
        print(
            "Telegram send exception:",
            repr(e)
        )
        return False


def contracts():
    response = requests.get(
        f"{BASE}/api/v1/exchangeInfo",
        timeout=TIMEOUT
    )

    response.raise_for_status()
    data = response.json()

    result = {}

    for item in data.get("contracts", []):

        symbol = str(
            item.get("symbol", "")
        ).upper()

        quote_asset = str(
            item.get("quoteAsset", "")
        ).upper()

        status = str(
            item.get("status", "UNKNOWN")
        ).upper()

        categories = {
            str(x).lower()
            for x in item.get(
                "categories",
                []
            )
        }

        if quote_asset != "USDT":
            continue

        if "-SWAP-USDT" not in symbol:
            continue

        if item.get("inverse") is True:
            continue

        # سهام و TradFi حذف شوند
        if "tradfi" in categories:
            continue

        result[symbol] = status

    return result


def klines(symbol, start_iso):
    start_ms = int(
        datetime.fromisoformat(
            start_iso
        ).timestamp() * 1000
    )

    response = requests.get(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": start_ms,
            "limit": 100
        },
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    current_ms = int(
        time.time() * 1000
    )

    rows = []

    for candle in data:

        if len(candle) < 7:
            continue

        close_time = int(
            candle[6]
        )

        # فقط کندل بسته‌شده
        if close_time > current_ms:
            continue

        rows.append(
            {
                "o": float(candle[1]),
                "h": float(candle[2]),
                "l": float(candle[3]),
                "c": float(candle[4]),
                "v": float(candle[5])
            }
        )

    return rows


def analyze(symbol, start_iso, hour):
    candles = klines(
        symbol,
        start_iso
    )

    if len(candles) < 4:
        return (
            "👀 هنوز صبر",
            (
                f"{symbol}\n"
                f"بررسی {hour} ساعت بعد\n"
                "کندل کافی برای تحلیل نداریم."
            )
        )

    first_price = candles[0]["o"]
    price = candles[-1]["c"]

    high = max(
        x["h"]
        for x in candles
    )

    low = min(
        x["l"]
        for x in candles
    )

    recent = candles[-4:]

    if len(candles) >= 8:
        prior = candles[-8:-4]
    else:
        prior = []

    gain = (
        (price / first_price) - 1
    ) * 100

    pullback = (
        (price / high) - 1
    ) * 100

    recent_volume = (
        sum(
            x["v"]
            for x in recent
        )
        / len(recent)
    )

    if prior:
        prior_volume = (
            sum(
                x["v"]
                for x in prior
            )
            / len(prior)
        )
    else:
        prior_volume = recent_volume

    if prior_volume > 0:
        volume_ratio = (
            recent_volume
            / prior_volume
        )
    else:
        volume_ratio = 1.0

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

    sma_recent = (
        sum(
            x["c"]
            for x in recent
        )
        / len(recent)
    )

    if high > low:
        position = (
            (price - low)
            / (high - low)
        )
    else:
        position = 0.5

    score = 0

    # بالای میانگین کوتاه
    if price > sma_recent:
        score += 1

    # ساخت کف‌های بالاتر
    if higher_lows >= 2:
        score += 2

    # ساخت سقف‌های بالاتر
    if higher_highs >= 2:
        score += 1

    # افزایش حجم
    if volume_ratio >= 1.50:
        score += 2
    elif volume_ratio >= 1.15:
        score += 1

    # رشد سالم
    if 3 <= gain <= 45:
        score += 1

    # نزدیک بخش بالایی رنج
    if position >= 0.65:
        score += 1

    # ضد تعقیب پامپ
    if pullback <= -15:
        score -= 3

    # اگر بیش از حد پامپ کرده
    if gain >= 80:
        score -= 2

    # اگر از شروع شدیداً منفی شده
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

    display_symbol = symbol.replace(
        "-SWAP-USDT",
        "/USDT"
    )

    message = (
        f"ارز: {display_symbol}\n"
        f"بررسی: {hour} ساعت بعد از شروع\n"
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
            risk = price * 0.06

        tp1 = price + (
            1.5 * risk
        )

        tp2 = price + (
            2.5 * risk
        )

        tp3 = price + (
            4.0 * risk
        )

        message += (
            f"\n\nورود تقریبی: {price}"
            f"\nحد ضرر: {sl}"
            f"\nهدف ۱: {tp1}"
            f"\nهدف ۲: {tp2}"
            f"\nهدف ۳: {tp3}"
        )

    return title, message


def main():

    # تست تلگرام فقط در اجرای دستی GitHub
    if (
        os.getenv(
            "GITHUB_EVENT_NAME"
        )
        == "workflow_dispatch"
    ):
        print(
            "Manual run detected. "
            "Testing Telegram..."
        )

        send(
            "✅ اتصال New Listing Hunter "
            "به تلگرام سالم است."
        )

    state = load_state()

    state.setdefault(
        "init",
        False
    )

    state.setdefault(
        "items",
        {}
    )

    current = contracts()
    current_time = now()

    print(
        "Crypto USDT perpetuals:",
        len(current)
    )

    # اجرای اولیه:
    # تمام ارزهای فعلی خط پایه می‌شوند
    if not state["init"]:

        for symbol,
