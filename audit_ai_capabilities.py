from shared_ai.capabilities import capability_report

report = capability_report()
for name, status in sorted(report.items()):
    print(f"{name}: importable={status.get('importable')} active={status.get('active')}" +
          (f" evidence={status['evidence']}" if 'evidence' in status else ''))

# These are explicit safety assertions, not claims that optional providers are live.
assert report['finbert']['active'] is False
assert report['marketaux_sentiment']['active'] is True
