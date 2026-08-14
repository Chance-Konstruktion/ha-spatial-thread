"""Thread on the floor plan: border routers, and the networks they serve.

Thread is where a house quietly ends up with a problem nobody can see. The
border routers are not one box the user bought -- they are an Apple TV, a
HomePod, two Google Nest speakers and Home Assistant's own radio, each of
which volunteered. Some are on the same Thread network and some have
started one of their own, and a device that joins the wrong one is simply
unreachable with no error message anywhere. Home Assistant knows all of
this. It shows it on a settings page, in a list, with no notion of which
room anything is in.

So: one node per border router, one node per Thread network, and an edge
from each router to the network it serves. Two networks means two clusters
on the plan, which is the entire diagnosis, visible without reading a word.

Where the data comes from, and both halves are Home Assistant's own:

- **Routers** from the same mDNS discovery the Thread settings page uses.
  It is push-shaped -- routers announce themselves and withdraw -- so this
  layer is told rather than polling, and the hub is notified on each
  change.
- **Networks** from the Thread dataset store, which also knows which
  border agent is the preferred one. That is the answer to "which of these
  five is actually in charge", and it is a single field nobody ever sees.

There are deliberately **no device nodes**. A Matter-over-Thread sensor is
a Thread device, but Home Assistant does not record that anywhere a third
party can read -- and the Matter layer already draws it in its room.
Guessing which devices are on Thread would be inventing the one thing this
layer would be believed about.

Border routers are discovered over the network, not created in the device
registry -- so there is no room attached to the discovery itself. But the
box usually *is* in Home Assistant under its own integration: an Apple TV,
a HomePod, Home Assistant's own radio. Where that device can be identified,
its area and one of its entities are carried over, so the router lands in
the room the user already put it in and the plan has a door back into Home
Assistant.

Identified means identified, not guessed at: the extended address against
the device's connections, or -- only when it matches exactly one device --
the mDNS hostname against the device name. Which of the two was used is
written onto the node, so a router in the wrong room can be traced instead
of merely being wrong. Where neither matches, the router keeps no area at
all and the hub places it, which is the honest answer.

There are no anchors here either, and that is not an omission. Anchoring
needs a distance-like measurement to something already placed, and mDNS
discovery has none: it says a router exists and what it serves, never how
far away it is. The Thread mesh itself would have that, but Home Assistant
does not expose it -- reading it would mean talking to each border router's
own API, which is a different project.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.event import async_track_time_interval

from .spatial_hub_provider import edge, node, spatial_provider

_LOGGER = logging.getLogger(__name__)

# Discovery pushes, so this is only a safety net for the half of the layer
# that does not: the dataset store, which changes when a user adds or
# prefers a network and not otherwise.
REFRESH = timedelta(minutes=5)

_UNKNOWN_NETWORK = "unbekannt"


def _pan(value: Any) -> str:
    """One spelling of an extended PAN ID, so two sources can be compared.

    The dataset store and mDNS both hand this over as hex, but not always
    the same hex: one may carry an ``0x`` prefix and the case is nobody's
    promise. Comparing the raw strings is how a router ends up next to a
    network it is already on.
    """
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text


async def _networks(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Every Thread network this installation knows, by extended PAN ID.

    The dataset store is a singleton behind an async accessor, which is
    why this half of the layer is async. Every field below is a property
    that parses a TLV blob, so each is asked for defensively: an entry that
    cannot be read costs its own detail, not the layer.
    """
    try:
        from homeassistant.components.thread import dataset_store
    except ImportError:  # pragma: no cover - core ships it
        return {}

    try:
        store = await dataset_store.async_get_store(hass)
    except Exception:  # noqa: BLE001 - never take the layer down with it
        _LOGGER.debug("Thread dataset store not readable", exc_info=True)
        return {}

    preferred_id = getattr(store, "preferred_dataset", None)
    networks: dict[str, dict[str, Any]] = {}
    for entry in (getattr(store, "datasets", None) or {}).values():
        try:
            pan = _pan(entry.extended_pan_id)
            name = entry.network_name or "Thread"
            channel = entry.channel
        except Exception:  # noqa: BLE001 - a malformed TLV is one entry's problem
            _LOGGER.debug("skipping unreadable Thread dataset", exc_info=True)
            continue
        if not pan:
            continue
        networks[pan] = {
            "name": name,
            "channel": channel,
            "preferred": getattr(entry, "id", None) == preferred_id,
            # Which router this network is meant to be reached through.
            # The single field that answers "which of these is in charge".
            "border_agent": str(
                getattr(entry, "preferred_border_agent_id", "") or ""
            ).lower(),
            "source": str(getattr(entry, "source", "") or ""),
        }
    return networks


def _router_label(address: str, router: Any) -> str:
    """What to call a border router, best answer first.

    ``vendor_name`` and ``model_name`` are what the user recognises -- an
    "Apple TV" is a thing in the living room, whereas the instance name is
    a hostname with a serial in it. The instance name is still a better
    answer than the raw address, so it comes next.
    """
    vendor = str(getattr(router, "vendor_name", "") or "").strip()
    model = str(getattr(router, "model_name", "") or "").strip()
    if vendor or model:
        return " ".join(part for part in (vendor, model) if part)
    for attribute in ("instance_name", "server", "brand"):
        value = str(getattr(router, attribute, "") or "").strip()
        if value:
            return value
    return address


def _geraet_zum_router(hass: HomeAssistant, router: Any) -> tuple[Any, str | None, str | None]:
    """Das Home-Assistant-Geraet hinter einem Border Router, wenn es eines gibt.

    Ein Border Router ist eine Kiste, die irgendwo steht -- ein Apple TV,
    ein HomePod, ein SkyConnect am Server. Steht sie in Home Assistant,
    hat der Nutzer ihr laengst einen Raum gegeben, und dann gehoert der
    Punkt dorthin statt in die Mitte des Grundrisses.

    Zwei Wege, und der zweite nur, wenn er eindeutig ist:

    1. Die **erweiterte Adresse** unter den Verbindungen des Geraets. Das
       ist eine Kennung, keine Aehnlichkeit -- ein Treffer ist ein Treffer.
    2. Der **mDNS-Hostname** gegen den Geraetenamen. Fuzzy, deshalb nur
       bei genau einem Treffer: zwei HomePods im Haus heissen aehnlich,
       und den falschen zu waehlen ist schlechter als keinen.

    Wie verknuepft wurde, steht am Knoten. Ein Nutzer, der einen Punkt im
    falschen Raum sieht, soll nachsehen koennen, warum.
    """
    try:
        registry = dr.async_get(hass)
    except (AttributeError, KeyError):  # pragma: no cover
        return None, None, None

    eui = str(getattr(router, "extended_address", "") or "").strip().lower()
    if eui:
        for geraet in registry.devices.values():
            for _art, wert in getattr(geraet, "connections", ()) or ():
                if str(wert).strip().lower().replace(":", "") == eui.replace(":", ""):
                    return geraet, "kennung", None

    server = str(getattr(router, "server", "") or "").strip().lower()
    name = server.removesuffix(".").removesuffix(".local")
    if len(name) >= 4:
        treffer = [
            geraet
            for geraet in registry.devices.values()
            if name in str(
                getattr(geraet, "name_by_user", None)
                or getattr(geraet, "name", "")
                or ""
            ).strip().lower().replace(" ", "-")
        ]
        if len(treffer) == 1:
            return treffer[0], "hostname", None
    return None, None, None


def _tuer(hass: HomeAssistant, device_id: str) -> str | None:
    """Die Entitaet, die ein Nutzer meint, wenn er auf das Geraet tippt."""
    try:
        registry = er.async_get(hass)
        eintraege = er.async_entries_for_device(
            registry, device_id, include_disabled_entities=False
        )
    except (AttributeError, KeyError, TypeError):  # pragma: no cover
        return None
    if not eintraege:
        return None
    return sorted(
        eintraege,
        key=lambda eintrag: (
            getattr(eintrag, "entity_category", None) is not None,
            eintrag.entity_id,
        ),
    )[0].entity_id


def _router_node(
    hass: HomeAssistant,
    address: str,
    router: Any,
    networks: dict[str, dict[str, Any]],
) -> dict:
    pan = _pan(getattr(router, "extended_pan_id", ""))
    network = networks.get(pan)
    agent = str(getattr(router, "border_agent_id", "") or "").lower()
    # A router that is up but has joined nothing is the interesting failure:
    # it is not broken, it is simply not part of anything.
    unconfigured = bool(getattr(router, "unconfigured", False))
    preferred = bool(network and agent and network["border_agent"] == agent)

    geraet, ueber, _ = _geraet_zum_router(hass, router)

    return node(
        f"router-{address}",
        label=_router_label(address, router),
        # Wo der Nutzer die Kiste hingestellt hat -- er weiss es, mDNS
        # nicht. Ohne Geraet bleibt beides leer, und der Hub legt den
        # Punkt in die Mitte, was ehrlicher ist als ein geratener Raum.
        area_id=getattr(geraet, "area_id", None) if geraet else None,
        entity_id=_tuer(hass, geraet.id) if geraet else None,
        state="unknown" if unconfigured else "online",
        icon="mdi:router-wireless-off" if unconfigured else (
            "mdi:router-wireless" if preferred else "mdi:access-point"
        ),
        rolle="Border Router",
        hersteller=str(getattr(router, "vendor_name", "") or ""),
        modell=str(getattr(router, "model_name", "") or ""),
        marke=str(getattr(router, "brand", "") or ""),
        thread_version=str(getattr(router, "thread_version", "") or ""),
        netzwerk=(network or {}).get("name") or _UNKNOWN_NETWORK,
        # The two flags that between them explain every "my sensor will not
        # join" in a house with more than one border router.
        bevorzugt="ja" if preferred else "nein",
        eingerichtet="nein" if unconfigured else "ja",
        adresse=address,
        # Wie die Verknuepfung zustande kam, damit ein Punkt im falschen
        # Raum nachvollziehbar ist statt nur falsch.
        **({"verknuepft_ueber": ueber} if ueber else {}),
    )


def async_setup_spatial(hass: HomeAssistant, entry: Any) -> None:
    """Start router discovery and register the layer.

    Called without awaiting, like every other adapter's setup. Discovery
    itself is async and is started as a background task on the config
    entry, so it is torn down with the entry and never outlives it.
    """
    routers: dict[str, Any] = {}
    provider: Any = None

    def _changed() -> None:
        if provider is not None:
            provider.async_notify()

    def router_discovered(address: str, router: Any) -> None:
        routers[address] = router
        _changed()

    def router_removed(address: str) -> None:
        routers.pop(address, None)
        _changed()

    async def data() -> dict[str, list]:
        networks = await _networks(hass)

        nodes = []
        edges = []
        # Only networks that something actually serves, plus every network
        # the store knows. A stored network with no router is worth seeing:
        # it is exactly what a house looks like after a border router dies.
        for pan, network in networks.items():
            nodes.append(
                node(
                    f"network-{pan}",
                    label=network["name"],
                    state="online",
                    icon="mdi:lan" if network["preferred"] else "mdi:lan-pending",
                    rolle="Thread-Netzwerk",
                    kanal=network["channel"],
                    pan_id=pan,
                    bevorzugt="ja" if network["preferred"] else "nein",
                    quelle=network["source"],
                )
            )

        for address, router in sorted(routers.items()):
            nodes.append(_router_node(hass, address, router, networks))
            pan = _pan(getattr(router, "extended_pan_id", ""))
            if pan in networks:
                edges.append(
                    edge(
                        f"router-{address}",
                        f"network-{pan}",
                        quality="unknown",
                        directed=True,
                    )
                )
            elif pan:
                # A router on a network this installation has no dataset
                # for. Drawn, because "there is a second Thread network in
                # this house and you do not have its credentials" is the
                # single most useful thing this layer can say.
                foreign = f"network-{pan}"
                if not any(item["id"] == foreign for item in nodes):
                    nodes.append(
                        node(
                            foreign,
                            label=str(
                                getattr(router, "network_name", "") or "Fremdes Netz"
                            ),
                            state="unknown",
                            icon="mdi:lan-disconnect",
                            rolle="Thread-Netzwerk",
                            pan_id=pan,
                            bekannt="nein",
                        )
                    )
                edges.append(
                    edge(
                        f"router-{address}", foreign,
                        quality="unknown", directed=True, dashed=True,
                    )
                )

        return {"nodes": nodes, "edges": edges}

    provider = spatial_provider(
        hass,
        entry,
        name="Thread",
        icon="mdi:access-point-network",
        data=data,
        version="260808",
    )

    try:
        from homeassistant.components.thread.discovery import ThreadRouterDiscovery
    except ImportError:  # pragma: no cover - core ships it
        _LOGGER.debug("Thread router discovery unavailable")
    else:
        discovery = ThreadRouterDiscovery(hass, router_discovered, router_removed)
        entry.async_create_background_task(
            hass, discovery.async_start(), "spatial_thread discovery"
        )
        entry.async_on_unload(
            lambda: hass.async_create_task(discovery.async_stop())
        )

    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda _now: provider.async_notify(), REFRESH
        )
    )
