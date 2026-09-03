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

exchange = ccxt.binance({
    "enableRateLimit": True
})


# =========================
# TELEGRAM
# =========================

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram token not found.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10,
        )

        if response.status_code != 200:
            print(
                "Telegram error:",
                response.status_code,
                response.text,
            )
            return False

        print("Telegram message sent successfully.")
        return True

    except Exception as error:
        print("Telegram send error:", error)
        return False


# =========================
# MARKET DATA
# =========================

def fetch_data(symbol):
    try:
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
        print(f"Fetch error for {symbol}: {error}")
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

    macd = ta.trend.MACD(df["close"])

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

    if buy_condition:
        stop_loss = price - (1.5 * atr)
        take_profit = price + (3.0 * atr)

        message = (
            f"🟢 <b>BUY SIGNAL</b>\n\n"
            f"🔹 <b>Pair:</b> #{symbol.replace('/USDT', '')}\n"
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
            f"🔹 <b>Pair:</b> #{symbol.replace('/USDT', '')}\n"
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

    # Telegram connection test
    send_telegram_message(
        "✅ AI Trade Scanner Telegram test successful"
    )

    for symbol in SYMBOLS:
        try:
            print(f"Scanning {symbol}...")
            analyze_symbol(symbol)

        except Exception as error:
            print(f"Error scanning {symbol}: {error}")

        time.sleep(0.5)

    print("Scan completed")


if __name__ == "__main__":
    main()
