import os
import json
import math
from datetime import datetime, timezone


# ============================================================
# AI TRADE SCANNER - FORWARD TEST TRACKER
# Tracks real forward-test signals independently from strategy.
#
# Primary result:
# LONG -> TP2 (+2R) or SL (-1R)
#
# Also:
# - maximum hold = 72 hours
# - conservative SL-first rule if SL and TP2
#   are touched inside the same 1H candle
# - 0.18% assumed round-trip trading cost
# - calculates WR / PF / Net R / Avg R / Drawdown
# ============================================================


VERSION = "FORWARD-TRACKER-V1"

FORWARD_FILE = "forward_test.json"

TIMEFRAME = "1h"

MAX_HOLD_HOURS = 72

ROUND_TRIP_COST_PCT = 0.0018

RISK_PER_TRADE = 0.01

ONE_HOUR_MS = 60 * 60 * 1000


# ============================================================
# HELPERS
# ============================================================

def utc_text(timestamp_ms):

    try:

        return datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=timezone.utc
        ).isoformat()

    except Exception:

        return ""


def new_book():

    return {
        "version": VERSION,
        "open": [],
        "closed": []
    }


# ============================================================
# LOAD / SAVE
# ============================================================

def load_book():

    if not os.path.exists(
        FORWARD_FILE
    ):

        return new_book()

    try:

        with open(
            FORWARD_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            book = json.load(f)

        if not isinstance(
            book,
            dict
        ):

            return new_book()

        book.setdefault(
            "version",
            VERSION
        )

        book.setdefault(
            "open",
            []
        )

        book.setdefault(
            "closed",
            []
        )

        return book

    except Exception as error:

        print(
            "Forward tracker load error:",
            error
        )

        return new_book()


def save_book(book):

    try:

        temp_file = (
            FORWARD_FILE
            + ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                book,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            FORWARD_FILE
        )

        return True

    except Exception as error:

        print(
            "Forward tracker save error:",
            error
        )

        return False


# ============================================================
# OPEN TRADE CHECK
# ============================================================

def has_open_trade(
    symbol,
    side="LONG"
):

    book = load_book()

    for trade in book["open"]:

        if (
            trade.get("symbol")
            == symbol

            and trade.get("side")
            == side
        ):

            return True

    return False


# ============================================================
# RECORD NEW SIGNAL
# ============================================================

def record_signal(
    symbol,
    side,
    entry,
    sl,
    tp2,
    signal_timestamp,
    score=None,
    rsi=None,
    adx=None,
    strategy_version=None
):

    book = load_book()

    trade_id = (
        f"{symbol}|"
        f"{side}|"
        f"{int(signal_timestamp)}"
    )

    all_trades = (
        book["open"]
        + book["closed"]
    )

    for trade in all_trades:

        if (
            trade.get("id")
            == trade_id
        ):

            print(
                "Forward trade already recorded:",
                trade_id
            )

            return False

    risk = abs(
        float(entry)
        - float(sl)
    )

    if risk <= 0:

        print(
            "Invalid forward-test risk:",
            symbol
        )

        return False

    trade = {

        "id":
            trade_id,

        "symbol":
            symbol,

        "side":
            side,

        "entry":
            float(entry),

        "sl":
            float(sl),

        "tp2":
            float(tp2),

        "risk":
            float(risk),

        "signal_timestamp":
            int(signal_timestamp),

        "signal_time_utc":
            utc_text(
                int(signal_timestamp)
            ),

        "score":
            (
                int(score)
                if score is not None
                else None
            ),

        "rsi":
            (
                float(rsi)
                if rsi is not None
                else None
            ),

        "adx":
            (
                float(adx)
                if adx is not None
                else None
            ),

        "strategy_version":
            strategy_version,

        "status":
            "OPEN"
    }

    book["open"].append(
        trade
    )

    save_book(
        book
    )

    print(
        "Forward trade recorded:",
        symbol,
        side
    )

    return True


# ============================================================
# CALCULATE NET R
# ============================================================

def net_r_after_cost(
    trade,
    raw_r
):

    risk = float(
        trade["risk"]
    )

    entry = float(
        trade["entry"]
    )

    if risk <= 0:

        return float(
            raw_r
        )

    cost_r = (

        entry
        * ROUND_TRIP_COST_PCT

    ) / risk

    return float(
        raw_r - cost_r
    )


# ============================================================
# CLOSE TRADE
# ============================================================

def close_trade(
    trade,
    result,
    raw_r,
    exit_price,
    exit_timestamp
):

    trade = dict(
        trade
    )

    trade["status"] = (
        "CLOSED"
    )

    trade["result"] = (
        result
    )

    trade["raw_r"] = float(
        raw_r
    )

    trade["net_r"] = (
        net_r_after_cost(
            trade,
            raw_r
        )
    )

    trade["exit_price"] = float(
        exit_price
    )

    trade["exit_timestamp"] = int(
        exit_timestamp
    )

    trade["exit_time_utc"] = (
        utc_text(
            int(exit_timestamp)
        )
    )

    return trade


# ============================================================
# EVALUATE ONE OPEN LONG
# ============================================================

def evaluate_long(
    exchange,
    trade
):

    signal_timestamp = int(
        trade[
            "signal_timestamp"
        ]
    )

    since = (
        signal_timestamp
        + ONE_HOUR_MS
    )

    try:

        candles = exchange.fetch_ohlcv(
            trade["symbol"],
            timeframe=TIMEFRAME,
            since=since,
            limit=100
        )

    except Exception as error:

        print(
            "Forward fetch error:",
            trade["symbol"],
            error
        )

        return None

    if not candles:

        return None

    entry = float(
        trade["entry"]
    )

    sl = float(
        trade["sl"]
    )

    tp2 = float(
        trade["tp2"]
    )

    risk = float(
        trade["risk"]
    )

    valid_bars = [

        bar

        for bar in candles

        if int(bar[0])
        > signal_timestamp
    ]

    if not valid_bars:

        return None

    for index, bar in enumerate(
        valid_bars
    ):

        timestamp = int(
            bar[0]
        )

        high = float(
            bar[2]
        )

        low = float(
            bar[3]
        )

        close = float(
            bar[4]
        )

        hit_sl = (
            low <= sl
        )

        hit_tp2 = (
            high >= tp2
        )

        # Conservative rule:
        # if both levels are hit
        # inside the same 1H candle,
        # SL counts first.

        if (
            hit_sl
            and hit_tp2
        ):

            return close_trade(
                trade,
                "SL_FIRST",
                -1.0,
                sl,
                timestamp
            )

        if hit_sl:

            return close_trade(
                trade,
                "SL",
                -1.0,
                sl,
                timestamp
            )

        if hit_tp2:

            return close_trade(
                trade,
                "TP2",
                2.0,
                tp2,
                timestamp
            )

        # 72 completed 1H bars
        if (
            index + 1
            >= MAX_HOLD_HOURS
        ):

            raw_r = (

                close
                - entry

            ) / risk

            return close_trade(
                trade,
                "TIME",
                raw_r,
                close,
                timestamp
            )

    return None


# ============================================================
# UPDATE ALL OPEN TRADES
# ============================================================

def update_open_trades(
    exchange
):

    book = load_book()

    still_open = []

    closed_now = []

    for trade in book["open"]:

        side = trade.get(
            "side"
        )

        if side != "LONG":

            still_open.append(
                trade
            )

            continue

        result = evaluate_long(
            exchange,
            trade
        )

        if result is None:

            still_open.append(
                trade
            )

            continue

        closed_now.append(
            result
        )

        book["closed"].append(
            result
        )

        print(
            "Forward trade closed:",
            result["symbol"],
            result["result"],
            f"{result['net_r']:.3f}R"
        )

    book["open"] = (
        still_open
    )

    save_book(
        book
    )

    return closed_now


# ============================================================
# METRICS
# ============================================================

def metrics(
    book=None
):

    if book is None:

        book = load_book()

    closed = book.get(
        "closed",
        []
    )

    if not closed:

        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "net_r": 0.0,
            "avg_r": 0.0,
            "max_drawdown": 0.0,
            "open": len(
                book.get(
                    "open",
                    []
                )
            )
        }

    r_values = [

        float(
            trade.get(
                "net_r",
                0
            )
        )

        for trade in closed
    ]

    wins = sum(
        1
        for r in r_values
        if r > 0
    )

    losses = (
        len(r_values)
        - wins
    )

    positive_r = sum(
        r
        for r in r_values
        if r > 0
    )

    negative_r = abs(
        sum(
            r
            for r in r_values
            if r < 0
        )
    )

    if negative_r > 0:

        pf = (
            positive_r
            / negative_r
        )

    elif positive_r > 0:

        pf = math.inf

    else:

        pf = 0.0

    net_r = sum(
        r_values
    )

    avg_r = (
        net_r
        / len(r_values)
    )

    # Equity simulation:
    # each 1R = 1% account risk.

    equity = 100.0

    peak = equity

    max_dd = 0.0

    for r in r_values:

        equity *= (
            1
            + (
                RISK_PER_TRADE
                * r
            )
        )

        if equity > peak:

            peak = equity

        if peak > 0:

            drawdown = (

                peak
                - equity

            ) / peak * 100

            max_dd = max(
                max_dd,
                drawdown
            )

    return {

        "trades":
            len(r_values),

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            (
                wins
                / len(r_values)
                * 100
            ),

        "profit_factor":
            pf,

        "net_r":
            net_r,

        "avg_r":
            avg_r,

        "max_drawdown":
            max_dd,

        "open":
            len(
                book.get(
                    "open",
                    []
                )
            )
    }


# ============================================================
# SUMMARY TEXT
# ============================================================

def summary_text():

    m = metrics()

    pf = m[
        "profit_factor"
    ]

    if math.isinf(
        pf
    ):

        pf_text = "INF"

    else:

        pf_text = (
            f"{pf:.2f}"
        )

    return (
        "📒 <b>FORWARD TEST STATS</b>\n\n"

        f"Closed trades: {m['trades']}\n"
        f"Open trades: {m['open']}\n"

        f"Wins: {m['wins']}\n"
        f"Losses: {m['losses']}\n"

        f"Win rate: "
        f"{m['win_rate']:.2f}%\n"

        f"Profit factor: "
        f"{pf_text}\n"

        f"Net R: "
        f"{m['net_r']:+.2f}R\n"

        f"Avg R: "
        f"{m['avg_r']:+.3f}R\n"

        f"Max drawdown: "
        f"{m['max_drawdown']:.2f}%"
    )


# ============================================================
# CLOSED TRADE TELEGRAM TEXT
# ============================================================

def closed_trade_text(
    trade
):

    result = trade.get(
        "result",
        "UNKNOWN"
    )

    if result == "TP2":

        icon = "✅"

    elif result in (
        "SL",
        "SL_FIRST"
    ):

        icon = "❌"

    else:

        icon = "⏱"

    return (
        f"{icon} <b>FORWARD RESULT</b>\n\n"

        f"💎 {trade['symbol']}\n"

        f"Side: {trade['side']}\n"

        f"Result: {result}\n"

        f"Entry: "
        f"{trade['entry']:.6f}\n"

        f"Exit: "
        f"{trade['exit_price']:.6f}\n"

        f"Net: "
        f"{trade['net_r']:+.3f}R"
    )


if __name__ == "__main__":

    print(
        summary_text()
      )
