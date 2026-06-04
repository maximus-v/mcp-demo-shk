"""Erzeugt den Demo-/Seed-Datensatz für die SHK-MCP-Demo.

Generiert deterministisch den Produktkatalog, 10 Monteure und 20 Projekte
(50 % Privatperson mit 1 Monteur, 50 % Großbaustelle mit mehreren Monteuren),
inkl. Vorgängen, Projekttagebuch-Einträgen und Materialpositionen.

Gestaffelter Reifegrad über Tiers (``schlecht``, ``budget``, ``mittel``,
``gut``):
  * ``schlecht`` – Vorgänge überfällig und "aus dem Plan".
  * ``budget``   – hoher Aufwand/teures Material gegen knappen Kostenvoranschlag
                   → Budgetauslastung > 100 %.
  * ``mittel``   – überwiegend planmäßig, einzelne offene Punkte.
  * ``gut``      – planmäßig; enthält abgeschlossene, noch nicht abgerechnete
                   Vorgänge für die Rechnungs-Demo (TICKET-4).

Der Projekttyp **Wärmepumpe** ist bewusst überproportional schwach besetzt,
sodass die Projekttyp-Aggregation ihn als schlechter laufenden Typ ausweist.

Alle Datumswerte werden relativ zum Demo-Tag (Default 2026-06-09) erzeugt;
überfällige Objekte liegen deutlich davor, sodass sie auch an früheren
Ausführungstagen greifen. Der **Betrieb** ist eine Modul-Konstante
(``shk.models.BETRIEB_*``) und wird nicht als Datensatz geseedet.

Beispiele:
    python manage.py seed_demo --flush
    python manage.py seed_demo --flush --reference-date 2026-06-09
    python manage.py seed_demo --flush --dump shk/fixtures/demo_seed.json
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from shk.models import (
    BETRIEB_NAME,
    Materialposition,
    Monteur,
    Produkt,
    Projekt,
    Projektart,
    Projekttagebuch,
    ProjektStatus,
    ProjektTyp,
    Projektvorgang,
    Rechnung,
    STUNDENSATZ,
    VorgangStatus,
)

SEED = 20260609
DEFAULT_REFERENCE = "2026-06-09"
DEFAULT_DUMP_PATH = "shk/fixtures/demo_seed.json"

# --------------------------------------------------------------------------- #
# Stammdaten-Pools
# --------------------------------------------------------------------------- #
MONTEURE = [
    "Mario Köhler", "Sven Bauer", "Dennis Richter", "Tobias Wolf",
    "André Schmidt", "Patrick Krause", "Marcel Hoffmann", "Kevin Lehmann",
    "Stefan Vogel", "Robert Neumann",
]

# (Bezeichnung, Verkaufspreis, Einheit)
PRODUKTE = [
    ("Wärmepumpe Luft/Wasser 8 kW", "8500.00", "Stk."),
    ("Wärmepumpe Sole/Wasser 12 kW", "13500.00", "Stk."),
    ("Pufferspeicher 300 L", "950.00", "Stk."),
    ("Warmwasserspeicher 300 L", "1100.00", "Stk."),
    ("Hydraulische Weiche", "280.00", "Stk."),
    ("Mischer-/Regelgruppe", "340.00", "Stk."),
    ("Fußbodenheizung-Set 80 m²", "1800.00", "Set"),
    ("Heizkörper Typ 22", "180.00", "Stk."),
    ("PV-Modul 430 Wp", "95.00", "Stk."),
    ("Wechselrichter 8 kW", "1450.00", "Stk."),
    ("Batteriespeicher 10 kWh", "6800.00", "Stk."),
    ("Montagegestell PV", "45.00", "m"),
    ("Smart-Meter / Energiemanager", "520.00", "Stk."),
    ("Solarthermie-Flachkollektor", "480.00", "Stk."),
    ("Solarthermie-Komplettpaket", "3200.00", "Set"),
]

# Vorgangsnamen je Projekttyp
VORGAENGE = {
    ProjektTyp.WAERMEPUMPE: [
        "Demontage Altanlage", "Installation Wärmepumpe",
        "Hydraulik & Pufferspeicher", "Inbetriebnahme & Einregulierung",
    ],
    ProjektTyp.PV: [
        "Unterkonstruktion & Gerüst", "Modulmontage",
        "Wechselrichter & Verkabelung", "Netzanschluss & Inbetriebnahme",
    ],
    ProjektTyp.SOLARTHERMIE: [
        "Kollektormontage Dach", "Speicher & Hydraulik", "Inbetriebnahme",
    ],
    ProjektTyp.BAD: [
        "Demontage & Rohbau", "Rohinstallation Sanitär",
        "Fliesen & Montage", "Endmontage & Abnahme",
    ],
}

# Material-Pools je Projekttyp: (Bezeichnung, menge_min, menge_max)
MATERIAL_POOL = {
    ProjektTyp.WAERMEPUMPE: [
        ("Wärmepumpe Luft/Wasser 8 kW", 1, 1), ("Pufferspeicher 300 L", 1, 1),
        ("Warmwasserspeicher 300 L", 1, 1), ("Hydraulische Weiche", 1, 2),
        ("Mischer-/Regelgruppe", 1, 2), ("Fußbodenheizung-Set 80 m²", 1, 1),
        ("Heizkörper Typ 22", 3, 8),
    ],
    ProjektTyp.PV: [
        ("PV-Modul 430 Wp", 12, 24), ("Wechselrichter 8 kW", 1, 1),
        ("Batteriespeicher 10 kWh", 1, 1), ("Montagegestell PV", 20, 55),
        ("Smart-Meter / Energiemanager", 1, 1),
    ],
    ProjektTyp.SOLARTHERMIE: [
        ("Solarthermie-Flachkollektor", 2, 5), ("Solarthermie-Komplettpaket", 1, 1),
        ("Warmwasserspeicher 300 L", 1, 1), ("Mischer-/Regelgruppe", 1, 1),
        ("Pufferspeicher 300 L", 1, 1),
    ],
    ProjektTyp.BAD: [
        ("Heizkörper Typ 22", 2, 5), ("Fußbodenheizung-Set 80 m²", 1, 1),
        ("Mischer-/Regelgruppe", 1, 1), ("Warmwasserspeicher 300 L", 1, 1),
    ],
}

TAGEBUCH_TEXTE = {
    "fortschritt": [
        "Arbeiten planmäßig fortgesetzt, keine Auffälligkeiten.",
        "Material angeliefert und verbaut, Anschluss vorbereitet.",
        "Montage abgeschnitten, weiter geht es nächste Woche.",
        "Kunde informiert, Zwischenstand abgestimmt.",
    ],
    "problem": [
        "Verzögerung: Altanlage komplizierter als erwartet, mehr Aufwand nötig.",
        "Lieferung verspätet, Restarbeiten verschieben sich.",
        "Zusätzliche Anpassungen an der Hydraulik erforderlich.",
        "Witterung/Zugang erschwert den Fortschritt deutlich.",
    ],
    "abschluss": [
        "Vorgang abgeschlossen, Funktionsprüfung erfolgreich.",
        "Endmontage erledigt, Anlage übergeben.",
        "Inbetriebnahme abgeschlossen, Messwerte im Sollbereich.",
    ],
}

# --------------------------------------------------------------------------- #
# Projekt-Spezifikationen (20 Projekte)
# nummer, titel (Adresse), typ, art, tier
# Privatperson → 1 Monteur, Großbaustelle → mehrere Monteure
# --------------------------------------------------------------------------- #
WP, PV, ST, BAD = (ProjektTyp.WAERMEPUMPE, ProjektTyp.PV,
                   ProjektTyp.SOLARTHERMIE, ProjektTyp.BAD)
PRIV, GROSS = Projektart.PRIVATPERSON, Projektart.GROSSBAUSTELLE

PROJEKT_SPECS = [
    # Wärmepumpe (8) – bewusst schwacher Typ
    dict(nummer="PR10001", titel="Wettiner Str. 12, 01067 Dresden", typ=WP, art=PRIV, tier="schlecht"),
    dict(nummer="PR10002", titel="Industriegelände Hamburger Str. 60, 01067 Dresden", typ=WP, art=GROSS, tier="schlecht"),
    dict(nummer="PR10003", titel="Bautzner Str. 45, 01099 Dresden", typ=WP, art=PRIV, tier="budget"),
    dict(nummer="PR10004", titel="Wohnpark Pieschener Allee 8, 01067 Dresden", typ=WP, art=GROSS, tier="budget"),
    dict(nummer="PR10005", titel="Tharandter Str. 21, 01159 Dresden", typ=WP, art=PRIV, tier="mittel"),
    dict(nummer="PR10006", titel="Gewerbehof Meißner Str. 30, 01445 Radebeul", typ=WP, art=GROSS, tier="schlecht"),
    dict(nummer="PR10007", titel="Comeniusstr. 99, 01309 Dresden", typ=WP, art=PRIV, tier="mittel"),
    dict(nummer="PR10008", titel="Quartier Löbtauer Str. 50, 01159 Dresden", typ=WP, art=GROSS, tier="gut"),
    # PV (6) – starker Typ
    dict(nummer="PR10009", titel="Logistikzentrum Großenhainer Str. 120, 01129 Dresden", typ=PV, art=GROSS, tier="gut"),
    dict(nummer="PR10010", titel="Kötzschenbroder Str. 7, 01139 Dresden", typ=PV, art=PRIV, tier="gut"),
    dict(nummer="PR10011", titel="Schulcampus Boxdorfer Str. 3, 01468 Moritzburg", typ=PV, art=GROSS, tier="gut"),
    dict(nummer="PR10012", titel="Rietzstr. 14, 01187 Dresden", typ=PV, art=PRIV, tier="mittel"),
    dict(nummer="PR10013", titel="Produktionshalle Reicker Str. 88, 01237 Dresden", typ=PV, art=GROSS, tier="mittel"),
    dict(nummer="PR10014", titel="Pillnitzer Landstr. 33, 01326 Dresden", typ=PV, art=PRIV, tier="gut"),
    # Solarthermie (4)
    dict(nummer="PR10015", titel="Kipsdorfer Str. 5, 01277 Dresden", typ=ST, art=PRIV, tier="gut"),
    dict(nummer="PR10016", titel="Sportzentrum Bodenbacher Str. 154, 01277 Dresden", typ=ST, art=GROSS, tier="mittel"),
    dict(nummer="PR10017", titel="Wachwitzer Höhenweg 2, 01326 Dresden", typ=ST, art=PRIV, tier="gut"),
    dict(nummer="PR10018", titel="Hotelanlage Bautzner Landstr. 200, 01324 Dresden", typ=ST, art=GROSS, tier="schlecht"),
    # Bad (2)
    dict(nummer="PR10019", titel="Hepkestr. 41, 01309 Dresden", typ=BAD, art=PRIV, tier="mittel"),
    dict(nummer="PR10020", titel="Seniorenresidenz Niederwaldstr. 10, 01277 Dresden", typ=BAD, art=GROSS, tier="gut"),
]


class Command(BaseCommand):
    help = "Erzeugt den SHK-Demo-Seed (relativ zum Demo-Tag) und dumpt optional ein JSON-Fixture."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reference-date", default=DEFAULT_REFERENCE,
            help=f"Demo-Tag als YYYY-MM-DD (Default {DEFAULT_REFERENCE}); Überfälligkeit greift relativ hierzu.",
        )
        parser.add_argument(
            "--flush", action="store_true",
            help="Bestehende shk-Daten vor dem Seeden löschen.",
        )
        parser.add_argument(
            "--dump", nargs="?", const=DEFAULT_DUMP_PATH, default=None,
            help=f"Nach dem Seeden ein JSON-Fixture schreiben (Default-Pfad {DEFAULT_DUMP_PATH}).",
        )

    def handle(self, *args, **options):
        try:
            ref = date.fromisoformat(options["reference_date"])
        except ValueError:
            raise CommandError("--reference-date muss im Format YYYY-MM-DD vorliegen.")

        self.ref = ref
        self.rng = random.Random(SEED)

        with transaction.atomic():
            if options["flush"]:
                self._flush()
            self._seed()

        self._report(ref)

        dump_path = options["dump"]
        if dump_path:
            self._dump(dump_path)

    # ----------------------------------------------------------------- #
    # Helpers
    # ----------------------------------------------------------------- #
    def _d(self, offset_days):
        return self.ref + timedelta(days=offset_days)

    def _dt(self, offset_days):
        naive = datetime.combine(self._d(offset_days), time(hour=9))
        return timezone.make_aware(naive)

    def _flush(self):
        Rechnung.objects.all().delete()
        Materialposition.objects.all().delete()
        Projekttagebuch.objects.all().delete()
        Projektvorgang.objects.all().delete()
        Monteur.objects.all().delete()  # leert auch die M2M-Zuordnung
        Projekt.objects.all().delete()
        Produkt.objects.all().delete()
        self.stdout.write("Bestehende shk-Daten gelöscht.")

    # ----------------------------------------------------------------- #
    # Seeding
    # ----------------------------------------------------------------- #
    def _seed(self):
        self.produkte = {
            bez: Produkt.objects.create(bezeichnung=bez, verkaufspreis=Decimal(preis), einheit=einheit)
            for bez, preis, einheit in PRODUKTE
        }
        self.monteure = [Monteur.objects.create(name=name) for name in MONTEURE]

        for spec in PROJEKT_SPECS:
            self._seed_project(spec)

    def _seed_project(self, spec):
        rng = self.rng
        typ, art, tier = spec["typ"], spec["art"], spec["tier"]

        projekt = Projekt.objects.create(
            nummer=spec["nummer"],
            titel=spec["titel"],
            projekttyp=typ,
            projektart=art,
            status=ProjektStatus.IN_BEARBEITUNG,
            enddatum=self._d(rng.randint(-20, 90)),
            kostenvoranschlag=Decimal("0"),  # final nach Aufwandsberechnung gesetzt
        )

        # Monteur-Zuordnung: Privat = 1, Groß = 2–4
        anzahl = 1 if art == PRIV else rng.randint(2, 4)
        team = rng.sample(self.monteure, k=anzahl)
        for m in team:
            m.projekte.add(projekt)

        self._seed_vorgaenge(projekt, typ, tier, team)
        self._finalize(projekt, tier)

    def _seed_vorgaenge(self, projekt, typ, tier, team):
        rng = self.rng
        namen = VORGAENGE[typ]
        art_faktor = Decimal("1.0") if projekt.projektart == PRIV else Decimal("1.8")
        n = len(namen)
        gab_abrechenbar = False

        for i, name in enumerate(namen):
            soll = (Decimal(rng.randint(16, 40)) * art_faktor).quantize(Decimal("1"))
            status, end_off, abgerechnet, frac = self._vorgang_plan(tier, i, n, rng)

            # Garantie: in jedem "gut"-Projekt mind. ein abgeschlossener,
            # nicht abgerechneter Vorgang (Rechnungs-Demo).
            if tier == "gut" and status == VorgangStatus.ABGESCHLOSSEN and not gab_abrechenbar:
                abgerechnet = False
                gab_abrechenbar = True

            vorgang = Projektvorgang.objects.create(
                projekt=projekt, bezeichnung=name,
                soll_aufwand=soll, enddatum=self._d(end_off),
                status=status, abgerechnet=abgerechnet,
            )

            if frac > 0:
                self._seed_tagebuch(projekt, vorgang, typ, tier, team, soll, frac, end_off)

    def _vorgang_plan(self, tier, i, n, rng):
        """(status, enddatum_offset, abgerechnet, logged_fraction) je Vorgang/Tier."""
        if tier == "schlecht":
            if i == 0:
                return VorgangStatus.ABGESCHLOSSEN, rng.randint(-120, -70), rng.random() < 0.5, 1.0
            if i == 1:
                # überfällig UND aus dem Plan: offen, Enddatum klar in der Vergangenheit,
                # wenig geleistet → Restaufwand groß
                return VorgangStatus.IN_BEARBEITUNG, rng.randint(-45, -15), False, rng.uniform(0.25, 0.45)
            return VorgangStatus.GEPLANT, rng.randint(15, 90), False, 0.0

        if tier == "budget":
            if i < n - 1:
                # viel (teils Mehr-)Aufwand → treibt Ist-Kosten über knappes Budget
                return VorgangStatus.ABGESCHLOSSEN, rng.randint(-90, -20), rng.random() < 0.3, rng.uniform(1.05, 1.35)
            return VorgangStatus.IN_BEARBEITUNG, rng.randint(-10, 20), False, rng.uniform(0.6, 0.9)

        if tier == "mittel":
            if i == 0:
                return VorgangStatus.ABGESCHLOSSEN, rng.randint(-110, -30), rng.random() < 0.6, rng.uniform(0.95, 1.1)
            if i < n - 1:
                return VorgangStatus.IN_BEARBEITUNG, rng.randint(10, 70), False, rng.uniform(0.4, 0.7)
            return VorgangStatus.GEPLANT, rng.randint(40, 120), False, 0.0

        # gut
        if i < n - 1:
            return VorgangStatus.ABGESCHLOSSEN, rng.randint(-160, -20), rng.random() < 0.35, rng.uniform(0.9, 1.1)
        return VorgangStatus.IN_BEARBEITUNG, rng.randint(20, 100), False, rng.uniform(0.3, 0.5)

    def _seed_tagebuch(self, projekt, vorgang, typ, tier, team, soll, frac, end_off):
        rng = self.rng
        gesamt_stunden = (soll * Decimal(str(frac))).quantize(Decimal("0.5"))
        if gesamt_stunden <= 0:
            return
        k = rng.randint(1, 3)
        # Stunden auf k Einträge verteilen
        anteile = [rng.random() for _ in range(k)]
        s = sum(anteile) or 1.0
        rest = gesamt_stunden
        textpool = TAGEBUCH_TEXTE["problem"] if tier in ("schlecht", "budget") else TAGEBUCH_TEXTE["fortschritt"]

        for j in range(k):
            if j == k - 1:
                stunden = rest
            else:
                stunden = (gesamt_stunden * Decimal(str(anteile[j] / s))).quantize(Decimal("0.5"))
                rest -= stunden
            if stunden <= 0:
                continue
            if vorgang.status == VorgangStatus.ABGESCHLOSSEN and j == k - 1:
                text = rng.choice(TAGEBUCH_TEXTE["abschluss"])
            else:
                text = rng.choice(textpool)
            datum_off = end_off - rng.randint(2, 25)
            eintrag = Projekttagebuch.objects.create(
                projekt=projekt, vorgang=vorgang, monteur=rng.choice(team),
                datum=self._dt(datum_off), stunden=stunden, text=text,
            )
            # Material auf ~2/3 der Einträge
            if rng.random() < 0.7:
                self._seed_material(eintrag, typ)

    def _seed_material(self, eintrag, typ):
        rng = self.rng
        pool = MATERIAL_POOL[typ]
        for bez, mmin, mmax in rng.sample(pool, k=rng.randint(1, 2)):
            Materialposition.objects.create(
                eintrag=eintrag, produkt=self.produkte[bez],
                menge=Decimal(rng.randint(mmin, mmax)),
            )

    def _finalize(self, projekt, tier):
        """Kostenvoranschlag relativ zu den tatsächlichen/erwarteten Kosten setzen,
        sodass die Budget-Narrative je Tier eindeutig trägt."""
        rng = self.rng
        ist = projekt.ist_kosten
        offene_reststunden = sum(
            (max(v.restaufwand, Decimal("0")) for v in projekt.vorgaenge.all()
             if v.status != VorgangStatus.ABGESCHLOSSEN),
            Decimal("0"),
        )
        rest_personal = offene_reststunden * STUNDENSATZ
        offene_vorgaenge = projekt.vorgaenge.exclude(status=VorgangStatus.ABGESCHLOSSEN).count()
        material_puffer = Decimal(offene_vorgaenge) * Decimal("1500")
        voll = ist + rest_personal + material_puffer

        faktor = {
            "schlecht": Decimal("1.15"),
            "budget": Decimal("0.62"),
            "mittel": Decimal("1.12"),
            "gut": Decimal("1.25"),
        }[tier]

        kv = voll * faktor
        # auf nächste 500 EUR runden, Minimum 3000
        kv = max((kv / Decimal("500")).quantize(Decimal("1")) * Decimal("500"), Decimal("3000"))
        projekt.kostenvoranschlag = kv

        # Projekt-Enddatum (vertragliche Deadline) tier-konsistent setzen, damit
        # "läuft aus dem Plan" auf Projektebene greift: schlechte/Budget-Projekte
        # haben eine knappe Deadline nahe heute, gute liegen klar im Plan.
        if tier in ("schlecht", "budget"):
            projekt.enddatum = self._d(rng.randint(-15, 5) if tier == "schlecht" else rng.randint(-5, 20))
        else:
            letztes_ende = max(v.enddatum for v in projekt.vorgaenge.all())
            projekt.enddatum = letztes_ende + timedelta(days=14 if tier == "mittel" else 28)

        # Projekt-Status grob passend zum Tier
        if tier == "gut" and rng.random() < 0.4:
            projekt.status = ProjektStatus.ABGESCHLOSSEN
        projekt.save(update_fields=["kostenvoranschlag", "status", "enddatum"])

    # ----------------------------------------------------------------- #
    # Report & Dump
    # ----------------------------------------------------------------- #
    def _report(self, ref):
        n_prod = Produkt.objects.count()
        n_mont = Monteur.objects.count()
        n_proj = Projekt.objects.count()
        n_vorg = Projektvorgang.objects.count()
        n_tb = Projekttagebuch.objects.count()
        n_mat = Materialposition.objects.count()
        n_priv = Projekt.objects.filter(projektart=Projektart.PRIVATPERSON).count()
        n_gross = Projekt.objects.filter(projektart=Projektart.GROSSBAUSTELLE).count()

        ueberfaellig = sum(1 for v in Projektvorgang.objects.all() if v.ist_ueberfaellig)
        aus_plan = sum(1 for v in Projektvorgang.objects.all() if v.laeuft_aus_plan)
        abrechenbar = sum(1 for v in Projektvorgang.objects.all() if v.ist_abrechenbar)
        ueber_budget = sum(
            1 for p in Projekt.objects.all()
            if p.budgetauslastung is not None and p.budgetauslastung > 1
        )

        self.stdout.write(self.style.SUCCESS(
            f"Seed erstellt (Stichtag {ref.isoformat()}): "
            f"Betrieb '{BETRIEB_NAME}' (Konstante), "
            f"{n_prod} Produkte, {n_mont} Monteure, {n_proj} Projekte "
            f"({n_priv} Privat / {n_gross} Groß), {n_vorg} Vorgänge, "
            f"{n_tb} Tagebuch-Einträge, {n_mat} Materialpositionen."
        ))
        self.stdout.write(
            f"  Vorgänge überfällig: {ueberfaellig} · läuft aus dem Plan: {aus_plan} · "
            f"abrechenbar (abgeschlossen, offen): {abrechenbar} · Projekte über Budget: {ueber_budget}"
        )

    def _dump(self, path):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        call_command("dumpdata", "shk", indent=2, output=str(out))
        self.stdout.write(self.style.SUCCESS(f"Fixture geschrieben: {out}"))
