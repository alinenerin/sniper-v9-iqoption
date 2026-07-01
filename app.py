#!/usr/bin/env python3
# app.py — Motor M5 Sniper (Railway Worker)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Usar iqoptionapi local (diretório iqoptionapi/ do repo)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

exec(open(os.path.join(os.path.dirname(__file__), "railway_worker.py")).read())
