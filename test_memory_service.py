from pathlib import Path
from tempfile import TemporaryDirectory
from shared_ai.memory_service import ZapiaMemoryService

with TemporaryDirectory() as tmp:
    svc = ZapiaMemoryService(str(Path(tmp) / 'zapia.db'))
    assert svc.remember_explicit('zero_gale', 'Preferir silêncio operacional a entradas fracas.', 'rule')['saved'] is False
    saved = svc.remember_explicit('zero_gale', 'Preferir silêncio operacional a entradas fracas.', 'rule', user_confirmed=True)
    assert saved['saved'] is True and saved['fingerprint']
    assert svc.context_for('zero_gale')['memory_count'] == 1
    assert svc.forget('zero_gale')['forgotten'] is False
    assert svc.forget('zero_gale', user_confirmed=True)['forgotten'] is True
    print('memory_service=OK')
