"""Write the canonical TradingView DXY/VIX source for GitHub scans."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from macro_source import fetch_macro

out = fetch_macro()
Path('reports').mkdir(exist_ok=True)
Path('reports/macro_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('tradingview_macro=', 'OK' if out['ok'] else 'BLOCKED', out['symbols'])
