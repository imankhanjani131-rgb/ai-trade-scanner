import os
import time
import json
import requests
import ccxt
import pandas as pd
import ta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ENTRY_TF = "1h"
TREND_TF = "4h"

MIN_SCORE = 9
MIN_ADX = 22

STATE_FILE = "signal_state.json"

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

CHAT_ID = None


# =========================
# SIGNAL STATE
# =========================

def load_state():
    if not os.path.exists(STATE_FILE):
        print("No previous signal state found")
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        print(
            "Signal state loaded:",
            len(state),
            "active signals"
        )

        return state

    except Exception as error:
        print("State load error:", error)
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as file:
            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as error:
        print("State save error:", error)


def clear_signal_state(state, symbol):
    if symbol in state:
        print(
            "Previous signal cleared:",
            symbol,
            state[symbol].get("side")
        )

        state.pop(symbol, None)


def is_duplicate_signal(state, symbol, side):
    previous = state.get(symbol)

    if not previous:
        return False

    return previous.get("side") == side


# =========================
# TELEGRAM
# =========================

def clean_token():
    token = (TOKEN or "").strip()

    if token.lower().startswith("bot"):
        token = token[3:].strip()

    return token


def get_chat_id():
    global CHAT_ID

    if CHAT_ID:
        return CHAT_ID

    token = clean_token()

    if not token:
        print("Telegram token missing")
        return None

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{token}/getUpdates"
        )

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            print(
                "Telegram getUpdates error:",
                response.text
            )
            return None

        updates = response.json().get(
            "result",
            []
        )

        for update in reversed(updates):
            message = update.get(
                "message",
                {}
            )

            chat = message.get(
                "chat",
                {}
            )

            if chat.get("id") is not None:
                CHAT_ID = str(chat["id"])
                return CHAT_ID

    except Exception as error:
        print(
            "Chat ID error:",
            error
        )

    return None


def send_message(text):
    token = clean_token()
    chat_id = get_chat_id()

    if not token or not chat_id:
        print(
            "Telegram connection unavailable"
        )
        return False

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{token}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )

        print(
            "Telegram status:",
            response.status_code
        )

        if response.status_code != 200:
            print(
                "Telegram response:",
                response.text
            )
            return False

        return True

    except Exception as error:
        print(
            "Telegram error:",
            error
        )
        return False


# =========================
# MARKET DATA
# =========================

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
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        df["datetime"] = pd.to_datetime(
            df["timestamp"],
            unit="ms",
            utc=True
        )

        return df

    except Exception as error:
        print(
            f"Fetch error {symbol} "
            f"{timeframe}: {error}"
        )

        return None


# =========================
# INDICATORS
# =========================

def indicators(df):
    if df is None or len(df) < 220:
        return None

    df = df.copy()

    df["ema20"] = ta.trend.EMAIndicator(
        df["close"],
        20
    ).ema_indicator()

    df["ema50"] = ta.trend.EMAIndicator(
        df["close"],
        50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        df["close"],
        200
    ).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"],
        14
    ).rsi()

    macd = ta.trend.MACD(
        df["close"]
    )

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["atr"] = (
        ta.volatility.AverageTrueRange(
            df["high"],
            df["low"],
            df["close"],
            14
        ).average_true_range()
    )

    df["adx"] = ta.trend.ADXIndicator(
        df["high"],
        df["low"],
        df["close"],
        14
    ).adx()

    df["vol_ma"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["vol_ratio"] = (
        df["volume"] /
        df["vol_ma"]
    )

    return (
        df.dropna()
        .reset_index(drop=True)
    )


# =========================
# 4H TREND
# =========================

def trend_4h(df):
    x = df.iloc[-2]

    if (
        x["close"] > x["ema200"]
        and x["ema20"] > x["ema50"]
        and x["ema50"] > x["ema200"]
        and x["rsi"] >= 50
    ):
        return "BULLISH"

    if (
        x["close"] < x["ema200"]
        and x["ema20"] < x["ema50"]
        and x["ema50"] < x["ema200"]
        and x["rsi"] <= 50
    ):
        return "BEARISH"

    return "NEUTRAL"


# =========================
# SCORE
# =========================

def score_signal(df1, df4, side):
    x = df1.iloc[-2]
    previous = df1.iloc[-3]

    trend = trend_4h(df4)

    score = 0
    reasons = []

    if side == "LONG":

        tests = [
            (
                trend == "BULLISH",
                3,
                "4H bullish"
            ),
            (
                x["close"] > x["ema50"],
                1,
                "Above EMA50"
            ),
            (
                x["ema20"] > x["ema50"],
                1,
                "EMA bullish"
            ),
            (
                45 <= x["rsi"] < 70,
                1,
                f"RSI {x['rsi']:.1f}"
            ),
            (
                x["macd"] > x["macd_signal"],
                1,
                "MACD bullish"
            ),
            (
                x["macd_hist"] >
                previous["macd_hist"],
                1,
                "Momentum rising"
            ),
            (
                x["adx"] >= MIN_ADX,
                1,
                f"ADX {x['adx']:.1f}"
            ),
            (
                x["vol_ratio"] >= 0.8,
                1,
                "Volume confirmed"
            )
        ]

    else:

        tests = [
            (
                trend == "BEARISH",
                3,
                "4H bearish"
            ),
            (
                x["close"] < x["ema50"],
                1,
                "Below EMA50"
            ),
            (
                x["ema20"] < x["ema50"],
                1,
                "EMA bearish"
            ),
            (
                30 < x["rsi"] <= 55,
                1,
                f"RSI {x['rsi']:.1f}"
            ),
            (
                x["macd"] < x["macd_signal"],
                1,
                "MACD bearish"
            ),
            (
                x["macd_hist"] <
                previous["macd_hist"],
                1,
                "Momentum falling"
            ),
            (
                x["adx"] >= MIN_ADX,
                1,
                f"ADX {x['adx']:.1f}"
            ),
            (
                x["vol_ratio"] >= 0.8,
                1,
                "Volume confirmed"
            )
        ]

    distance = abs(
        x["close"] - x["ema20"]
    ) / x["close"]

    if distance <= 0.015:
        tests.append(
            (
                True,
                1,
                "EMA20 pullback"
            )
        )

    for ok, points, reason in tests:
        if ok:
            score += points
            reasons.append(reason)

    return score, reasons


# =========================
# ENTRY / SL / TP
# =========================

def levels(df, side):
    x = df.iloc[-2]

    entry = float(
        x["close"]
    )

    atr = float(
        x["atr"]
    )

    recent = df.iloc[-12:-1]

    if side == "LONG":

        swing_low = float(
            recent["low"].min()
        )

        sl = min(
            entry - (1.5 * atr),
            swing_low - (0.2 * atr)
        )

        risk = entry - sl

        tp1 = entry + risk
        tp2 = entry + (2 * risk)
        tp3 = entry + (3 * risk)

    else:

        swing_high = float(
            recent["high"].max()
        )

        sl = max(
            entry + (1.5 * atr),
            swing_high + (0.2 * atr)
        )

        risk = sl - entry

        tp1 = entry - risk
        tp2 = entry - (2 * risk)
        tp3 = entry - (3 * risk)

    return (
        entry,
        sl,
        tp1,
        tp2,
        tp3
    )


# =========================
# SEND SIGNAL
# =========================

def send_signal(
    symbol,
    side,
    score,
    reasons,
    df
):
    (
        entry,
        sl,
        tp1,
        tp2,
        tp3
    ) = levels(
        df,
        side
    )

    x = df.iloc[-2]

    icon = (
        "🟢"
        if side == "LONG"
        else "🔴"
    )

    reason_text = "\n".join(
        "• " + reason
        for reason in reasons
    )

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

    return send_message(message)


# =========================
# ANALYZE SYMBOL
# =========================

def analyze(symbol, state):
    print(
        f"Scanning {symbol}..."
    )

    df1 = indicators(
        fetch_data(
            symbol,
            ENTRY_TF
        )
    )

    df4 = indicators(
        fetch_data(
            symbol,
            TREND_TF
        )
    )

    if df1 is None or df4 is None:
        print(
            "Not enough data:",
            symbol
        )
        return

    trend = trend_4h(df4)

    x = df1.iloc[-2]

    print(
        f"{symbol} | "
        f"RSI: {x['rsi']:.1f} | "
        f"ADX: {x['adx']:.1f} | "
        f"Trend: {trend}"
    )

    # Safety filters

    if (
        trend == "BULLISH"
        and x["rsi"] >= 70
    ):
        print(
            "LONG rejected: RSI too high"
        )

        clear_signal_state(
            state,
            symbol
        )

        return

    if (
        trend == "BEARISH"
        and x["rsi"] <= 30
    ):
        print(
            "SHORT rejected: RSI too low"
        )

        clear_signal_state(
            state,
            symbol
        )

        return

    if (
        trend in [
            "BULLISH",
            "BEARISH"
        ]
        and x["adx"] < MIN_ADX
    ):
        print(
            "Signal rejected: ADX too weak"
        )

        clear_signal_state(
            state,
            symbol
        )

        return

    long_score, long_reasons = (
        score_signal(
            df1,
            df4,
            "LONG"
        )
    )

    short_score, short_reasons = (
        score_signal(
            df1,
            df4,
            "SHORT"
        )
    )

    print(
        symbol,
        "| LONG:",
        long_score,
        "| SHORT:",
        short_score
    )

    side = None
    score = 0
    reasons = []

    if (
        trend == "BULLISH"
        and long_score >= MIN_SCORE
    ):
        side = "LONG"
        score = long_score
        reasons = long_reasons

    elif (
        trend == "BEARISH"
        and short_score >= MIN_SCORE
    ):
        side = "SHORT"
        score = short_score
        reasons = short_reasons

    if side is None:
        print(
            "No strong signal:",
            symbol
        )

        clear_signal_state(
            state,
            symbol
        )

        return

    # Duplicate protection

    if is_duplicate_signal(
        state,
        symbol,
        side
    ):
        print(
            "Duplicate signal skipped:",
            symbol,
            side
        )

        return

    print(
        "NEW signal detected:",
        symbol,
        side
    )

    sent = send_signal(
        symbol,
        side,
        score,
        reasons,
        df1
    )

    if sent:
        state[symbol] = {
            "side": side,
            "entry": float(x["close"]),
            "timestamp": int(x["timestamp"])
        }

        save_state(state)

        print(
            "Signal state saved:",
            symbol,
            side
        )


# =========================
# MAIN
# =========================

def main():
    print(
        "AI Swing Trade Scanner V2.2 started"
    )

    state = load_state()

    try:
        exchange.load_markets()

        print(
            "Toobit connected successfully"
        )

    except Exception as error:
        print(
            "Toobit connection error:",
            error
        )
        return

    if (
        os.getenv("GITHUB_EVENT_NAME")
        == "workflow_dispatch"
    ):
        send_message(
            "✅ <b>AI Swing Trade Scanner V2.2 started</b>\n"
            "⏱ Analysis: 1H + 4H\n"
            "🛡 Strong-signal filters enabled\n"
            "🔁 Duplicate protection enabled"
        )

    for symbol in SYMBOLS:

        try:
            analyze(
                symbol,
                state
            )

        except Exception as error:
            print(
                "Analysis error:",
                symbol,
                error
            )

        save_state(state)

        time.sleep(0.5)

    print(
        "Active signal states:",
        len(state)
    )

    print(
        "All scans completed"
    )


if __name__ == "__main__":
    main()
