"""Das Geraeteregister wird gelesen, ohne die veraltete Mapping-Sicht.

Core hat ``device_registry.devices`` als Abbildung abgekuendigt: jeder
Zugriff ueber ``.values()`` schreibt eine Warnung ins Protokoll und hoert
in Home Assistant 2027.9 auf zu arbeiten. Diese Ebene las das Register an
zwei Stellen so -- einmal ueber die Kennung des Routers, einmal ueber
seinen Namen.

Der Ersatz ist, ueber das Objekt selbst zu laufen. Beide Formen bleiben
verstanden: bis 2025.8 liefert das Iterieren die Schluessel, seit 2025.9
die Eintraege. Die Integration nennt 2024.4 als Untergrenze, also ist der
alte Weg kein Zierrat.
"""

from __future__ import annotations

import pytest

from custom_components.spatial_thread.spatial import _registry_entries


class _Registry:
    """Nur die Eigenschaft, die gelesen wird."""

    def __init__(self, devices):
        self.devices = devices


class _NeueSicht:
    """Wie Core seit 2025.9: Iterieren liefert die Eintraege.

    Der Indexzugriff ist verboten -- er ist genau das, was die Warnung
    schreibt. Kommt er doch, faellt der Test.
    """

    def __init__(self, eintraege):
        self._eintraege = list(eintraege)

    def __iter__(self):
        return iter(self._eintraege)

    def __bool__(self):
        return bool(self._eintraege)

    def __getitem__(self, schluessel):  # pragma: no cover - darf nie laufen
        raise AssertionError(
            "Indexzugriff auf registry.devices -- genau das ist abgekuendigt"
        )


def test_neue_sicht_ohne_abbildungszugriff():
    eins, zwei = object(), object()
    assert _registry_entries(_Registry(_NeueSicht([eins, zwei]))) == [eins, zwei]


def test_alte_sicht_wird_aufgeloest():
    eins, zwei = object(), object()
    assert _registry_entries(_Registry({"a": eins, "b": zwei})) == [eins, zwei]


@pytest.mark.parametrize("devices", [None, {}, _NeueSicht([])])
def test_leeres_register_gibt_leere_liste(devices):
    assert _registry_entries(_Registry(devices)) == []
