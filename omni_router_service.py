"""Lightweight read-only OmniRouter service: Groq primary, OpenRouter fallback."""
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
GROQ_URL='https://api.groq.com/openai/v1/chat/completions'
OPENROUTER_URL='https://openrouter.ai/api/v1/chat/completions'
def call(url,key,model,messages):
    if not key: return None,'missing_key'
    body=json.dumps({'model':model,'messages':messages,'temperature':0.1,'max_tokens':700}).encode()
    req=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'BinaryQuantX-OmniRouter/1.0'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r: data=json.loads(r.read().decode())
        text=((data.get('choices') or [{}])[0].get('message') or {}).get('content')
        return {'provider':'groq' if 'groq' in url else 'openrouter','model':model,'content':text,'read_only':True},None
    except Exception as e: return None,type(e).__name__
def consensus(payload):
    system=('Você é um analista consultivo. Responda em JSON válido com summary, direction, confidence, risks. '
            'Não invente cotações, não autorize ordens, não sugira gale/martingale. Se faltarem dados, diga AGUARDAR.')
    msgs=[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    result,err=call(GROQ_URL,os.getenv('GROQ_API_KEY',''),os.getenv('GROQ_MODEL','llama-3.3-70b-versatile'),msgs)
    errors=[]
    if result:return {'status':'ok','selected':result,'fallback_used':False,'read_only':True,'execution_allowed':False}
    errors.append({'provider':'groq','reason':err})
    result,err=call(OPENROUTER_URL,os.getenv('OPENROUTER_API_KEY',''),os.getenv('OPENROUTER_MODEL','openai/gpt-oss-20b:free'),msgs)
    if result:return {'status':'ok','selected':result,'fallback_used':True,'errors':errors,'read_only':True,'execution_allowed':False}
    errors.append({'provider':'openrouter','reason':err})
    return {'status':'blocked','reason':'NO_AI_PROVIDER_AVAILABLE','errors':errors,'read_only':True,'execution_allowed':False}
class Handler(BaseHTTPRequestHandler):
    def send_json(self,data,code=200):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        self.send_json({'status':'ok','service':'omni-router','providers':['groq','openrouter'],'read_only':True,'execution_allowed':False})
    def do_POST(self):
        if not self.path.startswith('/v1/consensus'):return self.send_json({'status':'blocked','reason':'NOT_FOUND','execution_allowed':False},404)
        expected=os.getenv('OMNI_API_KEY','')
        if expected and self.headers.get('X-API-Key') != expected:
            return self.send_json({'status':'blocked','reason':'UNAUTHORIZED','execution_allowed':False},401)
        try:payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')) or 0).decode() or '{}')
        except Exception:return self.send_json({'status':'blocked','reason':'INVALID_JSON','execution_allowed':False},400)
        self.send_json(consensus(payload))
    def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','10000'))),Handler).serve_forever()
