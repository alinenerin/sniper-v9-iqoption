"""Legacy Forex V15 compatibility entrypoint.

The production system is read-only. This compatibility module deliberately
cannot connect an account or submit an order.
"""


def executor_v15_v4(par="EURUSD", direcao="buy", valor=1):
    return {
        "ok": False,
        "execution_allowed": False,
        "reason": "EXECUTION_DISABLED_READ_ONLY",
        "symbol": par,
        "direction": direcao,
    }


if __name__ == "__main__":
    print(executor_v15_v4())
