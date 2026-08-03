from pathlib import Path
from tempfile import TemporaryDirectory
from shared_ai.memory import ZapiaMemory

with TemporaryDirectory() as tmp:
    mem = ZapiaMemory(str(Path(tmp) / 'memory.db'))
    mem.remember('zero_gale', 'Manter Zero Gale e preferir silêncio a uma entrada fraca.', 'rule')
    assert mem.recall('Zero Gale')[0]['key'] == 'zero_gale'
    assert mem.forget('zero_gale') is True
    assert mem.recall('Zero Gale') == []
    try:
        mem.remember('bad', 'senha: qualquer coisa', 'context')
    except ValueError as exc:
        assert str(exc) == 'SECRET_NOT_ALLOWED_IN_MEMORY'
    else:
        raise AssertionError('secret accepted')
    print('memory_contract=OK')
