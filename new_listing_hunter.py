import json, os, time
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
        return {"init": False, "items": {}}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"init": False, "items": {}}


def save_state(s):
    STATE.write_text(
        json.dumps(s, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def chat_id():
    if CHAT_ID:
        return CHAT_ID

    if not TOKEN:
        return ""

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"limit": 100},
            timeout=TIMEOUT,
        ).json()

        for u in reversed(r.get("result", [])):
            m = u.get("message") or u.get("channel_post")
            if m and m.get("chat", {}).get("id") is not None:
                return str(m["chat"]["id"])

    except Exception as e:
        print("chat id error:", e)

    return ""


def send(text):
    cid = chat_id()

    if not TOKEN or not cid:
        print("Telegram not ready. Token/chat id missing.")
        return

    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={
            "chat_id": cid,
            "text": text,
        },
        timeout=TIMEOUT,
    )

    r.raise_for_status()
    print("Telegram sent.")


def contracts():
    r = requests.get(
        f"{BASE}/api/v1/exchangeInfo",
        timeout=TIMEOUT,
    )

    r.raise_for_status()
    data = r.json()

    out = {}

    for x in data.get("contracts", []):
        symbol = str(x.get("symbol", "")).upper()
        cats = {str(c).lower() for c in x.get("categories", [])}

        if str(x.get("quoteAsset", "")).upper() != "USDT":
            continue

        if "-SWAP-USDT" not in symbol:
            continue

        if x.get("inverse") is True:
            continue

        # سهام و شاخص‌ها حذف شوند
        if "tradfi" in cats:
            continue

        out[symbol] = str(
            x.get("status", "UNKNOWN")
        ).upper()

    return out


def klines(symbol, start_iso):
    start_ms = int(
        datetime.fromisoformat(start_iso).timestamp() * 1000
    )

    r = requests.get(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": start_ms,
            "limit": 100,
        },
        timeout=TIMEOUT,
    )

    r.raise_for_status()

    current_ms = int(time.time() * 1000)
    rows = []

    for x in r.json():

        if len(x) < 7:
            continue

        # فقط کندل بسته‌شده
        if int(x[6]) > current_ms:
            continue

        rows.append(
            {
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5]),
            }
        )

    return rows


def analyze(symbol, start_iso, hour):

    c = klines(symbol, start_iso)

    if len(c) < 4:
        return (
            "👀 هنوز صبر",
            "کندل کافی برای تحلیل نداریم",
        )

    first = c[0]["o"]
    price = c[-1]["c"]

    high = max(x["h"] for x in c)
    low = min(x["l"] for x in c)

    recent = c[-4:]

    prior = (
        c[-8:-4]
        if len(c) >= 8
        else []
    )

    gain = (
        (price / first) - 1
    ) * 100

    pullback = (
        (price / high) - 1
    ) * 100

    rv = sum(
        x["v"] for x in recent
    ) / len(recent)

    pv = (
        sum(x["v"] for x in prior) / len(prior)
        if prior
        else rv
    )

    vr = rv / pv if pv else 1

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

    sma = sum(
        x["c"] for x in recent
    ) / len(recent)

    pos = (
        (price - low) / (high - low)
        if high > low
        else 0.5
    )

    score = 0

    if price > sma:
        score += 1

    if higher_lows >= 2:
        score += 2

    if higher_highs >= 2:
        score += 1

    if vr >= 1.5:
        score += 2
    elif vr >= 1.15:
        score += 1

    if 3 <= gain <= 45:
        score += 1

    if pos >= 0.65:
        score += 1

    # ضد تعقیب پامپ
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

    msg = (
        f"{symbol.replace('-SWAP-USDT', '/USDT')}\n"
        f"بررسی {hour} ساعت بعد از شروع\n"
        f"امتیاز: {score}\n"
        f"قیمت: {price}\n"
        f"رشد از شروع: {gain:+.1f}٪\n"
        f"فاصله از سقف: {pullback:+.1f}٪\n"
        f"نسبت حجم اخیر: {vr:.2f}x"
    )

    if score >= 6:

        sl = max(
            min(x["l"] for x in recent),
            price * 0.92,
        )

        risk = price - sl

        if risk <= 0:
            sl = price * 0.94
            risk = price * 0.06

        msg += (
            f"\n\nورود تقریبی: {price}"
            f"\nحد ضرر: {sl}"
            f"\nهدف ۱: {price + 1.5 * risk}"
            f"\nهدف ۲: {price + 2.5 * risk}"
            f"\nهدف ۳: {price + 4 * risk}"
        )

    return title, msg


def main():

    s = load_state()

    s.setdefault(
        "init",
        False,
    )

    s.setdefault(
        "items",
        {},
    )

    cur = contracts()
    t = now()

    print(
        "Crypto USDT perpetuals:",
        len(cur),
    )

    # اجرای اول:
    # فقط لیست فعلی را ذخیره می‌کند
    # تا همه ارزهای قدیمی جدید حساب نشوند.

    if not s["init"]:

        for symbol, status in cur.items():

            s["items"][symbol] = {
                "status": status,
                "baseline": True,
                "trading_since": None,
                "sent": [],
            }

        s["init"] = True

        save_state(s)

        send(
            "✅ شکارچی لیست‌های جدید توبیت فعال شد.\n"
            "ارزهای فعلی به عنوان خط پایه ذخیره شدند.\n"
            "از اجرای بعد فقط موارد واقعاً جدید گزارش می‌شوند."
        )

        return

    for symbol, status in cur.items():

        rec = s["items"].get(symbol)

        # ارز جدید پیدا شد
        if rec is None:

            rec = {
                "status": status,
                "baseline": False,
                "trading_since": (
                    t.isoformat()
                    if status == "TRADING"
                    else None
                ),
                "sent": [],
            }

            s["items"][symbol] = rec

            if status == "TRADING":
                fa = "معامله شروع شده"
            else:
                fa = "هنوز قابل معامله نیست"

            send(
                "🚨 ارز جدید در فیوچرز توبیت\n"
                f"ارز: {symbol.replace('-SWAP-USDT', '/USDT')}\n"
                f"وضعیت: {fa}\n"
                "فعلاً ورود نکن؛ ربات در حال جمع‌آوری داده است."
            )

        old = rec.get("status")

        # ONLINE تبدیل به TRADING شد
        if old != status:

            rec["status"] = status

            if status == "TRADING":

                rec["trading_since"] = t.isoformat()
                rec["sent"] = []

                send(
                    "🟢 معامله ارز جدید شروع شد\n"
                    f"ارز: {symbol.replace('-SWAP-USDT', '/USDT')}\n"
                    "ربات ۱، ۲ و ۴ ساعت بعد آن را بررسی می‌کند."
                )

        # ارزهای قدیمی را تحلیل نکن
        if rec.get("baseline"):
            continue

        if (
            status != "TRADING"
            or not rec.get("trading_since")
        ):
            continue

        start = datetime.fromisoformat(
            rec["trading_since"]
        )

        age = (
            t - start
        ).total_seconds() / 3600

        sent_hours = set(
            rec.get("sent", [])
        )

        for h in (1, 2, 4):

            if (
                age >= h
                and h not in sent_hours
            ):

                try:

                    title, body = analyze(
                        symbol,
                        rec["trading_since"],
                        h,
                    )

                    send(
                        f"{title} | شکارچی لیست جدید\n"
                        f"{body}\n\n"
                        "⚠️ معامله خودکار باز نمی‌شود."
                    )

                    sent_hours.add(h)

                    rec["sent"] = sorted(
                        sent_hours
                    )

                except Exception as e:

                    print(
                        f"analysis error "
                        f"{symbol} "
                        f"{h}h:",
                        e,
                    )

    save_state(s)

    print("Done.")


if __name__ == "__main__":
    main()
