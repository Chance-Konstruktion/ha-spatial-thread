# Spatial Thread

> **Vorlaeufige Beschreibung.** Aus CHANGELOG und Quelltext rekonstruiert, nicht die Originalfassung des Autors -- diese liegt auf GitHub und wird hier ersetzt, sobald sie verfuegbar ist.


Spatial-Hub-Provider fuer Border Router, Router und End Devices des Thread-Netzes.

Diese Integration meldet dem [Spatial Hub](https://gitlab.schanz.ipv64.net/chance-konstruktion/ha-spatial-hub) Border Router, Router und End Devices des Thread-Netzes,
damit sie auf dem Grundriss auftauchen. Sie ist eine ganz normale Home
Assistant-Integration und laeuft auch dann, wenn der Hub gar nicht
installiert ist -- dann passiert schlicht nichts.

## Was hier als Kante gemeldet wird

Die Mesh-Nachbarschaften. Thread baut sein Netz selbst und weiss jederzeit, wer mit wem spricht.

## Stand

**Geruest.** Aufbau, Manifest, Config Flow und der Provider-Shim stehen.
Was noch fehlt, ist die Funktion `_spatial_data()` in
[`custom_components/spatial_thread/__init__.py`](custom_components/spatial_thread/__init__.py):
Sie liefert derzeit eine leere Liste, weil das Auslesen der Topologie fuer
jeden Transport anders aussieht.

Die Integration ist damit installierbar und tut nichts Falsches -- sie hat
nur noch nichts zu erzaehlen.

## Installation

Ueber HACS als benutzerdefiniertes Repository, oder von Hand:
`custom_components/spatial_thread/` nach `config/custom_components/` kopieren und
Home Assistant neu starten.

## Warum nichts aus `spatial_hub` importiert wird

Die Datei `spatial_hub_provider.py` ist eine **Kopie** aus dem Hub, kein
Import. Der Hub kann fehlen, in einer anderen Version vorliegen oder
entfernt werden, waehrend diese Integration weiterlaeuft. Der Shim schreibt
nur ein Dict nach `hass.data` und feuert ein Dispatcher-Signal -- beides
kostet nichts, wenn niemand zuhoert.

Naeheres in der [SDK-Dokumentation des Hubs](https://gitlab.schanz.ipv64.net/chance-konstruktion/ha-spatial-hub/-/blob/main/sdk/README.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE).

