import os
import time
import json
import requests
import ccxt
import pandas as pd
import ta

from forward_tracker import (
    has_open_trade,
    record_signal,
    update_open_trades,
    closed_trade_text,
    summary_text,
)

# ============================================================
# AI SWING TRADE SCANNER - FINAL FORWARD TEST + TRACKER
# Filter E: LONG + ADX >= 40 + RSI 60-70 + SCORE == 9
# Entry: 1H | Trend: 4H | Primary target: TP2
# SIGNAL ONLY - NO AUTOMATIC ORDER EXECUTION
# ============================================================

VERSION = "V3.0-E"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENV_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ENTRY_TF = "1h"
TREND_TF = "4h"

BASE_MIN_ADX = 22
FINAL_MIN_ADX = 40
FINAL_MIN_RSI = 60
FINAL_MAX_RSI = 70
FINAL_SCORE = 9

STATE_FILE = "signal_state.json"

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

exchange = ccxt.toobit({
    "enableRateLimit": True,
    "timeout": 20000,
})

CHAT_ID = None


# ============================================================
# SIGNAL STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        print(
            "No previous signal state found"
        )

        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            state = json.load(
                f
            )

        if not isinstance(
            state,
            dict
        ):

            return {}

        print(
            "Signal state loaded:",
            len(state)
        )

        return state

    except Exception as error:

        print(
            "State load error:",
            error
        )

        return {}


def save_state(
    state
):

    try:

        temp_file = (
            STATE_FILE
            + ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            STATE_FILE
        )

    except Exception as error:

        print(
            "State save error:",
            error
        )


def clear_signal_state(
    state,
    symbol
):

    if symbol in state:

        print(
            "Previous signal cleared:",
            symbol
        )

        state.pop(
            symbol,
            None
        )


def is_duplicate_signal(
    state,
    symbol
):

    previous = state.get(
        symbol
    )

    return bool(
        previous
        and previous.get(
            "side"
        ) == "LONG"
    )


# ============================================================
# TELEGRAM
# ============================================================

def clean_token():

    token = (
        TOKEN or ""
    ).strip()

    if token.lower().startswith(
        "bot"
    ):

        token = (
            token[3:]
            .strip()
        )

    return token


def get_chat_id():

    global CHAT_ID

    if CHAT_ID:

        return CHAT_ID

    if ENV_CHAT_ID:

        CHAT_ID = str(
            ENV_CHAT_ID
        ).strip()

        return CHAT_ID

    token = clean_token()

    if not token:

        print(
            "Telegram token missing"
        )

        return None

    try:

        response = requests.get(
            f"https://api.telegram.org/"
            f"bot{token}/getUpdates",
            timeout=15
        )

        if response.status_code != 200:

            print(
                "Telegram getUpdates error:",
                response.text
            )

            return None

        updates = (
            response
            .json()
            .get(
                "result",
                []
            )
        )

        for update in reversed(
            updates
        ):

            chat = (
                update
                .get(
                    "message",
                    {}
                )
                .get(
                    "chat",
                    {}
                )
            )

            if chat.get(
                "id"
            ) is not None:

                CHAT_ID = str(
                    chat[
                        "id"
                    ]
                )

                return CHAT_ID

    except Exception as error:

        print(
            "Chat ID error:",
            error
        )

    return None


def send_message(
    text
):

    token = clean_token()

    chat_id = get_chat_id()

    if (
        not token
        or not chat_id
    ):

        print(
            "Telegram connection unavailable"
        )

        return False

    try:

        response = requests.post(
            f"https://api.telegram.org/"
            f"bot{token}/sendMessage",
            json={
                "chat_id":
                    chat_id,

                "text":
                    text,

                "parse_mode":
                    "HTML",
            },
            timeout=15,
        )

        print(
            "Telegram status:",
            response.status_code
        )

        if (
            response.status_code
            != 200
        ):

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


# ============================================================
# MARKET DATA
# ============================================================

def fetch_data(
    symbol,
    timeframe
):

    try:

        candles = (
            exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=260
            )
        )

        if not candles:

            return None

        df = pd.DataFrame(
            candles,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

        df[
            "datetime"
        ] = pd.to_datetime(
            df[
                "timestamp"
            ],
            unit="ms",
            utc=True
        )

        return df

    except Exception as error:

        print(
            f"Fetch error "
            f"{symbol} "
            f"{timeframe}: "
            f"{error}"
        )

        return None


# ============================================================
# INDICATORS
# ============================================================

def indicators(
    df
):

    if (
        df is None
        or len(df) < 220
    ):

        return None

    df = df.copy()

    df[
        "ema20"
    ] = (
        ta.trend
        .EMAIndicator(
            df[
                "close"
            ],
            window=20
        )
        .ema_indicator()
    )

    df[
        "ema50"
    ] = (
        ta.trend
        .EMAIndicator(
            df[
                "close"
            ],
            window=50
        )
        .ema_indicator()
    )

    df[
        "ema200"
    ] = (
        ta.trend
        .EMAIndicator(
            df[
                "close"
            ],
            window=200
        )
        .ema_indicator()
    )

    df[
        "rsi"
    ] = (
        ta.momentum
        .RSIIndicator(
            df[
                "close"
            ],
            window=14
        )
        .rsi()
    )

    macd = (
        ta.trend.MACD(
            df[
                "close"
            ]
        )
    )

    df[
        "macd"
    ] = (
        macd.macd()
    )

    df[
        "macd_signal"
    ] = (
        macd.macd_signal()
    )

    df[
        "macd_hist"
    ] = (
        macd.macd_diff()
    )

    df[
        "atr"
    ] = (
        ta.volatility
        .AverageTrueRange(
            df[
                "high"
            ],
            df[
                "low"
            ],
            df[
                "close"
            ],
            window=14
        )
        .average_true_range()
    )

    df[
        "adx"
    ] = (
        ta.trend
        .ADXIndicator(
            df[
                "high"
            ],
            df[
                "low"
            ],
            df[
                "close"
            ],
            window=14
        )
        .adx()
    )

    df[
        "vol_ma"
    ] = (
        df[
            "volume"
        ]
        .rolling(
            20
        )
        .mean()
    )

    df[
        "vol_ratio"
    ] = (
        df[
            "volume"
        ]
        / df[
            "vol_ma"
        ]
    )

    return (
        df
        .dropna()
        .reset_index(
            drop=True
        )
    )


# ============================================================
# 4H TREND
# ============================================================

def trend_4h(
    df
):

    # Last closed 4H candle

    x = df.iloc[
        -2
    ]

    if (
        x[
            "close"
        ]
        > x[
            "ema200"
        ]

        and x[
            "ema20"
        ]
        > x[
            "ema50"
        ]

        and x[
            "ema50"
        ]
        > x[
            "ema200"
        ]

        and x[
            "rsi"
        ]
        >= 50
    ):

        return "BULLISH"

    if (
        x[
            "close"
        ]
        < x[
            "ema200"
        ]

        and x[
            "ema20"
        ]
        < x[
            "ema50"
        ]

        and x[
            "ema50"
        ]
        < x[
            "ema200"
        ]

        and x[
            "rsi"
        ]
        <= 50
    ):

        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# SCORE ENGINE
# ============================================================

def score_long(
    df1,
    df4
):

    # Last closed 1H candle

    x = df1.iloc[
        -2
    ]

    previous = df1.iloc[
        -3
    ]

    trend = trend_4h(
        df4
    )

    tests = [

        (
            trend
            == "BULLISH",
            3,
            "4H bullish",
        ),

        (
            x[
                "close"
            ]
            > x[
                "ema50"
            ],
            1,
            "Above EMA50",
        ),

        (
            x[
                "ema20"
            ]
            > x[
                "ema50"
            ],
            1,
            "EMA bullish",
        ),

        (
            45
            <= x[
                "rsi"
            ]
            < 70,
            1,
            f"RSI "
            f"{x['rsi']:.1f}",
        ),

        (
            x[
                "macd"
            ]
            > x[
                "macd_signal"
            ],
            1,
            "MACD bullish",
        ),

        (
            x[
                "macd_hist"
            ]
            > previous[
                "macd_hist"
            ],
            1,
            "Momentum rising",
        ),

        (
            x[
                "adx"
            ]
            >= BASE_MIN_ADX,
            1,
            f"ADX "
            f"{x['adx']:.1f}",
        ),

        (
            x[
                "vol_ratio"
            ]
            >= 0.8,
            1,
            "Volume confirmed",
        ),
    ]

    distance = (

        abs(
            x[
                "close"
            ]
            - x[
                "ema20"
            ]
        )

        / x[
            "close"
        ]
    )

    if (
        distance
        <= 0.015
    ):

        tests.append(
            (
                True,
                1,
                "EMA20 pullback",
            )
        )

    score = 0

    reasons = []

    for (
        ok,
        points,
        reason
    ) in tests:

        if ok:

            score += (
                points
            )

            reasons.append(
                reason
            )

    return (
        score,
        reasons
    )


# ============================================================
# ENTRY / SL / TP
# ============================================================

def levels(
    df
):

    x = df.iloc[
        -2
    ]

    entry = float(
        x[
            "close"
        ]
    )

    atr = float(
        x[
            "atr"
        ]
    )

    recent = df.iloc[
        -12:-1
    ]

    swing_low = float(
        recent[
            "low"
        ].min()
    )

    sl = min(

        entry
        - (
            1.5
            * atr
        ),

        swing_low
        - (
            0.2
            * atr
        )
    )

    risk = (
        entry
        - sl
    )

    if risk <= 0:

        raise ValueError(
            "Invalid LONG risk calculation"
        )

    tp1 = (
        entry
        + risk
    )

    tp2 = (
        entry
        + (
            2
            * risk
        )
    )

    tp3 = (
        entry
        + (
            3
            * risk
        )
    )

    return (
        entry,
        sl,
        tp1,
        tp2,
        tp3
    )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def send_signal(
    symbol,
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
        df
    )

    x = df.iloc[
        -2
    ]

    reason_text = (
        "\n".join(
            "• "
            + reason

            for reason
            in reasons
        )
    )

    message = (

        f"🟢 <b>FINAL LONG SIGNAL</b>\n\n"

        f"💎 <b>{symbol}</b>\n"

        f"🤖 Strategy: "
        f"E / {VERSION}\n"

        f"⏱ Entry: 1H | "
        f"Trend: 4H\n\n"

        f"💵 Entry: "
        f"{entry:.6f}\n"

        f"🛑 SL: "
        f"{sl:.6f}\n"

        f"🎯 TP1: "
        f"{tp1:.6f}\n"

        f"🎯 <b>TP2: "
        f"{tp2:.6f} "
        f"← PRIMARY</b>\n"

        f"🎯 TP3: "
        f"{tp3:.6f}\n\n"

        f"⭐ Score: "
        f"{score}/11 "
        f"(required exactly 9)\n"

        f"📊 RSI: "
        f"{x['rsi']:.1f} "
        f"(required 60-70)\n"

        f"📏 ADX: "
        f"{x['adx']:.1f} "
        f"(required ≥40)\n\n"

        f"{reason_text}\n\n"

        f"🧪 Forward-test "
        f"signal only — "
        f"no automatic order."
    )

    return send_message(
        message
    )


# ============================================================
# FINAL FILTER E
# ============================================================

def analyze(
    symbol,
    state
):

    print(
        f"Scanning "
        f"{symbol}..."
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

    if (
        df1 is None
        or df4 is None
    ):

        print(
            "Not enough data:",
            symbol
        )

        return "data_error"

    x = df1.iloc[
        -2
    ]

    trend = trend_4h(
        df4
    )

    (
        score,
        reasons
    ) = score_long(
        df1,
        df4
    )

    print(

        f"{symbol} | "

        f"RSI:"
        f"{x['rsi']:.1f} | "

        f"ADX:"
        f"{x['adx']:.1f} | "

        f"Score:"
        f"{score} | "

        f"Trend:"
        f"{trend}"
    )

    qualifies = (

        trend
        == "BULLISH"

        and x[
            "adx"
        ]
        >= FINAL_MIN_ADX

        and FINAL_MIN_RSI
        <= x[
            "rsi"
        ]
        < FINAL_MAX_RSI

        and score
        == FINAL_SCORE
    )

    if not qualifies:

        print(
            "No Filter-E signal:",
            symbol
        )

        clear_signal_state(
            state,
            symbol
        )

        return "no_signal"

    # Prevent a new signal if an older
    # forward-test trade is still open.

    if has_open_trade(
        symbol,
        "LONG"
    ):

        print(
            "Forward trade still open:",
            symbol
        )

        return "duplicate"

    if is_duplicate_signal(
        state,
        symbol
    ):

        print(
            "Duplicate signal skipped:",
            symbol
        )

        return "duplicate"

    print(
        "NEW Filter-E signal detected:",
        symbol
    )

    sent = send_signal(
        symbol,
        score,
        reasons,
        df1
    )

    if not sent:

        return "telegram_error"

    (
        entry,
        sl,
        tp1,
        tp2,
        tp3
    ) = levels(
        df1
    )

    tracker_saved = record_signal(

        symbol=symbol,

        side="LONG",

        entry=entry,

        sl=sl,

        tp2=tp2,

        signal_timestamp=int(
            x[
                "timestamp"
            ]
        ),

        score=score,

        rsi=float(
            x[
                "rsi"
            ]
        ),

        adx=float(
            x[
                "adx"
            ]
        ),

        strategy_version=VERSION
    )

    print(
        "Forward tracker recorded:",
        tracker_saved
    )

    state[
        symbol
    ] = {

        "side":
            "LONG",

        "entry":
            float(
                entry
            ),

        "sl":
            float(
                sl
            ),

        "tp2":
            float(
                tp2
            ),

        "timestamp":
            int(
                x[
                    "timestamp"
                ]
            ),

        "score":
            int(
                score
            ),

        "rsi":
            float(
                x[
                    "rsi"
                ]
            ),

        "adx":
            float(
                x[
                    "adx"
                ]
            ),

        "version":
            VERSION,
    }

    save_state(
        state
    )

    return "signal"


# ============================================================
# MAIN + HEALTH CHECK + FORWARD TRACKER
# ============================================================

def main():

    print(

        f"AI Swing Trade Scanner "
        f"{VERSION} started"
    )

    print(

        "Filter E: "
        "LONG + ADX>=40 + "
        "RSI 60-70 + "
        "SCORE==9"
    )

    print(
        "Primary target: TP2"
    )

    print(

        "Mode: SIGNAL ONLY / "
        "FORWARD TEST"
    )

    print(
        "Forward tracker: ENABLED"
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

        send_message(

            "🚨 <b>Scanner health error</b>\n"

            "Toobit connection failed.\n"

            f"Version: "
            f"{VERSION}"
        )

        return

    # ========================================================
    # UPDATE EXISTING FORWARD-TEST TRADES
    # ========================================================

    try:

        closed_now = (
            update_open_trades(
                exchange
            )
        )

        for trade in closed_now:

            send_message(
                closed_trade_text(
                    trade
                )
            )

        if closed_now:

            send_message(
                summary_text()
            )

    except Exception as error:

        print(
            "Forward tracker update error:",
            error
        )

    manual_run = (

        os.getenv(
            "GITHUB_EVENT_NAME"
        )

        == "workflow_dispatch"
    )

    if manual_run:

        send_message(

            f"✅ <b>AI Swing Trade Scanner "
            f"{VERSION} started</b>\n"

            "🧪 Mode: Forward Test / "
            "Signal Only\n"

            "🟢 Direction: LONG only\n"

            "📏 ADX: ≥ 40\n"

            "📊 RSI: 60-70\n"

            "⭐ Score: exactly 9\n"

            "🎯 Primary exit: TP2\n"

            "⏱ Analysis: 1H + 4H\n"

            "🔁 Duplicate protection enabled\n"

            "📒 Forward tracker enabled"
        )

    stats = {

        "signal":
            0,

        "duplicate":
            0,

        "no_signal":
            0,

        "data_error":
            0,

        "telegram_error":
            0,
    }

    for symbol in SYMBOLS:

        try:

            result = analyze(
                symbol,
                state
            )

            if result in stats:

                stats[
                    result
                ] += 1

        except Exception as error:

            print(
                "Analysis error:",
                symbol,
                error
            )

            stats[
                "data_error"
            ] += 1

        save_state(
            state
        )

        time.sleep(
            0.5
        )

    print(
        "Active signal states:",
        len(
            state
        )
    )

    print(
        "Scan stats:",
        stats
    )

    print(
        "All scans completed"
    )

    if (
        stats[
            "data_error"
        ]
        >= 5
    ):

        send_message(

            "⚠️ <b>Scanner health warning</b>\n"

            f"Data errors: "
            f"{stats['data_error']} / "
            f"{len(SYMBOLS)}\n"

            f"Version: "
            f"{VERSION}"
        )

    if manual_run:

        send_message(

            "✅ <b>Manual scan completed</b>\n"

            f"New signals: "
            f"{stats['signal']}\n"

            f"Duplicates skipped: "
            f"{stats['duplicate']}\n"

            f"Data errors: "
            f"{stats['data_error']}\n"

            f"Active signal states: "
            f"{len(state)}"
        )

        send_message(
            summary_text()
        )


if __name__ == "__main__":
    main()
