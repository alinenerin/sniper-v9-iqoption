"""FinBERT news context. OTC symbols inherit base-pair sentiment as auxiliary only."""
import json, os
from pathlib import Path
import requests
from transformers import pipeline

base_symbols = os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
base_symbols = [s.upper().replace('-OTC','') for s in base_symbols]
include_otc = os.getenv('INCLUDE_OTC','false').lower() == 'true'
token = os.getenv('MARKETAUX_API_TOKEN')
results = {}
if not token:
    raise RuntimeError('MARKETAUX_API_TOKEN_NOT_CONFIGURED')
clf = pipeline('text-classification', model='ProsusAI/finbert', tokenizer='ProsusAI/finbert', top_k=None)
for symbol in base_symbols:
    try:
        r = requests.get('https://api.marketaux.com/v1/news/all', params={
            'symbols': symbol, 'filter_entities':'true', 'language':'en', 'limit':10,
            'api_token':token}, timeout=20)
        r.raise_for_status()
        articles = r.json().get('data', [])
        labels=[]
        for article in articles:
            text=(article.get('title') or article.get('description') or '').strip()
            if text:
                pred=clf(text[:2000])[0]; best=max(pred,key=lambda x:x['score'])
                labels.append({'label':best['label'],'score':round(float(best['score']),6),'text':text})
        results[symbol]={'symbol':symbol,'status':'inference_ok','model':'ProsusAI/finbert','articles':len(labels), 'labels':labels,
                         'role':'auxiliary_only','veto_authority':'chart_only'}
    except Exception as exc:
        results[symbol]={'symbol':symbol,'status':'error','reason':f'{type(exc).__name__}: {exc}', 'role':'auxiliary_only','veto_authority':'chart_only'}
if include_otc:
    for base in base_symbols:
        otc=base+'-OTC'
        source=results[base]
        results[otc]={'symbol':otc,'base_symbol':base,'status':source['status'],
                      'reason':source.get('reason'),'model':source.get('model','ProsusAI/finbert'),
                      'articles':source.get('articles',0),'labels':source.get('labels',[]),
                      'role':'auxiliary_only','mapping':'base_pair_sentiment_context_only',
                      'direct_otc_causation':False,'hard_blocker':False,'veto_authority':'chart_only'}
Path('reports/finbert_inference.json').write_text(json.dumps({
    'status':'ok','purpose':'Base-pair sentiment mapped to OTC as context only',
    'components':results,'read_only':True,'execution_allowed':False
},ensure_ascii=False,indent=2)+'\n')
print('finbert_inference_complete',len(results))
