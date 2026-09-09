"""Guarda central de execução do V16.

A análise pode rodar continuamente. Envio de ordem só é possível por uma
chamada explícita com manual_authorized=True, nunca por loop, workflow ou CLI.
"""

class ManualAuthorizationError(RuntimeError):
    pass


def require_manual_authorization(manual_authorized: bool) -> None:
    if manual_authorized is not True:
        raise ManualAuthorizationError(
            "EXECUÇÃO BLOQUEADA: autorização manual explícita necessária"
        )
