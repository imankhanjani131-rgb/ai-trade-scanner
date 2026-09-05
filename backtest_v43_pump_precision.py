import sys

import backtest_v42_super_pump as core


# ============================================================
# V4.3 PUMP PRECISION
# ============================================================

core.VERSION = "V4.3-PUMP-PRECISION"


# هدف:
# پیدا کردن نقطه تعادل بین S2_CONFIRM و S3_STRICT در V4.2
#
# V4.2:
# S2 = 35 trades | PF 0.97
# S3 = 12 trades | PF 1.08
#
# در V4.3 سه حالت بین این دو را تست می‌کنیم.

core.PROFILES = {

    # S2 + الزام روند صعودی 4H
    "P1_4H_CONFIRM": {
        "min_score": 12,
        "min_vol_accel": 1.20,
        "min_vol_ratio5": 1.00,
        "max_dist5": 1.15,
        "need_near_breakout": True,
        "need_4h_bull": True,
    },

    # حالت متعادل بین S2 و S3
    "P2_BALANCED": {
        "min_score": 13,
        "min_vol_accel": 1.20,
        "min_vol_ratio5": 1.05,
        "max_dist5": 1.10,
        "need_near_breakout": True,
        "need_4h_bull": True,
    },

    # Precision بالاتر ولی کمی آزادتر از S3
    "P3_PRECISION": {
        "min_score": 13,
        "min_vol_accel": 1.25,
        "min_vol_ratio5": 1.10,
        "max_dist5": 1.05,
        "need_near_breakout": True,
        "need_4h_bull": True,
    },

    # یک مدل برای گرفتن نمونه بیشتر؛
    # فقط کمی آزادتر از S2
    "P4_SAMPLE": {
        "min_score": 12,
        "min_vol_accel": 1.15,
        "min_vol_ratio5": 1.00,
        "max_dist5": 1.20,
        "need_near_breakout": True,
        "need_4h_bull": False,
    },
}


# خروجی‌های هاردکد V4.2 را هنگام چاپ به V4.3 تبدیل می‌کنیم.
class RenameOutput:

    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        text = text.replace(
            "V4.2 SUPER PUMP MAX",
            "V4.3 PUMP PRECISION"
        )
        return self.stream.write(text)

    def flush(self):
        return self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def main():

    original_stdout = sys.stdout
    sys.stdout = RenameOutput(original_stdout)

    try:
        core.main()

    finally:
        sys.stdout = original_stdout


if __name__ == "__main__":
    main()
