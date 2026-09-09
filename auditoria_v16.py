try:
    import xgboost as xgb
    print(f"✅ XGBoost carregado: {xgb.__version__}")
    import finmarketpy
    print("✅ Finmarketpy carregado com sucesso.")
    print("--- VEREDITO: CERTEZA_ABSOLUTA_OK ---")
except Exception as e:
    print(f"❌ FALHA NA AUDITORIA: {str(e)}")
