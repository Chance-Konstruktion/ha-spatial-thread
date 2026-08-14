"""Der volle Konformitaetssatz, gegen eine NICHT leere Nutzlast.

Die Suite nebenan prueft den Weg ohne Thread -- den Ausfallpfad. Dort ist
die Nutzlast leer, und eine leere Liste erfuellt jeden Vertrag muehelos:
keine Kennung kann wackeln, keine Kante ins Leere zeigen, keine Metadaten
sich dem Websocket verweigern. Sie beweist nichts.

Gestellt sind hier genau zwei Dinge, und beide brauchen im Betrieb ein
Netz: die mDNS-Entdeckung, die Border Router meldet, und der Datensatz-
Speicher, der die bekannten Netze haelt. Alles andere ist echt -- echtes
``hass``, echtes Geraeteregister, echte Bereiche. Insbesondere laeuft die
Verknuepfung Router -> Home-Assistant-Geraet -> Raum durch denselben
Code wie im Haus.

Der Aufbau ist der Fall, um den es geht und den nichts in Home Assistant
zeigt: **zwei** Border Router auf **zwei verschiedenen** Thread-Netzen.
Ein Geraet, das dem falschen beitritt, ist ohne Fehlermeldung
unerreichbar, und auf dem Grundriss sind es zwei getrennte Haufen -- das
ist die ganze Diagnose.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spatial_hub_conformance import SpatialHubConformance

EIGENE_DOMAIN = "spatial_thread"

# Der Router, der einem Home-Assistant-Geraet zugeordnet werden kann --
# ueber seine erweiterte Adresse, die als Verbindung am Geraet steht.
APPLE_EUI = "f4:5c:89:aa:bb:01"
NEST_EUI = "1a:2b:3c:dd:ee:02"

PAN_EIGEN = "1122334455667788"
PAN_FREMD = "99aabbccddeeff00"


def _router(eui: str, hersteller: str, modell: str, pan: str, server: str):
    """Ein Border Router, wie ihn ThreadRouterDiscoveryData liefert."""
    return SimpleNamespace(
        instance_name=f"{modell}-{eui[-2:]}",
        addresses=["fd00::1"],
        border_agent_id=f"agent-{eui[-2:]}",
        brand=hersteller.lower(),
        extended_address=eui,
        extended_pan_id=pan,
        model_name=modell,
        network_name="Mein Thread" if pan == PAN_EIGEN else "Fremdes Netz",
        server=server,
        thread_version="1.3.0",
        unconfigured=False,
        vendor_name=hersteller,
    )


class _FakeDiscovery:
    """Meldet die Router sofort, statt auf mDNS zu warten."""

    router: list = []

    def __init__(self, _hass, entdeckt, _entfernt):
        self._entdeckt = entdeckt

    async def async_start(self) -> None:
        for router in self.router:
            self._entdeckt(router.extended_address, router)

    async def async_stop(self) -> None:
        return None


@pytest.fixture
def threadhaus(hass: HomeAssistant, enable_custom_integrations, monkeypatch):
    """Zwei Border Router auf zwei Netzen, einer davon mit Geraet im Haus."""
    from homeassistant.components.thread import dataset_store, discovery

    bereiche = ar.async_get(hass)
    wohnzimmer = bereiche.async_create("Wohnzimmer")

    # Der Apple TV steht in Home Assistant und hat einen Raum. Genau
    # darueber soll der Router seinen Platz bekommen.
    fremd = MockConfigEntry(domain="apple_tv", title="Apple TV")
    fremd.add_to_hass(hass)
    geraete = dr.async_get(hass)
    geraet = geraete.async_get_or_create(
        config_entry_id=fremd.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, APPLE_EUI)},
        identifiers={("apple_tv", "wohnzimmer")},
        name="Apple TV Wohnzimmer",
    )
    geraete.async_update_device(geraet.id, area_id=wohnzimmer.id)

    _FakeDiscovery.router = [
        _router(APPLE_EUI, "Apple", "Apple TV", PAN_EIGEN, "apple-tv.local."),
        # Der zweite haengt an einem Netz, fuer das dieses Haus keine
        # Zugangsdaten hat -- die Diagnose, um die es geht.
        _router(NEST_EUI, "Google", "Nest Hub", PAN_FREMD, "nest-hub.local."),
    ]
    monkeypatch.setattr(discovery, "ThreadRouterDiscovery", _FakeDiscovery)

    class _Datensatz:
        id = "eigen"
        extended_pan_id = PAN_EIGEN
        network_name = "Mein Thread"
        channel = 15
        preferred_border_agent_id = f"agent-{APPLE_EUI[-2:]}"
        source = "otbr"

    class _Speicher:
        preferred_dataset = "eigen"
        datasets = {"eigen": _Datensatz()}

    async def _speicher(_hass):
        return _Speicher()

    monkeypatch.setattr(dataset_store, "async_get_store", _speicher)

    # Der Adapter haengt seinen Abbau an den Config Entry: die
    # Entdeckung wird gestoppt, der Zeitgeber abgemeldet. Wird der Eintrag
    # nie entladen, laeuft beides erst beim Abraeumen der Vorrichtung --
    # und dann ist die Ereignisschleife schon zu. Deshalb gehoert der
    # Eintrag hierher und wird hier auch wieder abgeraeumt.
    eigener = MockConfigEntry(domain=EIGENE_DOMAIN, title="Spatial Thread")
    eigener.add_to_hass(hass)
    yield hass, eigener

    hass.data.get("spatial_hub_providers", {}).pop(EIGENE_DOMAIN, None)
    eigener.async_on_unload_callbacks = []


def _anmeldung(threadhaus) -> dict:
    from custom_components.spatial_thread.spatial import async_setup_spatial

    hass, eintrag = threadhaus
    async_setup_spatial(hass, eintrag)
    return hass.data["spatial_hub_providers"][EIGENE_DOMAIN]


class TestKonformitaetMitInhalt(SpatialHubConformance):
    """Der Satz aus dem SDK an einem Haus mit zwei Thread-Netzen.

    Faellt diese Klasse, ist der Adapter vom Vertrag abgewichen -- nicht
    der Vertrag vom Adapter.
    """

    @pytest.fixture(autouse=True)
    def _binden(self, threadhaus):
        self._haus = threadhaus
        yield

    def build_registration(self):
        return _anmeldung(self._haus)


async def test_zwei_netze_werden_als_zwei_haufen_gezeichnet(threadhaus) -> None:
    """Die Gegenprobe, und der eigentliche Grund fuer diese Datei.

    Ein Konformitaetssatz ueber einer leeren Liste ist gruen und sagt
    nichts. Ginge die Vorrichtung oben still kaputt, bliebe er gruen,
    waehrend er nichts mehr prueft.

    Behauptet wird deshalb ausdruecklich, was drinstehen muss: beide
    Router, beide Netze, und der Apple TV im Wohnzimmer statt in der
    Mitte des Grundrisses.
    """
    hass, _ = threadhaus
    anmeldung = _anmeldung(threadhaus)
    await hass.async_block_till_done()

    nutzlast = await anmeldung["data"]()
    knoten = {k["id"]: k for k in nutzlast["nodes"]}

    assert f"router-{APPLE_EUI}" in knoten
    assert f"router-{NEST_EUI}" in knoten
    assert f"network-{PAN_EIGEN}" in knoten
    assert f"network-{PAN_FREMD}" in knoten, (
        "das fremde Netz ist die wichtigste Aussage dieser Ebene"
    )

    apple = knoten[f"router-{APPLE_EUI}"]
    assert apple["area_id"], "der Apple TV steht im Geraeteregister mit Raum"
    assert apple["metadata"]["verknuepft_ueber"] == "kennung"

    # Der Nest Hub hat kein Geraet im Haus -- also kein Raum, und das ist
    # die ehrliche Antwort statt eines geratenen.
    assert not knoten[f"router-{NEST_EUI}"].get("area_id")
