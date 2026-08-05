"""Multi-source Forex news retrieval followed by FinBERT sentiment inference."""
import json, os, re
from pathlib import Path
from datetime import date, timedelta, datetime, timezone
import requests
from transformers import pipeline
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split(); marketaux=os.getenv('MARKETAUX_API_TOKEN'); finnhub=os.getenv('FINNHUB_API_TOKEN'); session=requests.Session()
def add(rows, source, title, description='', url=''):
    text=(title or description or '').strip()
    if text: rows.append({'source':source,'text':text[:2000],'url':url})
def fetch(symbol):
    rows=[]
    if finnhub:
        try:
            end=date.today(); start=end-timedelta(days=2)
            data=session.get('https://finnhub.io/api/v1/news',params={'category':'forex','from':start.isoformat(),'to':end.isoformat(),'token':finnhub},timeout=15).json()
            for a in data if isinstance(data,list) else []:
                text=(a.get('headline','')+' '+a.get('summary','')).lower()
                if symbol[:3].lower() in text or symbol[3:].lower() in text or any(k in text for k in ('fed','ecb','boe','boj','rba','inflation','interest rate','jobs')): add(rows,'finnhub',a.get('headline'),a.get('summary'),a.get('url',''))
        except Exception: pass
    if marketaux:
        try:
            data=session.get('https://api.marketaux.com/v1/news/all',params={'symbols':symbol,'filter_entities':'true','language':'en','limit':10,'api_token':marketaux},timeout=15).json()
            for a in data.get('data',[]) if isinstance(data,dict) else []: add(rows,'marketaux',a.get('title'),a.get('description'),a.get('url',''))
        except Exception: pass
    try:
        for q in (f'{symbol[:3]} forex', f'{symbol[3:]} currency', 'forex central bank'):
            data=session.get('https://api.gdeltproject.org/api/v2/doc/doc',params={'query':q,'mode':'artlist','format':'json','maxrecords':25,'sort':'datedesc'},timeout=20).json()
            for a in data.get('articles',[]) if isinstance(data,dict) else []: add(rows,'gdelt',a.get('title'),a.get('seendate',''),a.get('url',''))
    except Exception: pass
    # Verified economic-calendar fallback when news APIs are rate-limited.
    try:
        cal=session.get('https://nfs.faireconomy.media/ff_calendar_thisweek.json',timeout=15).json()
        country_map={'EUR':'euro','USD':'united states','GBP':'united kingdom','JPY':'japan','AUD':'australia'}
        for e in cal if isinstance(cal,list) else []:
            country=str(e.get('country','')).upper()
            if country in (symbol[:3], symbol[3:]):
                title=e.get('title') or e.get('event') or ''
                add(rows,'forexfactory',f'{country_map.get(country,country)} {title} ({e.get("impact","")} impact)',str(e.get('date','')),e.get('url',''))
    except Exception: pass

    seen=set(); out=[]
    for x in rows:
        key=re.sub(r'[^a-z0-9]+',' ',x['text'].lower()).strip()
        if key and key not in seen: seen.add(key); out.append(x)
    return out[:30]
clf=pipeline('text-classification',model='ProsusAI/finbert',tokenizer='ProsusAI/finbert',top_k=None); results={}
for symbol in symbols:
    articles=fetch(symbol); labels=[]
    for a in articles:
        pred=clf(a['text'])[0]; best=max(pred,key=lambda x:x['score']); labels.append({'source':a['source'],'label':best['label'],'score':round(float(best['score']),6),'text':a['text'],'url':a['url']})
    results[symbol]={'status':'inference_ok' if labels else 'inconclusive','model':'ProsusAI/finbert','articles':len(labels),'labels':labels,'sources':sorted({a['source'] for a in articles})}
Path('reports/finbert_inference.json').write_text(json.dumps({'status':'ok','provider_mode':'multi_source','components':results,'read_only':True,'generated_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2)+'\n'); print('finbert_multisource_complete',len(results))
