import time
def forex_engine_loop():
    print("🌍 [V16 SUPREME] Motor Forex (SMC/H1) Ativo...")
    while True:
        spread, spread_avg = 5, 2
        if spread > (spread_avg * 1.5):
            print("⚠️ VETO: Spread alto.")
        time.sleep(60)

if __name__ == "__main__":
    forex_engine_loop()
