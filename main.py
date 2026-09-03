import os
import time
import requests
import ccxt
import pandas as pd
import ta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENTRY_TF = "1h"
TREND_TF = "4h"
MIN_SCORE = 8

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT",
    "DOT/USDT", "LINK/USDT", "NEAR/USDT", "LTC/USDT",
    "SHIB/USDT", "SUI/USDT", "PEPE/USDT", "APT/USDT",
    "FET/USDT", "RENDER/USDT", "TON/USDT", "TRX/USDT"
]

exchange = ccxt.toobit({
    "enableRateLimit": True,
    "timeout": 20000
})


def clean_token():
    token = (TOKEN or "").strip()
    if token.lower().startswith("bot"):
        token = token[3:].strip()
    return token


def get_chat_id():
    token = clean_token()

    if not token:
        print("Telegram token missing")
        return None

    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        r = requests.get(url, timeout=15)

        if r.status_code != 200:
            print("getUpdates error:", r.text)
            return None

        for update in reversed(r.json().get("result", [])):
            message = update.get("message", {})
            chat = message.get("chat", {})

            if chat.get("id") is not None:
                return str(chat["id"])

    except Exception as e:
        print("Chat ID error:", e)

    return None


def send_message(text):
    token = clean_token()
    chat_id = get_chat_id()

    if not token or not chat_id:
        print("Telegram connection unavailable")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )

        print("Telegram status:", r.status_code)

    except Exception as e:
        print("Telegram error:", e)


def fetch_data(symbol, timeframe):
    try:
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=260
        )

        df = pd.DataFrame(
            candles,
            columns=[
                "timestamp", "open", "high",
                "low", "close", "volume"
            ]
        )

        df["datetime"] = pd.to_datetime(
            df["timestamp"],
            unit="ms",
            utc=True
        )

        return df

    except Exception as e:
        print(f"Fetch error {symbol} {timeframe}: {e}")
        return None


def indicators(df):
    if df is None or len(df) < 220:
        return None

    df = df.copy()

    df["ema20"] = ta.trend.EMAIndicator(
        df["close"], 20
    ).ema_indicator()

    df["ema50"] = ta.trend.EMAIndicator(
        df["close"], 50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        df["close"], 200
    ).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"], 14
    ).rsi()

    macd = ta.trend.MACD(df["close"])

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"],
        df["low"],
        df["close"],
        14
    ).average_true_range()

    df["adx"] = ta.trend.ADXIndicator(
        df["high"],
        df["low"],
        df["close"],
        14
    ).adx()

    df["vol_ma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma"]

    return df.dropna().reset_index(drop=True)


def trend_4h(df):
    x = df.iloc[-2]

    if (
        x["close"] > x["ema200"]
        and x["ema20"] > x["ema50"] > x["ema200"]
        and x["rsi"] >= 50
    ):
        return "BULLISH"

    if (
        x["close"] < x["ema200"]
        and x["ema20"] < x["ema50"] < x["ema200"]
        and x["rsi"] <= 50
    ):
        return "BEARISH"

    return "NEUTRAL"


def score_signal(df1, df4, side):
    x = df1.iloc[-2]
    p = df1.iloc[-3]
    trend = trend_4h(df4)

    score = 0
    reasons = []

    if side == "LONG":
        tests = [
            (trend == "BULLISH", 3, "4H bullish"),
            (x["close"] > x["ema50"], 1, "Above EMA50"),
            (x["ema20"] > x["ema50"], 1, "EMA bullish"),
            (45 <= x["rsi"] <= 68, 1, f"RSI {x['rsi']:.1f}"),
            (x["macd"] > x["macd_signal"], 1, "MACD bullish"),
            (x["macd_hist"] > p["macd_hist"], 1, "Momentum rising"),
            (x["adx"] >= 18, 1, f"ADX {x['adx']:.1f}"),
            (x["vol_ratio"] >= 0.8, 1, "Volume confirmed")
        ]

    else:
        tests = [
            (trend == "BEARISH", 3, "4H bearish"),
            (x["close"] < x["ema50"], 1, "Below EMA50"),
            (x["ema20"] < x["ema50"], 1, "EMA bearish"),
            (32 <= x["rsi"] <= 55, 1, f"RSI {x['rsi']:.1f}"),
            (x["macd"] < x["macd_signal"], 1, "MACD bearish"),
            (x["macd_hist"] < p["macd_hist"], 1, "Momentum falling"),
            (x["adx"] >= 18, 1, f"ADX {x['adx']:.1f}"),
            (x["vol_ratio"] >= 0.8, 1, "Volume confirmed")
        ]

    distance = abs(x["close"] - x["ema20"]) / x["close"]

    if distance <= 0.015:
        tests.append((True, 1, "EMA20 pullback"))

    for ok, points, reason in tests:
        if ok:
            score += points
            reasons.append(reason)

    return score, reasons


def levels(df, side):
    x = df.iloc[-2]
    entry = float(x["close"])
    atr = float(x["atr"])
    recent = df.iloc[-12:-1]

    if side == "LONG":
        swing = float(recent["low"].min())
        sl = min(entry - 1.5 * atr, swing - 0.2 * atr)
        risk = entry - sl
        return entry, sl, entry + risk, entry + 2*risk, entry + 3*risk

    swing = float(recent["high"].max())
    sl = max(entry + 1.5 * atr, swing + 0.2 * atr)
    risk = sl - entry

    return entry, sl, entry - risk, entry - 2*risk, entry - 3*risk


def send_signal(symbol, side, score, reasons, df):
    entry, sl, tp1, tp2, tp3 = levels(df, side)
    x = df.iloc[-2]

    icon = "🟢" if side == "LONG" else "🔴"
    reason_text = "\n".join("• " + r for r in reasons)

    message = (
        f"{icon} <b>{side} SIGNAL</b>\n\n"
        f"💎 <b>{symbol}</b>\n"
        f"⏱ 1H entry / 4H trend\n\n"
        f"💵 Entry: {entry:.6f}\n"
        f"🛑 SL: {sl:.6f}\n"
        f"🎯 TP1: {tp1:.6f}\n"
        f"🎯 TP2: {tp2:.6f}\n"
        f"🎯 TP3: {tp3:.6f}\n\n"
        f"⭐ Score: {score}/11\n"
        f"📊 RSI: {x['rsi']:.1f}\n"
        f"📏 ADX: {x['adx']:.1f}\n\n"
        f"{reason_text}"
    )

    send_message(message)


def analyze(symbol):
    print(f"Scanning {symbol}...")

    df1 = indicators(fetch_data(symbol, ENTRY_TF))
    df4 = indicators(fetch_data(symbol, TREND_TF))

    if df1 is None or df4 is None:
        print("Not enough data:", symbol)
        return

    trend = trend_4h(df4)
    long_score, long_reasons = score_signal(df1, df4, "LONG")
    short_score, short_reasons = score_signal(df1, df4, "SHORT")

    print(
        symbol,
        "| Trend:", trend,
        "| LONG:", long_score,
        "| SHORT:", short_score
    )

    if trend == "BULLISH" and long_score >= MIN_SCORE:
        send_signal(
            symbol, "LONG",
            long_score, long_reasons, df1
        )

    elif trend == "BEARISH" and short_score >= MIN_SCORE:
        send_signal(
            symbol, "SHORT",
            short_score, short_reasons, df1
        )


def main():
    print("AI Swing Trade Scanner V2 started")

    try:
        exchange.load_markets()
        print("Toobit connected successfully")

    except Exception as e:
        print("Toobit connection error:", e)
        return

    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        send_message(
            "✅ <b>AI Swing Trade Scanner V2 started</b>\n"
            "⏱ Analysis: 1H + 4H"
        )

    for symbol in SYMBOLS:
        try:
            analyze(symbol)
        except Exception as e:
            print("Analysis error:", symbol, e)

        time.sleep(0.5)

    print("All scans completed")


if __name__ == "__main__":
    main()
