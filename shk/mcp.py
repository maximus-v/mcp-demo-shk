"""MCP-Server für die SHK-Demo (django-mcp-server).

Stellt fünf Tools über den Streamable-HTTP-Endpoint ``/mcp`` bereit – drei
lesende Auswertungen und zwei schreibende Erfassungs-Tools:

* ``log_projekttagebuch``        (schreibend)
* ``get_projekt_status``         (lesend)
* ``get_budget_status``          (lesend)
* ``get_abrechenbare_vorgaenge`` (lesend)
* ``erstelle_rechnung``          (schreibend)

Die Mapping-/Schreiblogik liegt in modulweiten Funktionen (ohne MCP-Schicht
testbar); die Toolset-Methoden sind dünne Wrapper, deren Docstrings als
Tool-Beschreibung dienen und bewusst trennscharf formuliert sind, damit ein LLM
bei fünf Tools sicher das richtige auswählt.
"""

from decimal import Decimal
from typing import Annotated, Optional

from django.db import transaction
from django.utils import timezone
from mcp_server import MCPToolset
from pydantic import Field

from shk.models import (
    Materialposition,
    Monteur,
    Produkt,
    Projekt,
    Projektvorgang,
    Projekttagebuch,
    Rechnung,
    VorgangStatus,
)

# Projekt gilt als budgetgefährdet ab dieser Auslastung (Ist / Kostenvoranschlag).
GEFAEHRDET_SCHWELLE = 0.9


def _f(wert):
    """Decimal/Number → gerundeter float für JSON-Ausgabe."""
    if wert is None:
        return None
    return round(float(wert), 2)


# --------------------------------------------------------------------------- #
# Lesende Serializer (pure functions)
# --------------------------------------------------------------------------- #
def _projekte_mit_aufwand():
    return (
        Projekt.objects
        .prefetch_related("vorgaenge__tagebuch_eintraege__materialpositionen__produkt")
        .order_by("nummer")
    )


def build_projekt_status():
    """Output von get_projekt_status: Projektstatus + Verzug, plus Projekttyp-Aggregation."""
    projekte_out = []
    agg = {}

    for p in _projekte_mit_aufwand():
        vorgaenge = list(p.vorgaenge.all())
        ueberfaellig = [v for v in vorgaenge if v.ist_ueberfaellig]
        aus_plan = [v for v in vorgaenge if v.laeuft_aus_plan]
        projekt_aus_plan = p.laeuft_aus_plan

        projekte_out.append({
            "nummer": p.nummer,
            "titel": p.titel,
            "projekttyp": p.projekttyp,
            "projektart": p.projektart,
            "status": p.status,
            "enddatum": p.enddatum.isoformat(),
            "projekt_laeuft_aus_plan": projekt_aus_plan,
            "vorgaenge_ueberfaellig": {
                "anzahl": len(ueberfaellig),
                "liste": [
                    {"bezeichnung": v.bezeichnung, "enddatum": v.enddatum.isoformat()}
                    for v in ueberfaellig
                ],
            },
            "vorgaenge_aus_plan": {
                "anzahl": len(aus_plan),
                "liste": [
                    {
                        "bezeichnung": v.bezeichnung,
                        "enddatum": v.enddatum.isoformat(),
                        "restaufwand_stunden": _f(v.restaufwand),
                    }
                    for v in aus_plan
                ],
            },
        })

        a = agg.setdefault(p.projekttyp, {
            "projekte": 0, "vorgaenge_ueberfaellig": 0,
            "vorgaenge_aus_plan": 0, "projekte_aus_plan": 0,
            "_ausl_sum": 0.0, "_ausl_n": 0,
        })
        a["projekte"] += 1
        a["vorgaenge_ueberfaellig"] += len(ueberfaellig)
        a["vorgaenge_aus_plan"] += len(aus_plan)
        a["projekte_aus_plan"] += 1 if projekt_aus_plan else 0
        if p.budgetauslastung is not None:
            a["_ausl_sum"] += float(p.budgetauslastung)
            a["_ausl_n"] += 1

    aggregation = []
    for typ, a in agg.items():
        avg = round(a["_ausl_sum"] / a["_ausl_n"], 3) if a["_ausl_n"] else None
        aggregation.append({
            "projekttyp": typ,
            "projekte": a["projekte"],
            "vorgaenge_ueberfaellig": a["vorgaenge_ueberfaellig"],
            "vorgaenge_aus_plan": a["vorgaenge_aus_plan"],
            "projekte_aus_plan": a["projekte_aus_plan"],
            "durchschnittliche_budgetauslastung": avg,
        })
    # schwächster Typ zuerst (meiste überfällige Vorgänge, dann höchste Auslastung)
    aggregation.sort(
        key=lambda x: (x["vorgaenge_ueberfaellig"], x["durchschnittliche_budgetauslastung"] or 0),
        reverse=True,
    )

    return {"projekte": projekte_out, "aggregation_nach_projekttyp": aggregation}


def build_budget_status():
    """Output von get_budget_status: Soll/Ist-Kosten und Budgetauslastung je Projekt."""
    projekte = []
    for p in _projekte_mit_aufwand():
        ausl = p.budgetauslastung
        projekte.append({
            "nummer": p.nummer,
            "titel": p.titel,
            "projekttyp": p.projekttyp,
            "kostenvoranschlag": _f(p.kostenvoranschlag),
            "ist_kosten": _f(p.ist_kosten),
            "budgetauslastung": round(float(ausl), 3) if ausl is not None else None,
            "gefaehrdet": bool(ausl is not None and ausl > GEFAEHRDET_SCHWELLE),
        })
    return {"projekte": projekte, "gefaehrdet_schwelle": GEFAEHRDET_SCHWELLE}


def build_abrechenbare_vorgaenge():
    """Output von get_abrechenbare_vorgaenge: abgeschlossene, nicht abgerechnete Vorgänge
    mit Betragsaufschlüsselung als Prüfgrundlage im Chat."""
    vorgaenge = (
        Projektvorgang.objects
        .filter(status=VorgangStatus.ABGESCHLOSSEN, abgerechnet=False)
        .select_related("projekt")
        .prefetch_related("tagebuch_eintraege__materialpositionen__produkt")
        .order_by("projekt__nummer", "id")
    )
    out = []
    for v in vorgaenge:
        auf = v.rechnungsaufschluesselung()
        if auf["summe"] <= 0:
            continue
        out.append({
            "vorgang_id": v.id,
            "projekt_nummer": v.projekt.nummer,
            "projekt_titel": v.projekt.titel,
            "bezeichnung": v.bezeichnung,
            "personalkosten": _f(auf["personalkosten"]),
            "materialkosten": _f(auf["produktsumme"]),
            "werkstoffpauschale": _f(auf["werkstoffpauschale"]),
            "summe": _f(auf["summe"]),
        })
    return out


# --------------------------------------------------------------------------- #
# Schreibende Helper (transaktional)
# --------------------------------------------------------------------------- #
def _einzigartig(qs, gesucht, fehler_basis, kandidaten_fn):
    """Genau-1-Treffer-Auflösung; sonst strukturierter Fehler mit Kandidaten."""
    treffer = list(qs)
    if len(treffer) == 0:
        return None, {"error": f"{fehler_basis}_nicht_gefunden", "gesucht": gesucht,
                      "kandidaten": kandidaten_fn()}
    if len(treffer) > 1:
        return None, {"error": f"{fehler_basis}_mehrdeutig", "gesucht": gesucht,
                      "kandidaten": [kandidaten_fn(t) for t in treffer]}
    return treffer[0], None


def log_tagebuch_eintrag(projekt, monteur, vorgang, stunden,
                         materialpositionen=None, fortschritt="", abgeschlossen=False):
    """Legt einen Tagebucheintrag + Materialpositionen an. Identifiziert Projekt
    (Nummer oder Titel/Adresse), Monteur und Vorgang per Name/Bezeichnung. Material
    zwingend auf Katalog-Produkte gemappt – unbekanntes Produkt lehnt die Aktion ab.
    Bei ``abgeschlossen=True`` wird der Vorgangsstatus auf Abgeschlossen gesetzt."""
    materialpositionen = materialpositionen or []

    # Projekt: erst Nummer (exakt), sonst Titel (contains)
    p_qs = Projekt.objects.filter(nummer__iexact=projekt)
    if not p_qs.exists():
        p_qs = Projekt.objects.filter(titel__icontains=projekt)
    p, err = _einzigartig(
        p_qs, projekt, "projekt",
        lambda t=None: [{"nummer": x.nummer, "titel": x.titel} for x in (Projekt.objects.all() if t is None else [t])][:8],
    )
    if err:
        return err

    # Monteur
    m, err = _einzigartig(
        Monteur.objects.filter(name__icontains=monteur), monteur, "monteur",
        lambda t=None: [x.name for x in (Monteur.objects.all() if t is None else [t])],
    )
    if err:
        return err

    # Vorgang innerhalb des Projekts
    v, err = _einzigartig(
        p.vorgaenge.filter(bezeichnung__icontains=vorgang), vorgang, "vorgang",
        lambda t=None: [x.bezeichnung for x in (p.vorgaenge.all() if t is None else [t])],
    )
    if err:
        return err

    # Produkte VORAB auflösen (alles ablehnen, falls eines unbekannt) – nichts schreiben
    aufzulegen = []
    for pos in materialpositionen:
        bez = pos.get("produkt")
        menge = pos.get("menge")
        if not bez or menge is None:
            return {"error": "materialposition_unvollstaendig", "position": pos}
        prod, perr = _einzigartig(
            Produkt.objects.filter(bezeichnung__icontains=bez), bez, "produkt",
            lambda t=None: [x.bezeichnung for x in (Produkt.objects.all() if t is None else [t])],
        )
        if perr:
            # einheitlicher Schlüssel für die Chat-Rückfrage
            perr["unbekanntes_produkt"] = bez
            return perr
        aufzulegen.append((prod, Decimal(str(menge))))

    with transaction.atomic():
        eintrag = Projekttagebuch.objects.create(
            projekt=p, vorgang=v, monteur=m,
            stunden=Decimal(str(stunden)), text=fortschritt or "",
        )
        for prod, menge in aufzulegen:
            Materialposition.objects.create(eintrag=eintrag, produkt=prod, menge=menge)
        if abgeschlossen and v.status != VorgangStatus.ABGESCHLOSSEN:
            v.status = VorgangStatus.ABGESCHLOSSEN
            v.save(update_fields=["status"])

    return {
        "ok": True,
        "eintrag_id": eintrag.id,
        "projekt": p.nummer,
        "projekt_titel": p.titel,
        "vorgang": v.bezeichnung,
        "monteur": m.name,
        "stunden": _f(eintrag.stunden),
        "materialpositionen": [
            {"produkt": prod.bezeichnung, "menge": _f(menge)} for prod, menge in aufzulegen
        ],
        "vorgang_status": v.status,
        "restaufwand_stunden": _f(v.restaufwand),
    }


def erstelle_rechnung_fuer_vorgang(vorgang_id, request=None):
    """Schreibt die finale Rechnung für einen abgeschlossenen, noch nicht
    abgerechneten Vorgang, markiert ihn als abgerechnet und liefert den View-Link.
    Doppelabrechnung wird über das ``abgerechnet``-Flag verhindert."""
    v = Projektvorgang.objects.filter(pk=vorgang_id).select_related("projekt").first()
    if v is None:
        return {"error": "vorgang_nicht_gefunden", "vorgang_id": vorgang_id}
    if v.abgerechnet:
        best = Rechnung.objects.filter(vorgang=v).first()
        return {"error": "bereits_abgerechnet", "vorgang_id": vorgang_id,
                "rechnungsnummer": best.nummer if best else None}
    if v.status != VorgangStatus.ABGESCHLOSSEN:
        return {"error": "nicht_abrechenbar", "grund": "Vorgang ist nicht abgeschlossen",
                "vorgang_id": vorgang_id, "status": v.status}

    with transaction.atomic():
        v = Projektvorgang.objects.select_for_update().select_related("projekt").get(pk=vorgang_id)
        if v.abgerechnet:  # Re-Check unter Lock
            return {"error": "bereits_abgerechnet", "vorgang_id": vorgang_id}
        nummer = f"RE-{timezone.now().year}-{Rechnung.objects.count() + 1:04d}"
        betrag = v.rechnungsbetrag.quantize(Decimal("0.01"))
        rechnung = Rechnung.objects.create(
            nummer=nummer, projekt=v.projekt, vorgang=v, betrag=betrag,
        )
        v.abgerechnet = True
        v.save(update_fields=["abgerechnet"])

    url = rechnung.view_url
    if request is not None:
        url = request.build_absolute_uri(url)
    return {"rechnungsnummer": rechnung.nummer, "betrag": _f(rechnung.betrag), "url": url}


# --------------------------------------------------------------------------- #
# MCP-Tools. Docstring = Tool-Beschreibung, Type-Hints/Annotated = Schema.
# --------------------------------------------------------------------------- #
class ShkTools(MCPToolset):
    def log_projekttagebuch(
        self,
        projekt: Annotated[str, Field(description="Projekt: Adresse/Titel (z. B. 'Wettiner Str. 12') ODER Projektnummer (z. B. 'PR10001').")],
        monteur: Annotated[str, Field(description="Name des erfassenden Monteurs.")],
        vorgang: Annotated[str, Field(description="Bezeichnung des Vorgangs im Projekt, z. B. 'Installation Wärmepumpe'.")],
        stunden: Annotated[float, Field(description="Für diesen Eintrag aufgewendete Stunden.")],
        materialpositionen: Annotated[Optional[list[dict]], Field(description="Verbrauchtes Material als Liste von Objekten {\"produkt\": Katalogbezeichnung, \"menge\": Zahl}. Nur Katalog-Produkte sind erlaubt; Werkstoffe (Schrauben etc.) NICHT erfassen.")] = None,
        fortschritt: Annotated[str, Field(description="Kurzes Fortschritts-Update (Freitext).")] = "",
        abgeschlossen: Annotated[bool, Field(description="True, wenn der Vorgang mit diesem Eintrag abgeschlossen ist (setzt den Vorgangsstatus auf Abgeschlossen).")] = False,
    ) -> dict:
        """(SCHREIBEND) Erfasst einen Projekttagebuch-Eintrag eines Monteurs nach dem
        Verlassen der Baustelle: aufgewendete Stunden, verbrauchtes Material und ein
        Fortschritts-Update zu einem Vorgang. Nutze dieses Tool zum **Dokumentieren von
        Arbeit** („Ich war heute bei … und habe … gemacht / verbaut"). Material muss auf
        Katalog-Produkte gemappt sein; ein unbekanntes Produkt führt zur Ablehnung ohne
        Schreiben. Bei mehrdeutigem/unbekanntem Projekt werden Kandidaten zurückgegeben.
        NICHT für Auswertungen oder Rechnungen verwenden."""
        return log_tagebuch_eintrag(projekt, monteur, vorgang, stunden,
                                    materialpositionen, fortschritt, abgeschlossen)

    def get_projekt_status(self) -> dict:
        """(LESEND) Statusüberblick ALLER Projekte mit Fokus auf zeitlichen Verzug.
        Kein Eingabeparameter. Nutze dieses Tool für Fragen wie „Welche Projekte laufen
        aus dem Plan / haben überfällige Vorgänge?" oder „Welcher Projekttyp läuft
        schlechter?". Liefert je Projekt Nummer, Titel, Projekttyp, Status, überfällige
        Vorgänge (Anzahl + Liste) und „läuft aus dem Plan"-Vorgänge, plus eine
        Aggregation nach Projekttyp (für den Vergleich der Typen)."""
        return build_projekt_status()

    def get_budget_status(self) -> dict:
        """(LESEND) Budgetüberblick ALLER Projekte. Kein Eingabeparameter. Nutze dieses
        Tool für Fragen wie „Wo wird das Budget eng?" oder „Welche Projekte sind über
        Budget?". Liefert je Projekt Kostenvoranschlag, Ist-Kosten (Personal + Material
        inkl. Werkstoffpauschale), Budgetauslastung und eine Kennzeichnung gefährdeter
        Projekte."""
        return build_budget_status()

    def get_abrechenbare_vorgaenge(self) -> list:
        """(LESEND) Liste der abgeschlossenen, noch NICHT abgerechneten Vorgänge mit
        Betragsaufschlüsselung (Personal, Material, Werkstoffpauschale, Summe). Kein
        Eingabeparameter. Nutze dieses Tool als **Prüfgrundlage vor der Rechnung**
        („Was kann ich abrechnen?"). Jeder Eintrag enthält eine ``vorgang_id``, die du
        anschließend an ``erstelle_rechnung`` übergibst."""
        return build_abrechenbare_vorgaenge()

    def erstelle_rechnung(
        self,
        vorgang_id: Annotated[int, Field(description="ID des abzurechnenden Vorgangs aus get_abrechenbare_vorgaenge (Feld 'vorgang_id').")],
    ) -> dict:
        """(SCHREIBEND) Schreibt die finale Rechnung für einen geprüften, abgeschlossenen
        Vorgang, markiert ihn als abgerechnet und gibt ``{rechnungsnummer, betrag, url}``
        zurück (url verweist auf die HTML-Rechnungs-View). Erst nach Prüfung der Beträge
        via ``get_abrechenbare_vorgaenge`` aufrufen. Doppelabrechnung wird verhindert: ein
        bereits abgerechneter Vorgang wird abgelehnt."""
        return erstelle_rechnung_fuer_vorgang(vorgang_id, request=self.request)
