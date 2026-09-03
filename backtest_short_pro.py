import math
from collections import Counter, defaultdict

import pandas as pd
import backtest as bt


# ============================================================
# AI TRADE SCANNER - SHORT PRO V1
#
# Professional independent SHORT discovery engine.
#
# IMPORTANT:
# - LONG main.py is NOT changed.
# - Uses existing OKX historical engine from backtest.py.
# - 1H entries + 4H market regime.
# - Conservative SL-first intrabar handling.
# - Fees/slippage inherited from backtest.py.
# - Tests several genuinely different SHORT entry models.
# - Tests TP 1.5R and TP 2R.
# - Full-year + older + recent + 4-block validation.
# - Checks diversification across symbols.
# - Rejects weak/overfit setups automatically.
# ============================================================


VERSION = "SHORT-PRO-V1"

DAYS = bt.DAYS
RECENT_DAYS = 90
LAST30_DAYS = 30

MAX_HOLD_HOURS = 72
COOLDOWN_BARS = 3

TARGETS = (
    1.5,
    2.0,
)

# Strict approval rules
MIN_FULL_TRADES = 50
MIN_RECENT_TRADES = 10

MAX_FULL_DD = 30.0

MIN_SYMBOLS_USED = 8
MAX_TOP_SYMBOL_SHARE = 0.30


# ============================================================
# HELPERS
# ============================================================


def safe_pf(metrics):

    if not metrics:
        return 0.0

    value = metrics["pf"]

    if math.isinf(value):
        return 99.0

    return float(value)


def print_metrics(
    label,
    metrics
):

    if metrics is None:

        print(
            f"{label} | NO TRADES"
        )

        return

    print(
        f"{label} | "
        f'Trades:{metrics["trades"]} | '
        f'WR:{metrics["win_rate"]:.2f}% | '
        f'PF:{bt.pf_text(metrics["pf"])} | '
        f'NetR:{metrics["net_r"]:.2f}R | '
        f'AvgR:{metrics["avg_r"]:.3f}R | '
        f'DD:{metrics["max_dd"]:.2f}%'
    )


def slice_results(
    results,
    start=None,
    end=None
):

    rows = results

    if start is not None:

        rows = [
            row
            for row in rows
            if row["time"] >= start
        ]

    if end is not None:

        rows = [
            row
            for row in rows
            if row["time"] < end
        ]

    return rows


def frequency(
    metrics
):

    if not metrics:

        return {
            "year": 0,
            "month": 0.0,
            "week": 0.0,
            "day": 0.0,
        }

    trades = metrics[
        "trades"
    ]

    return {
        "year":
            trades,

        "month":
            trades / 12.0,

        "week":
            trades / 52.14,

        "day":
            trades / 365.0,
    }


# ============================================================
# 4H MARKET REGIMES
# ============================================================


def strict_bearish_4h(
    x
):

    return (

        x["close4"]
        < x["ema200_4"]

        and x["ema20_4"]
        < x["ema50_4"]

        and x["ema50_4"]
        < x["ema200_4"]

        and x["rsi_4"]
        <= 50
    )


def bearish_bias_4h(
    x
):

    return (

        x["close4"]
        < x["ema50_4"]

        and x["ema20_4"]
        < x["ema50_4"]

        and x["rsi_4"]
        <= 52
    )


# ============================================================
# SHORT SL ENGINE
# ============================================================


def short_levels(
    df,
    i
):

    x = df.iloc[
        i
    ]

    recent = df.iloc[
        max(
            0,
            i - 12
        ):
        i + 1
    ]

    entry = float(
        x["close"]
    )

    atr = float(
        x["atr"]
    )

    swing_high = float(
        recent[
            "high"
        ].max()
    )

    sl = max(

        entry
        + (
            1.5
            * atr
        ),

        swing_high
        + (
            0.2
            * atr
        )
    )

    risk = (
        sl
        - entry
    )

    if risk <= 0:
        return None

    return (
        entry,
        sl,
        risk
    )


# ============================================================
# BUILD SHORT FEATURES
# ============================================================


def build_candidate(
    symbol,
    df,
    i
):

    x = df.iloc[
        i
    ]

    p = df.iloc[
        i - 1
    ]

    prior12 = df.iloc[
        max(
            0,
            i - 12
        ):
        i
    ]

    if len(
        prior12
    ) < 8:

        return None

    levels = short_levels(
        df,
        i
    )

    if levels is None:
        return None

    (
        entry,
        sl,
        risk
    ) = levels

    prior_low = float(
        prior12[
            "low"
        ].min()
    )

    bearish_candle = (

        x["close"]
        < x["open"]
    )

    ema_bear = (

        x["ema20"]
        < x["ema50"]

        and x["close"]
        < x["ema50"]
    )

    macd_bear = (

        x["macd"]
        < x["macd_signal"]
    )

    momentum_down = (

        x["macd_hist"]
        < p["macd_hist"]
    )

    # Type 1:
    # support breakdown

    breakdown = (

        x["close"]
        < prior_low
    )

    # Type 2:
    # pullback to EMA20
    # followed by bearish rejection

    ema_touch = (

        x["high"]
        >= (
            x["ema20"]
            * 0.997
        )
    )

    ema_reject = (

        ema_touch

        and x["close"]
        < x["ema20"]

        and bearish_candle
    )

    # Type 3:
    # failed recovery above EMA20

    cross_down = (

        p["close"]
        >= p["ema20"]

        and x["close"]
        < x["ema20"]

        and bearish_candle
    )

    # Type 4:
    # momentum continuation

    momentum = (

        ema_bear

        and macd_bear

        and momentum_down

        and x["close"]
        < x["ema20"]
    )

    trigger_count = sum([
        breakdown,
        ema_reject,
        cross_down,
        momentum,
    ])

    # Avoid chasing deeply oversold moves.

    not_deep_oversold = (

        x["rsi"]
        >= 27
    )

    return {

        "symbol":
            symbol,

        "i":
            i,

        "time":
            x["signal_time"],

        "entry":
            entry,

        "sl":
            sl,

        "risk":
            risk,

        "strict4":
            strict_bearish_4h(
                x
            ),

        "bias4":
            bearish_bias_4h(
                x
            ),

        "breakdown":
            bool(
                breakdown
            ),

        "ema_reject":
            bool(
                ema_reject
            ),

        "cross_down":
            bool(
                cross_down
            ),

        "momentum":
            bool(
                momentum
            ),

        "trigger_count":
            int(
                trigger_count
            ),

        "bearish_candle":
            bool(
                bearish_candle
            ),

        "ema_bear":
            bool(
                ema_bear
            ),

        "macd_bear":
            bool(
                macd_bear
            ),

        "momentum_down":
            bool(
                momentum_down
            ),

        "not_deep_oversold":
            bool(
                not_deep_oversold
            ),

        "rsi":
            float(
                x["rsi"]
            ),

        "rsi4":
            float(
                x["rsi_4"]
            ),

        "adx":
            float(
                x["adx"]
            ),

        "vol_ratio":
            float(
                x["vol_ratio"]
            ),
    }


def find_pro_candidates(
    symbol,
    df
):

    candidates = []

    for i in range(
        20,
        len(df) - 1
    ):

        trade = build_candidate(
            symbol,
            df,
            i
        )

        if trade is None:
            continue

        if (
            trade[
                "trigger_count"
            ]
            == 0
        ):

            continue

        candidates.append(
            trade
        )

    return candidates


# ============================================================
# PROFESSIONAL SHORT MODELS
#
# Intentionally limited number of models.
# We do NOT brute-force hundreds of parameter combinations.
# ============================================================


def setups():

    return [

        # ----------------------------------------------------
        # P1
        # Strong 4H downtrend +
        # fresh support breakdown
        # ----------------------------------------------------

        {
            "name":
                "P1 STRICT BREAKDOWN",

            "condition":
                lambda t: (

                    t["strict4"]

                    and t[
                        "breakdown"
                    ]

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 25

                    and 30
                    <= t["rsi"]
                    <= 55

                    and t[
                        "vol_ratio"
                    ]
                    >= 0.80
                ),
        },

        # ----------------------------------------------------
        # P2
        # Pullback into EMA
        # then bearish rejection
        # ----------------------------------------------------

        {
            "name":
                "P2 STRICT EMA REJECTION",

            "condition":
                lambda t: (

                    t["strict4"]

                    and t[
                        "ema_reject"
                    ]

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 22

                    and 35
                    <= t["rsi"]
                    <= 60

                    and t[
                        "not_deep_oversold"
                    ]
                ),
        },

        # ----------------------------------------------------
        # P3
        # Trend continuation
        # ----------------------------------------------------

        {
            "name":
                "P3 STRICT MOMENTUM",

            "condition":
                lambda t: (

                    t["strict4"]

                    and t[
                        "momentum"
                    ]

                    and t["adx"]
                    >= 28

                    and 30
                    <= t["rsi"]
                    <= 52

                    and t[
                        "vol_ratio"
                    ]
                    >= 0.80
                ),
        },

        # ----------------------------------------------------
        # P4
        # Wider bearish regime
        # but needs stronger volume
        # ----------------------------------------------------

        {
            "name":
                "P4 BIAS BREAKDOWN + VOLUME",

            "condition":
                lambda t: (

                    t["bias4"]

                    and t[
                        "breakdown"
                    ]

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 30

                    and 30
                    <= t["rsi"]
                    <= 55

                    and t[
                        "vol_ratio"
                    ]
                    >= 1.00
                ),
        },

        # ----------------------------------------------------
        # P5
        # Pullback rejection
        # under broader bearish regime
        # ----------------------------------------------------

        {
            "name":
                "P5 BIAS PULLBACK REJECTION",

            "condition":
                lambda t: (

                    t["bias4"]

                    and t[
                        "ema_reject"
                    ]

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t[
                        "momentum_down"
                    ]

                    and t["adx"]
                    >= 25

                    and 38
                    <= t["rsi"]
                    <= 60

                    and t[
                        "not_deep_oversold"
                    ]
                ),
        },

        # ----------------------------------------------------
        # P6
        # At least two independent
        # bearish triggers agree
        # ----------------------------------------------------

        {
            "name":
                "P6 STRICT ENSEMBLE 2+",

            "condition":
                lambda t: (

                    t["strict4"]

                    and t[
                        "trigger_count"
                    ]
                    >= 2

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 25

                    and 30
                    <= t["rsi"]
                    <= 56

                    and t[
                        "not_deep_oversold"
                    ]
                ),
        },

        # ----------------------------------------------------
        # P7
        # EMA20 loss after attempted recovery
        # ----------------------------------------------------

        {
            "name":
                "P7 BIAS CROSSDOWN",

            "condition":
                lambda t: (

                    t["bias4"]

                    and t[
                        "cross_down"
                    ]

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 27

                    and 35
                    <= t["rsi"]
                    <= 58

                    and t[
                        "vol_ratio"
                    ]
                    >= 0.75
                ),
        },

        # ----------------------------------------------------
        # P8
        # Balanced multi-trigger model
        # ----------------------------------------------------

        {
            "name":
                "P8 STRICT BALANCED",

            "condition":
                lambda t: (

                    t["strict4"]

                    and (

                        t[
                            "breakdown"
                        ]

                        or t[
                            "ema_reject"
                        ]

                        or t[
                            "cross_down"
                        ]
                    )

                    and t[
                        "ema_bear"
                    ]

                    and t[
                        "macd_bear"
                    ]

                    and t["adx"]
                    >= 24

                    and 32
                    <= t["rsi"]
                    <= 58

                    and t[
                        "vol_ratio"
                    ]
                    >= 0.75

                    and t[
                        "not_deep_oversold"
                    ]
                ),
        },
    ]


# ============================================================
# SHORT TRADE SIMULATION
# ============================================================


def simulate_short(
    df,
    trade,
    target_r
):

    entry = trade[
        "entry"
    ]

    sl = trade[
        "sl"
    ]

    risk = trade[
        "risk"
    ]

    tp = (

        entry
        - target_r
        * risk
    )

    start_i = (
        trade["i"]
        + 1
    )

    end_i = min(

        len(df) - 1,

        trade["i"]
        + MAX_HOLD_HOURS
    )

    raw_r = None

    exit_i = end_i

    reason = "TIME"

    for j in range(
        start_i,
        end_i + 1
    ):

        bar = df.iloc[
            j
        ]

        hit_sl = (

            float(
                bar["high"]
            )
            >= sl
        )

        hit_tp = (

            float(
                bar["low"]
            )
            <= tp
        )

        # Conservative:
        # if TP and SL touch in same candle,
        # count SL first.

        if (
            hit_sl
            and hit_tp
        ):

            raw_r = -1.0

            exit_i = j

            reason = (
                "SL_FIRST"
            )

            break

        if hit_sl:

            raw_r = -1.0

            exit_i = j

            reason = "SL"

            break

        if hit_tp:

            raw_r = float(
                target_r
            )

            exit_i = j

            reason = (
                f"TP{target_r:g}R"
            )

            break

    # Time exit after 72 hours.

    if raw_r is None:

        exit_price = float(
            df.iloc[
                end_i
            ][
                "close"
            ]
        )

        raw_r = (

            entry
            - exit_price

        ) / risk

    # Same fee + slippage assumption
    # used by the existing backtester.

    cost_r = (

        entry
        * bt.ROUND_TRIP_COST_PCT

    ) / risk

    net_r = (

        raw_r
        - cost_r
    )

    return (
        float(
            net_r
        ),
        exit_i,
        reason
    )


# ============================================================
# RUN ONE MODEL
# ============================================================


def run_setup(
    candidates,
    data,
    condition,
    target_r
):

    results = []

    blocked_until = {}

    for trade in candidates:

        if not condition(
            trade
        ):

            continue

        symbol = trade[
            "symbol"
        ]

        # No overlapping SHORT positions
        # on the same symbol.

        if (

            trade["i"]

            <= blocked_until.get(
                symbol,
                -1
            )
        ):

            continue

        (
            r,
            exit_i,
            reason
        ) = simulate_short(

            data[
                symbol
            ],

            trade,

            target_r
        )

        blocked_until[
            symbol
        ] = (

            exit_i
            + COOLDOWN_BARS
        )

        results.append({

            "symbol":
                symbol,

            "time":
                trade[
                    "time"
                ],

            "side":
                "SHORT",

            "r":
                r,

            "exit":
                reason,

            "target_r":
                target_r,
        })

    return sorted(
        results,
        key=lambda x:
            x["time"]
    )


# ============================================================
# SYMBOL DIVERSIFICATION
# ============================================================


def diversification(
    results
):

    if not results:

        return {

            "symbols_used":
                0,

            "top_share":
                1.0,

            "positive_symbols":
                0,
        }

    counts = Counter(

        row["symbol"]

        for row
        in results
    )

    symbol_r = defaultdict(
        float
    )

    for row in results:

        symbol_r[
            row["symbol"]
        ] += row[
            "r"
        ]

    top_count = max(
        counts.values()
    )

    top_share = (

        top_count
        / len(results)
    )

    positive_symbols = sum(

        value > 0

        for value
        in symbol_r.values()
    )

    return {

        "symbols_used":
            len(
                counts
            ),

        "top_share":
            top_share,

        "positive_symbols":
            positive_symbols,
    }


# ============================================================
# ROBUSTNESS RULES
# ============================================================


def period_pass(
    metrics,
    min_trades,
    min_pf=1.00
):

    return bool(

        metrics

        and metrics[
            "trades"
        ]
        >= min_trades

        and metrics[
            "net_r"
        ]
        > 0

        and safe_pf(
            metrics
        )
        >= min_pf
    )


def evaluate_robustness(
    full_m,
    older_m,
    recent_m,
    quarter_metrics,
    div
):

    # Full year must be clearly profitable.

    full_pass = bool(

        full_m

        and full_m[
            "trades"
        ]
        >= MIN_FULL_TRADES

        and full_m[
            "net_r"
        ]
        > 0

        and safe_pf(
            full_m
        )
        >= 1.15

        and full_m[
            "avg_r"
        ]
        > 0.03

        and full_m[
            "max_dd"
        ]
        <= MAX_FULL_DD
    )

    # Old 275 days must work independently.

    older_pass = period_pass(

        older_m,

        min_trades=25,

        min_pf=1.05
    )

    # Most recent 90 days must also work.

    recent_pass = period_pass(

        recent_m,

        min_trades=
            MIN_RECENT_TRADES,

        min_pf=1.05
    )

    # Require stability through time.

    positive_quarters = sum(

        1

        for m
        in quarter_metrics

        if (

            m

            and m[
                "trades"
            ]
            >= 5

            and m[
                "net_r"
            ]
            > 0

            and safe_pf(
                m
            )
            >= 0.95
        )
    )

    quarters_pass = (

        positive_quarters
        >= 3
    )

    # Do not allow one coin
    # to create all the profits.

    diversification_pass = bool(

        div[
            "symbols_used"
        ]
        >= MIN_SYMBOLS_USED

        and div[
            "top_share"
        ]
        <= MAX_TOP_SYMBOL_SHARE

        and div[
            "positive_symbols"
        ]
        >= 5
    )

    checks = {

        "FULL":
            full_pass,

        "OLDER":
            older_pass,

        "RECENT90":
            recent_pass,

        "TIME_BLOCKS":
            quarters_pass,

        "DIVERSIFICATION":
            diversification_pass,
    }

    robustness = sum(
        checks.values()
    )

    approved = all(
        checks.values()
    )

    return (
        checks,
        robustness,
        approved,
        positive_quarters
    )


# ============================================================
# MAIN
# ============================================================


def main():

    print(
        "=" * 88
    )

    print(
        "AI TRADE SCANNER - "
        "SHORT PRO INDEPENDENT DISCOVERY"
    )

    print(
        "=" * 88
    )

    print(
        "Version:",
        VERSION
    )

    print(
        "Historical source: OKX"
    )

    print(
        "LONG main.py: UNTOUCHED"
    )

    print(
        "Direction tested: SHORT ONLY"
    )

    print(
        "Validation:",
        DAYS,
        "days"
    )

    print(
        "Targets:",
        TARGETS
    )

    print(
        "Maximum hold:",
        MAX_HOLD_HOURS,
        "hours"
    )

    print(
        "Round-trip cost:",
        f"{bt.ROUND_TRIP_COST_PCT * 100:.3f}%"
    )

    print(
        "Checks: FULL + OLDER + "
        "RECENT90 + 4 BLOCKS + "
        "DIVERSIFICATION"
    )

    # ========================================================
    # LOAD DATA
    # ========================================================

    data = {}

    candidates = []

    usable_symbols = []

    for number, symbol in enumerate(
        bt.SYMBOLS,
        start=1
    ):

        print()

        print(
            "#" * 88
        )

        print(
            f"[{number}/"
            f"{len(bt.SYMBOLS)}] "
            f"LOADING {symbol}"
        )

        print(
            "#" * 88
        )

        try:

            df = bt.prepare(
                symbol
            )

            if (
                df is None
                or df.empty
            ):

                print(
                    "SKIPPED"
                )

                continue

            data[
                symbol
            ] = df

            usable_symbols.append(
                symbol
            )

            found = find_pro_candidates(
                symbol,
                df
            )

            candidates.extend(
                found
            )

            print(
                "Raw PRO SHORT triggers:",
                len(
                    found
                )
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )

    candidates.sort(
        key=lambda x:
            x["time"]
    )

    print()

    print(
        "=" * 88
    )

    print(
        "DATA / CANDIDATE BUILD COMPLETED"
    )

    print(
        "=" * 88
    )

    print(
        "Usable symbols:",
        len(
            usable_symbols
        )
    )

    print(
        "Raw SHORT triggers:",
        len(
            candidates
        )
    )

    if not candidates:

        print(
            "NO SHORT TRIGGERS FOUND."
        )

        print(
            "SHORT PRO NOT APPROVED."
        )

        return

    # ========================================================
    # COMMON VALIDATION DATES
    # ========================================================

    validation_end = min(

        data[
            symbol
        ]
        .iloc[-1][
            "signal_time"
        ]

        for symbol
        in usable_symbols
    )

    validation_start = (

        validation_end

        - pd.Timedelta(
            days=DAYS
        )
    )

    recent_start = (

        validation_end

        - pd.Timedelta(
            days=RECENT_DAYS
        )
    )

    last30_start = (

        validation_end

        - pd.Timedelta(
            days=LAST30_DAYS
        )
    )

    # Four chronological blocks.

    q_edges = [

        validation_start,

        validation_start
        + pd.Timedelta(
            days=91
        ),

        validation_start
        + pd.Timedelta(
            days=182
        ),

        validation_start
        + pd.Timedelta(
            days=273
        ),

        validation_end
        + pd.Timedelta(
            seconds=1
        ),
    ]

    print(
        "Validation start:",
        validation_start
    )

    print(
        "Validation end:",
        validation_end
    )

    # ========================================================
    # TEST ALL PROFESSIONAL MODELS
    # ========================================================

    ranking = []

    for setup in setups():

        for target_r in TARGETS:

            name = (

                f'{setup["name"]} '
                f'| TP={target_r:g}R'
            )

            print()

            print(
                "#" * 88
            )

            print(
                name
            )

            print(
                "#" * 88
            )

            results = run_setup(

                candidates,

                data,

                setup[
                    "condition"
                ],

                target_r
            )

            full = slice_results(

                results,

                start=
                    validation_start,

                end=
                    validation_end
                    + pd.Timedelta(
                        seconds=1
                    )
            )

            older = slice_results(

                full,

                end=
                    recent_start
            )

            recent = slice_results(

                full,

                start=
                    recent_start
            )

            last30 = slice_results(

                full,

                start=
                    last30_start
            )

            quarters = []

            for qi in range(
                4
            ):

                quarter = slice_results(

                    full,

                    start=
                        q_edges[
                            qi
                        ],

                    end=
                        q_edges[
                            qi + 1
                        ]
                )

                quarters.append(
                    quarter
                )

            full_m = bt.calc_metrics(
                full
            )

            older_m = bt.calc_metrics(
                older
            )

            recent_m = bt.calc_metrics(
                recent
            )

            last30_m = bt.calc_metrics(
                last30
            )

            quarter_m = [

                bt.calc_metrics(
                    rows
                )

                for rows
                in quarters
            ]

            div = diversification(
                full
            )

            (
                checks,
                robustness,
                approved,
                positive_quarters
            ) = evaluate_robustness(

                full_m,
                older_m,
                recent_m,
                quarter_m,
                div
            )

            print_metrics(
                "OLDER275",
                older_m
            )

            print_metrics(
                "RECENT90",
                recent_m
            )

            print_metrics(
                "LAST30",
                last30_m
            )

            print_metrics(
                "FULL365",
                full_m
            )

            for index, qm in enumerate(
                quarter_m,
                start=1
            ):

                print_metrics(
                    f"BLOCK{index}",
                    qm
                )

            print()

            print(

                "Diversification | "

                f'Symbols:'
                f'{div["symbols_used"]} | '

                f'TopShare:'
                f'{div["top_share"] * 100:.1f}% | '

                f'PositiveSymbols:'
                f'{div["positive_symbols"]}'
            )

            print(
                "Checks:",
                checks
            )

            print(
                "Positive blocks:",
                f"{positive_quarters}/4"
            )

            print(
                "ROBUSTNESS:",
                f"{robustness}/5"
            )

            if approved:

                verdict = (
                    "PRO APPROVED"
                )

            else:

                verdict = (
                    "FAIL / WATCH ONLY"
                )

            print(
                "VERDICT:",
                verdict
            )

            freq = frequency(
                full_m
            )

            print(

                "Signal frequency | "

                f'Year:'
                f'{freq["year"]} | '

                f'Month:'
                f'{freq["month"]:.1f} | '

                f'Week:'
                f'{freq["week"]:.2f} | '

                f'Day:'
                f'{freq["day"]:.3f}'
            )

            ranking.append({

                "name":
                    name,

                "approved":
                    approved,

                "robustness":
                    robustness,

                "full":
                    full_m,

                "older":
                    older_m,

                "recent":
                    recent_m,

                "last30":
                    last30_m,

                "quarters":
                    quarter_m,

                "div":
                    div,

                "checks":
                    checks,

                "freq":
                    freq,
            })

    # ========================================================
    # RANKING
    # ========================================================

    def ranking_key(
        row
    ):

        full = row[
            "full"
        ]

        if full is None:

            return (
                row[
                    "approved"
                ],
                row[
                    "robustness"
                ],
                -999,
                -999,
                -999,
            )

        return (

            row[
                "approved"
            ],

            row[
                "robustness"
            ],

            min(
                safe_pf(
                    full
                ),
                5.0
            ),

            full[
                "avg_r"
            ],

            -full[
                "max_dd"
            ]
        )

    ranking.sort(
        key=ranking_key,
        reverse=True
    )

    print()

    print(
        "=" * 88
    )

    print(
        "FINAL SHORT PRO RANKING"
    )

    print(
        "Priority: ROBUSTNESS > "
        "PF > AVG R > LOW DD"
    )

    print(
        "=" * 88
    )

    for position, row in enumerate(
        ranking,
        start=1
    ):

        print()

        print(
            f"RANK {position}"
        )

        print(
            row[
                "name"
            ]
        )

        print(
            "APPROVED:",
            row[
                "approved"
            ]
        )

        print(
            "ROBUSTNESS:",
            f'{row["robustness"]}/5'
        )

        print_metrics(
            "FULL365",
            row[
                "full"
            ]
        )

        print_metrics(
            "OLDER275",
            row[
                "older"
            ]
        )

        print_metrics(
            "RECENT90",
            row[
                "recent"
            ]
        )

        print(

            "Frequency | "

            f'Year:'
            f'{row["freq"]["year"]} | '

            f'Month:'
            f'{row["freq"]["month"]:.1f} | '

            f'Week:'
            f'{row["freq"]["week"]:.2f}'
        )

        print(

            "Diversification | "

            f'Symbols:'
            f'{row["div"]["symbols_used"]} | '

            f'TopShare:'
            f'{row["div"]["top_share"] * 100:.1f}%'
        )

    # ========================================================
    # FINAL DECISION
    # ========================================================

    approved_rows = [

        row

        for row
        in ranking

        if row[
            "approved"
        ]
    ]

    print()

    print(
        "=" * 88
    )

    print(
        "FINAL SHORT PRO DECISION"
    )

    print(
        "=" * 88
    )

    if approved_rows:

        winner = (
            approved_rows[
                0
            ]
        )

        print(
            "PROFESSIONAL SHORT "
            "SETUP APPROVED"
        )

        print(
            "WINNER:",
            winner[
                "name"
            ]
        )

        print()

        print_metrics(
            "FULL365",
            winner[
                "full"
            ]
        )

        print_metrics(
            "OLDER275",
            winner[
                "older"
            ]
        )

        print_metrics(
            "RECENT90",
            winner[
                "recent"
            ]
        )

        print()

        print(
            "HISTORICAL SIGNAL FREQUENCY"
        )

        print(
            "Year:",
            winner[
                "freq"
            ][
                "year"
            ]
        )

        print(
            "Month:",
            f'{winner["freq"]["month"]:.1f}'
        )

        print(
            "Week:",
            f'{winner["freq"]["week"]:.2f}'
        )

        print()

        print(
            "NEXT STEP:"
        )

        print(
            "Build a separate SHORT "
            "forward-test scanner using "
            "this exact winner."
        )

        print(
            "Do NOT merge SHORT into "
            "LONG until forward testing "
            "confirms it."
        )

    else:

        best = ranking[
            0
        ]

        print(
            "NO SHORT PRO SETUP "
            "PASSED ALL CHECKS."
        )

        print()

        print(
            "BEST RESEARCH CANDIDATE:"
        )

        print(
            best[
                "name"
            ]
        )

        print(
            "ROBUSTNESS:",
            f'{best["robustness"]}/5'
        )

        print_metrics(
            "FULL365",
            best[
                "full"
            ]
        )

        print()

        print(
            "DO NOT FORCE SHORT "
            "INTO main.py."
        )

        print(
            "LONG V3.0-E REMAINS "
            "UNCHANGED."
        )

    print()

    print(
        "=" * 88
    )

    print(
        "SHORT PRO BACKTEST COMPLETED"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":
    main()
