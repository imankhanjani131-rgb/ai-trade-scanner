import json
import os
import time

import main as base

VERSION = "V4.0-EARLY"
STATE_FILE = "v4_signal_state.json"

TRIGGER_TF = "15m"
SETUP_TF = "1h"
TREND_TF = "4h"

EARLY_MIN_SCORE = 6
FINAL_MIN_SCORE = 8

EARLY_COOLDOWN_MS = 4 * 60 * 60 * 1000
FINAL_COOLDOWN_MS = 8 * 60 * 60 * 1000


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

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


def cooldown_ok(
    state,
    symbol,
    kind,
    now_ms
):
    row = state.get(
        symbol,
        {}
    )

    last = int(
        row.get(
            f"last_{kind}_ms",
            0
        )
        or 0
    )

    if kind == "early":
        cooldown = EARLY_COOLDOWN_MS
    else:
        cooldown = FINAL_COOLDOWN_MS

    return (
        now_ms - last
        >= cooldown
    )


def mark_sent(
    state,
    symbol,
    kind,
    now_ms
):
    state.setdefault(
        symbol,
        {}
    )

    state[
        symbol
    ][
        f"last_{kind}_ms"
    ] = int(
        now_ms
    )

    save_state(
        state
    )


def v4_score(
    df15,
    df1,
    df4
):
    x15 = df15.iloc[-2]
    p15 = df15.iloc[-3]

    x1 = df1.iloc[-2]
    p1 = df1.iloc[-3]

    trend = base.trend_4h(
        df4
    )

    atr15 = max(
        float(
            x15["atr"]
        ),
        1e-12
    )

    pullback = (
        float(
            x15["low"]
        )
        <=
        float(
            x15["ema20"]
        )
        + (
            0.25
            * atr15
        )

        and

        float(
            x15["close"]
        )
        >
        float(
            x15["ema20"]
        )
    )

    reclaim = (
        float(
            p15["close"]
        )
        <=
        float(
            p15["ema20"]
        )

        and

        float(
            x15["close"]
        )
        >
        float(
            x15["ema20"]
        )
    )

    momentum_rising = (
        float(
            x15["macd_hist"]
        )
        >
        float(
            p15["macd_hist"]
        )
    )

    adx_healthy = (
        float(
            x1["adx"]
        )
        >= 20

        and

        float(
            x1["adx"]
        )
        >=
        float(
            p1["adx"]
        )
        - 1.5
    )

    distance_atr = (
        float(
            x15["close"]
        )
        -
        float(
            x15["ema20"]
        )
    ) / atr15

    four_bars_ago = (
        df15.iloc[-6]
    )

    impulse_atr = max(
        0.0,
        (
            float(
                x15["close"]
            )
            -
            float(
                four_bars_ago[
                    "close"
                ]
            )
        )
        / atr15
    )

    overextended = (
        distance_atr
        > 1.25

        or

        impulse_atr
        > 2.50

        or

        float(
            x15["rsi"]
        )
        >= 69
    )

    tests = [

        (
            trend
            == "BULLISH",
            2,
            "4H bullish"
        ),

        (
            float(
                x1["close"]
            )
            >
            float(
                x1["ema50"]
            ),
            1,
            "1H above EMA50"
        ),

        (
            float(
                x1["ema20"]
            )
            >
            float(
                x1["ema50"]
            ),
            1,
            "1H EMA bullish"
        ),

        (
            48
            <=
            float(
                x1["rsi"]
            )
            < 68,
            1,
            f"1H RSI {x1['rsi']:.1f}"
        ),

        (
            adx_healthy,
            1,
            f"1H ADX {x1['adx']:.1f}"
        ),

        (
            float(
                x15["close"]
            )
            >
            float(
                x15["ema20"]
            ),
            1,
            "15m above EMA20"
        ),

        (
            pullback
            or reclaim,
            1,
            "15m pullback/reclaim"
        ),

        (
            momentum_rising,
            1,
            "15m momentum rising"
        ),

        (
            float(
                x15["vol_ratio"]
            )
            >= 0.70,
            1,
            "15m volume confirmed"
        ),
    ]

    score = 0
    reasons = []

    for (
        ok,
        points,
        reason
    ) in tests:

        if ok:
            score += points
            reasons.append(
                reason
            )

    flags = {

        "trend":
            trend,

        "pullback":
            pullback,

        "reclaim":
            reclaim,

        "momentum_rising":
            momentum_rising,

        "overextended":
            overextended,

        "distance_atr":
            distance_atr,

        "impulse_atr":
            impulse_atr,

        "rsi15":
            float(
                x15["rsi"]
            ),

        "rsi1":
            float(
                x1["rsi"]
            ),

        "adx1":
            float(
                x1["adx"]
            ),
    }

    return (
        score,
        reasons,
        flags
    )


def nearest_resistance(
    df1,
    entry
):
    highs = (
        df1["high"]
        .astype(float)
        .tolist()
    )

    pivots = []

    start = max(
        2,
        len(highs) - 45
    )

    end = (
        len(highs)
        - 2
    )

    for i in range(
        start,
        end
    ):

        high = highs[i]

        if (
            high
            > highs[i - 1]

            and

            high
            >= highs[i - 2]

            and

            high
            > highs[i + 1]

            and

            high
            >= highs[i + 2]

            and

            high
            > entry
        ):
            pivots.append(
                high
            )

    if pivots:
        return min(
            pivots
        )

    return None


def levels_v4(
    df15,
    df1
):
    x = df15.iloc[-2]

    entry = float(
        x["close"]
    )

    atr = float(
        x["atr"]
    )

    recent = (
        df15.iloc[
            -18:-2
        ]
    )

    swing_low = float(
        recent[
            "low"
        ].min()
    )

    sl = min(

        swing_low
        -
        (
            0.10
            * atr
        ),

        entry
        -
        (
            0.80
            * atr
        )
    )

    risk = (
        entry
        - sl
    )

    if risk <= 0:
        raise ValueError(
            "Invalid V4 risk"
        )

    if (
        risk
        >
        2.20
        * atr
    ):
        raise ValueError(
            "Stop too wide"
        )

    resistance = (
        nearest_resistance(
            df1,
            entry
        )
    )

    if (
        resistance
        is not None

        and

        resistance
        - entry
        <
        0.65
        * risk
    ):
        raise ValueError(
            "Resistance too close"
        )

    tp1 = (
        entry
        +
        1.00
        * risk
    )

    if (
        resistance
        is not None

        and

        resistance
        < tp1
    ):
        tp1 = (
            resistance
            * 0.998
        )

    tp2 = (
        entry
        +
        1.50
        * risk
    )

    tp3 = (
        entry
        +
        2.20
        * risk
    )

    return (
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        resistance
    )


def send_early(
    symbol,
    score,
    flags,
    reasons
):
    reason_text = "\n".join(
        "• " + reason

        for reason
        in reasons[-5:]
    )

    message = (

        "🟡 <b>V4 EARLY WATCH — NOT ENTRY</b>\n\n"

        f"💎 <b>{symbol}</b>\n"

        f"🤖 {VERSION}\n"

        "⏱ Trigger: 15m | Setup: 1H | Trend: 4H\n\n"

        f"⭐ Score: {score}/10\n"

        f"📊 1H RSI: "
        f"{flags['rsi1']:.1f}\n"

        f"📏 1H ADX: "
        f"{flags['adx1']:.1f}\n"

        f"📐 EMA20 distance: "
        f"{flags['distance_atr']:.2f} ATR\n\n"

        f"{reason_text}\n\n"

        "⏳ Setup forming. Wait for FINAL signal.\n"

        "🧪 Forward-test only."
    )

    return base.send_message(
        message
    )


def send_final(
    symbol,
    score,
    flags,
    reasons,
    df15,
    df1
):
    (
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        resistance
    ) = levels_v4(
        df15,
        df1
    )

    risk = (
        entry
        - sl
    )

    be_trigger = (
        entry
        +
        0.70
        * risk
    )

    reason_text = "\n".join(
        "• " + reason

        for reason
        in reasons
    )

    if resistance is not None:
        resistance_text = (
            f"{resistance:.6f}"
        )
    else:
        resistance_text = (
            "none nearby"
        )

    message = (

        "🟢 <b>V4 FINAL LONG SIGNAL</b>\n\n"

        f"💎 <b>{symbol}</b>\n"

        f"🤖 {VERSION}\n"

        "⏱ Trigger: 15m | Setup: 1H | Trend: 4H\n\n"

        f"💵 Entry: "
        f"{entry:.6f}\n"

        f"🛑 SL: "
        f"{sl:.6f}\n"

        f"🎯 TP1: "
        f"{tp1:.6f}\n"

        f"🎯 <b>TP2: "
        f"{tp2:.6f} ← PRIMARY</b>\n"

        f"🎯 TP3: "
        f"{tp3:.6f}\n"

        f"🧱 Resistance: "
        f"{resistance_text}\n\n"

        f"⭐ Score: "
        f"{score}/10 "
        f"(required ≥8)\n"

        f"📊 1H RSI: "
        f"{flags['rsi1']:.1f}\n"

        f"📏 1H ADX: "
        f"{flags['adx1']:.1f}\n"

        f"📐 EMA20 distance: "
        f"{flags['distance_atr']:.2f} ATR\n\n"

        f"{reason_text}\n\n"

        f"🔒 Profit protection: "
        f"at {be_trigger:.6f} (+0.7R), "
        "move SL toward break-even.\n"

        "💰 At TP1, consider taking partial profit.\n"

        "🧪 Forward-test only — no automatic order."
    )

    return base.send_message(
        message
    )


def analyze(
    symbol,
    state
):
    print(
        f"V4 scanning "
        f"{symbol}..."
    )

    df15 = base.indicators(
        base.fetch_data(
            symbol,
            TRIGGER_TF
        )
    )

    df1 = base.indicators(
        base.fetch_data(
            symbol,
            SETUP_TF
        )
    )

    df4 = base.indicators(
        base.fetch_data(
            symbol,
            TREND_TF
        )
    )

    if (
        df15 is None
        or df1 is None
        or df4 is None
    ):
        return "data_error"

    x15 = df15.iloc[-2]

    now_ms = int(
        x15["timestamp"]
    )

    (
        score,
        reasons,
        flags
    ) = v4_score(
        df15,
        df1,
        df4
    )

    print(

        f"{symbol} | "

        f"score="
        f"{score}/10 | "

        f"trend="
        f"{flags['trend']} | "

        f"rsi1="
        f"{flags['rsi1']:.1f} | "

        f"adx1="
        f"{flags['adx1']:.1f} | "

        f"dist="
        f"{flags['distance_atr']:.2f}ATR | "

        f"chase="
        f"{flags['overextended']}"
    )

    mandatory = (

        flags[
            "trend"
        ]
        == "BULLISH"

        and

        not flags[
            "overextended"
        ]

        and

        48
        <= flags[
            "rsi1"
        ]
        < 68

        and

        flags[
            "adx1"
        ]
        >= 20
    )

    final_ok = (

        mandatory

        and

        score
        >= FINAL_MIN_SCORE

        and

        (
            flags[
                "pullback"
            ]

            or

            flags[
                "reclaim"
            ]
        )

        and

        flags[
            "momentum_rising"
        ]
    )

    if (
        final_ok

        and

        cooldown_ok(
            state,
            symbol,
            "final",
            now_ms
        )
    ):

        try:

            sent = send_final(
                symbol,
                score,
                flags,
                reasons,
                df15,
                df1
            )

        except ValueError as error:

            print(
                f"V4 blocked "
                f"{symbol}: "
                f"{error}"
            )

            sent = False

        if sent:

            mark_sent(
                state,
                symbol,
                "final",
                now_ms
            )

            return "final"

    early_ok = (

        mandatory

        and

        score
        >= EARLY_MIN_SCORE
    )

    if (
        early_ok

        and

        cooldown_ok(
            state,
            symbol,
            "early",
            now_ms
        )
    ):

        sent = send_early(
            symbol,
            score,
            flags,
            reasons
        )

        if sent:

            mark_sent(
                state,
                symbol,
                "early",
                now_ms
            )

            return "early"

    return "no_signal"


def main():

    print(
        f"AI Trade Scanner "
        f"{VERSION} started"
    )

    print(
        "15m trigger + "
        "1H setup + "
        "4H trend"
    )

    print(
        "Anti-chase + "
        "early watch + "
        "pullback/reclaim"
    )

    state = load_state()

    try:

        base.exchange.load_markets()

        print(
            "Toobit connected"
        )

    except Exception as error:

        print(
            "Toobit error:",
            error
        )

        base.send_message(
            f"🚨 V4 Toobit "
            f"connection error: "
            f"{error}"
        )

        return

    stats = {

        "final": 0,

        "early": 0,

        "no_signal": 0,

        "data_error": 0,
    }

    for symbol in base.SYMBOLS:

        try:

            result = analyze(
                symbol,
                state
            )

        except Exception as error:

            print(
                "V4 analysis error:",
                symbol,
                error
            )

            result = (
                "data_error"
            )

        if result in stats:

            stats[
                result
            ] += 1

        time.sleep(
            0.4
        )

    save_state(
        state
    )

    print(
        "V4 stats:",
        stats
    )

    print(
        "V4 scan completed"
    )


if __name__ == "__main__":
    main()
