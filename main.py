import os
import time
import requests
import ccxt
import pandas as pd
import ta


# =========================
# CONFIGURATION
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = "6175027599"

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "LINK/USDT",
    "NEAR/USDT",
    "LTC/USDT",
    "SHIB/USDT",
    "SUI/USDT",
    "PEPE/USDT",
    "APT/USDT",
    "FET/USDT",
    "RENDER/USDT",
    "TON/USDT",
    "TRX/USDT",
]

TIMEFRAME = "15m"


# =========================
# EXCHANGE - TOOBIT
# =========================

exchange = ccxt.toobit({
    "enableRateLimit": True,
})


# =========================
# TELEGRAM
# =========================

def send_telegram_message(message):
    token = (TELEGRAM_BOT_TOKEN or "").strip()

    if token.lower().startswith("bot"):
        token = token[3:].strip()

    print("Telegram token loaded:", bool(token))
    print("Telegram token length:", len(token))
    print("Telegram token has colon:", ":" in token)

    if not token:
        print("Telegram token is missing")
        return False

    try:
        # First test the bot token
        test_url = f"https://api.telegram.org/bot{token}/getMe"

        test_response = requests.get(
            test_url,
            timeout=15,
        )

        print(
            "Telegram getMe status:",
            test_response.status_code,
        )

        print(
            "Telegram getMe response:",
            test_response.text,
        )

        if test_response.status_code != 200:
            return False

        # Send message
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        print(
            "Telegram sendMessage status:",
            response.status_code,
        )

        print(
            "Telegram sendMessage response:",
            response.text,
        )

        if response.status_code == 200:
            print("Telegram message sent successfully.")
            return True

        return False

    except Exception as error:
        print("Telegram request error:", error)
        return False


# =========================
# MARKET DATA
# =========================

def fetch_data(symbol):
    try:
        if not exchange.markets:
            exchange.load_markets()

        if symbol not in exchange.markets:
            print(f"{symbol} is not available on Toobit.")
            return None

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=100,
        )

        df = pd.DataFrame(
            ohlcv,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        return df

    except Exception as error:
        print(
            f"Fetch error for {symbol}: {error}"
        )
        return None


# =========================
# ANALYSIS
# =========================

def analyze_symbol(symbol):
    df = fetch_data(symbol)

    if df is None or len(df) < 50:
        return

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"],
        window=14,
    ).rsi()

    df["ema_fast"] = ta.trend.EMAIndicator(
        df["close"],
        window=20,
    ).ema_indicator()

    df["ema_slow"] = ta.trend.EMAIndicator(
        df["close"],
        window=50,
    ).ema_indicator()

    macd = ta.trend.MACD(
        df["close"]
    )

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()

    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"],
        df["low"],
        df["close"],
        window=14,
    ).average_true_range()

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    price = curr["close"]
    atr = curr["atr"]

    buy_condition = (
        curr["rsi"] < 38
        and curr["ema_fast"] > curr["ema_slow"]
        and curr["macd"] > curr["macd_signal"]
        and prev["macd"] <= prev["macd_signal"]
    )

    sell_condition = (
        curr["rsi"] > 62
        and curr["ema_fast"] < curr["ema_slow"]
        and curr["macd"] < curr["macd_signal"]
        and prev["macd"] >= prev["macd_signal"]
    )

    print(
        f"{symbol} | "
        f"Price: {price} | "
        f"RSI: {curr['rsi']:.2f}"
    )

    if buy_condition:
        stop_loss = price - (1.5 * atr)
        take_profit = price + (3.0 * atr)

        message = (
            f"🟢 <b>BUY SIGNAL</b>\n\n"
            f"🔹 <b>Pair:</b> {symbol}\n"
            f"⏱ <b>Timeframe:</b> {TIMEFRAME}\n"
            f"💵 <b>Entry:</b> {price:,.4f}\n"
            f"🛑 <b>SL:</b> {stop_loss:,.4f}\n"
            f"🎯 <b>TP:</b> {take_profit:,.4f}\n"
            f"📊 <b>RSI:</b> {curr['rsi']:.1f}\n"
            f"⚖️ <b>Risk/Reward:</b> 1:2"
        )

        send_telegram_message(message)

    elif sell_condition:
        stop_loss = price + (1.5 * atr)
        take_profit = price - (3.0 * atr)

        message = (
            f"🔴 <b>SELL SIGNAL</b>\n\n"
            f"🔹 <b>Pair:</b> {symbol}\n"
            f"⏱ <b>Timeframe:</b> {TIMEFRAME}\n"
            f"💵 <b>Entry:</b> {price:,.4f}\n"
            f"🛑 <b>SL:</b> {stop_loss:,.4f}\n"
            f"🎯 <b>TP:</b> {take_profit:,.4f}\n"
            f"📊 <b>RSI:</b> {curr['rsi']:.1f}\n"
            f"⚖️ <b>Risk/Reward:</b> 1:2"
        )

        send_telegram_message(message)


# =========================
# RUN ONE SCAN
# =========================

def main():
    print("AI Trade Scanner started")

    # Test Telegram first
    send_telegram_message(
        "✅ AI Trade Scanner Telegram test successful"
    )

    print("Connecting to Toobit...")

    try:
        exchange.load_markets()
        print(
            "Toobit connected successfully."
        )
    except Exception as error:
        print(
            "Toobit connection error:",
            error,
        )
        return

    for symbol in SYMBOLS:
        try:
            print(
                f"Scanning {symbol}..."
            )

            analyze_symbol(symbol)

        except Exception as error:
            print(
                f"Error scanning {symbol}: {error}"
            )

        time.sleep(0.5)

    print("Scan completed")


if __name__ == "__main__":
    main()
