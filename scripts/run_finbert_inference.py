"""Fetch MarketAux headlines and run real ProsusAI/finbert inference."""
import json, os
from pathlib import Path
import requests
from transformers import pipeline

symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split()
token=os.getenv('MARKETAUX_API_TOKEN')
if not token:
    raise RuntimeError('MARKETAUX_API_TOKEN_NOT_CONFIGURED')
clf=pipeline('text-classification', model='ProsusAI/finbert', tokenizer='ProsusAI/finbert', top_k=None)
results={}
for symbol in symbols:
    r=requests.get('https://api.marketaux.com/v1/news/all',params={'symbols':symbol,'filter_entities':'true','language':'en','limit':10,'api_token':token},timeout=20)
    r.raise_for_status(); articles=r.json().get('data',[])
    texts=[(a.get('title') or a.get('description') or '').strip() for a in articles]
    texts=[x for x in texts if x]
    labels=[]
    for text in texts:
        pred=clf(text[:2000])[0]
        best=max(pred,key=lambda x:x['score'])
        labels.append({'label':best['label'],'score':round(float(best['score']),6),'text':text})
    results[symbol]={'status':'inference_ok','model':'ProsusAI/finbert','articles':len(texts),'labels':labels}
Path('reports/finbert_inference.json').write_text(json.dumps({'status':'ok','components':results,'read_only':True},ensure_ascii=False,indent=2)+'\n')
print('finbert_inference_complete',len(results))
