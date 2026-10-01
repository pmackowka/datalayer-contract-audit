"""Sprawdzenia na liście przechwyconych pushy - wspólne dla scenariuszy i raportu."""

from collections.abc import Sequence

from pydantic import ValidationError

from datalayer_audit.capture import CapturedPush
from datalayer_audit.contract import push_kind, validate_push


def kinds(pushes: Sequence[CapturedPush]) -> list[str | None]:
    """Sekwencja etykiet pushy - czytelniejsza w asercji niż pełne payloady."""
    return [push_kind(p.payload) for p in pushes]


def contract_errors(pushes: Sequence[CapturedPush]) -> list[str]:
    """Waliduje WSZYSTKIE pushe i zwraca wszystkie błędy naraz.

    Przerwanie na pierwszym błędzie ukryłoby kolejne, a audyt ma pokazać pełny obraz.
    """
    errors = []
    for push in pushes:
        try:
            validate_push(push.payload)
        except ValidationError as exc:
            errors.append(f"push #{push.index} {push.payload!r}\n{exc}")
    return errors


def assert_contract(pushes: Sequence[CapturedPush]) -> None:
    errors = contract_errors(pushes)
    assert not errors, "pushe niezgodne z kontraktem:\n\n" + "\n\n".join(errors)
