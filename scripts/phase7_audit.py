"""Final safety audit for Phase 7; does not connect to brokers or place orders."""
from __future__ import annotations
import ast, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    findings=[]
    for path in (ROOT/'shared_ai',ROOT/'research'):
        if not path.exists(): continue
        for f in path.rglob('*.py'):
            try: tree=ast.parse(f.read_text(errors='ignore'))
            except SyntaxError: findings.append(f"SYNTAX_ERROR:{f.relative_to(ROOT)}"); continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.lower() in {"buy","sell","execute_order"}:
                    findings.append(f"EXECUTION_CALL:{f.relative_to(ROOT)}:{node.func.attr}")
    checks={
      'execution_guard': (ROOT/'execution_guard.py').exists(),
      'shared_ai': (ROOT/'shared_ai/consultation.py').exists(),
      'paper_memory': (ROOT/'shared_ai/performance_service.py').exists(),
      'optimizer_research_only': (ROOT/'research/strategy_optimizer.py').exists(),
      'cycle_catalog': (ROOT/'shared_ai/cycle_catalog.py').exists(),
      'lse_advisor': (ROOT/'shared_ai/lse_advisor.py').exists(),
    }
    report={'status':'inference_ok' if all(checks.values()) and not findings else 'blocked','mode':'final_audit','checks':checks,'execution_findings':findings,'execution_allowed':False,'paper_trading_required':True,'real_orders':False,'read_only':True}
    Path('reports').mkdir(exist_ok=True); Path('reports/phase7_audit.json').write_text(json.dumps(report,indent=2))
    print('phase7_audit=',report['status'])
    if findings: print('phase7_audit_findings=', findings)
if __name__=='__main__': main()
