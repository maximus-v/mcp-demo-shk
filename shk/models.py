"""Datenmodell für die MCP-Demo SHK (Sanitär-Heizung-Klima).

Sieben Entitäten gemäß Umsetzungsplan (Attribut-Tabellen). Der **Betrieb** wird
nicht als Modell, sondern als Modul-Konstante gehalten (ein einziger Betrieb).

Ableitungen (``restaufwand``, ``ist_ueberfaellig``, ``laeuft_aus_plan``,
``personalkosten``, ``materialkosten``, ``rechnungsbetrag``, ``ist_abrechenbar``,
``ist_kosten``, ``budgetauslastung``) werden zur Laufzeit als ``@property``
berechnet und nicht als DB-Feld gespeichert.
"""

import math
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone


# --------------------------------------------------------------------------- #
# Betriebs-Stammdaten & Berechnungs-Konstanten (kein DB-Modell)
# --------------------------------------------------------------------------- #
BETRIEB_NAME = "Acp SHK Betrieb"
BETRIEB_ADRESSE = "Schnorrstraße 7, 01069 Dresden"
STUNDENSATZ = Decimal("60")           # EUR/Stunde, einheitlich für alle Monteure
STUNDEN_PRO_ARBEITSTAG = 8            # Reststunden → Resttage für "läuft aus dem Plan"
WERKSTOFFPAUSCHALE = Decimal("0.10")  # 10 % auf den Produkt-Verkaufspreis (Werkstoffe)


# --------------------------------------------------------------------------- #
# Choices
# --------------------------------------------------------------------------- #
class ProjektTyp(models.TextChoices):
    WAERMEPUMPE = "Wärmepumpe", "Wärmepumpe"
    PV = "PV", "PV"
    SOLARTHERMIE = "Solarthermie", "Solarthermie"
    BAD = "Bad", "Bad"


class Projektart(models.TextChoices):
    PRIVATPERSON = "Privatperson", "Privatperson"
    GROSSBAUSTELLE = "Großbaustelle", "Großbaustelle"


class ProjektStatus(models.TextChoices):
    IN_PLANUNG = "In Planung", "In Planung"
    IN_BEARBEITUNG = "In Bearbeitung", "In Bearbeitung"
    ABGESCHLOSSEN = "Abgeschlossen", "Abgeschlossen"


class VorgangStatus(models.TextChoices):
    GEPLANT = "Geplant", "Geplant"
    IN_BEARBEITUNG = "In Bearbeitung", "In Bearbeitung"
    ABGESCHLOSSEN = "Abgeschlossen", "Abgeschlossen"


# --------------------------------------------------------------------------- #
# Stammdaten-Entitäten
# --------------------------------------------------------------------------- #
class Produkt(models.Model):
    bezeichnung = models.CharField("Bezeichnung", max_length=200)
    verkaufspreis = models.DecimalField("Verkaufspreis", max_digits=10, decimal_places=2)
    einheit = models.CharField("Einheit", max_length=20, default="Stk.")

    class Meta:
        verbose_name = "Produkt"
        verbose_name_plural = "Produkte"
        ordering = ["bezeichnung"]

    def __str__(self):
        return self.bezeichnung


class Projekt(models.Model):
    nummer = models.CharField("Nummer", max_length=20, unique=True, help_text="Anzeige z. B. PR10025")
    titel = models.CharField("Titel", max_length=200, help_text="Adresse zur Identifikation im Tagebuch, z. B. Musterstraße 4, Dresden")
    projekttyp = models.CharField("Projekttyp", max_length=30, choices=ProjektTyp.choices, default=ProjektTyp.WAERMEPUMPE)
    projektart = models.CharField("Projektart", max_length=20, choices=Projektart.choices, default=Projektart.PRIVATPERSON)
    status = models.CharField("Status", max_length=20, choices=ProjektStatus.choices, default=ProjektStatus.IN_PLANUNG)
    enddatum = models.DateField("Enddatum")
    kostenvoranschlag = models.DecimalField("Kostenvoranschlag", max_digits=12, decimal_places=2, help_text="Budget (Soll-Kosten)")

    class Meta:
        verbose_name = "Projekt"
        verbose_name_plural = "Projekte"
        ordering = ["nummer"]

    def __str__(self):
        return f"{self.nummer} – {self.titel}"

    @property
    def ist_kosten(self):
        """Ist-Kosten = Σ (Personal + Material inkl. Werkstoffpauschale) über alle Vorgänge."""
        return sum((v.personalkosten + v.materialkosten for v in self.vorgaenge.all()), Decimal("0"))

    @property
    def budgetauslastung(self):
        """Ist-Kosten / Kostenvoranschlag. None, wenn kein Budget hinterlegt."""
        if not self.kostenvoranschlag:
            return None
        return self.ist_kosten / self.kostenvoranschlag

    @property
    def laeuft_aus_plan(self):
        """heute + (Σ Restaufwand offener Vorgänge / STUNDEN_PRO_ARBEITSTAG) > Projekt-Enddatum."""
        rest = sum(
            (max(v.restaufwand, Decimal("0")) for v in self.vorgaenge.all() if v.status != VorgangStatus.ABGESCHLOSSEN),
            Decimal("0"),
        )
        resttage = math.ceil(float(rest) / STUNDEN_PRO_ARBEITSTAG)
        return timezone.localdate() + timedelta(days=resttage) > self.enddatum


class Monteur(models.Model):
    name = models.CharField("Name", max_length=120)
    projekte = models.ManyToManyField(
        Projekt, related_name="monteure", verbose_name="Projekte", blank=True,
        help_text="Fest zugeordnet; tageweiser Wechsel zwischen Projekten möglich.",
    )

    class Meta:
        verbose_name = "Monteur"
        verbose_name_plural = "Monteure"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def anzahl_projekte(self):
        return self.projekte.count()


# --------------------------------------------------------------------------- #
# Vorgänge & Erfassung
# --------------------------------------------------------------------------- #
class Projektvorgang(models.Model):
    projekt = models.ForeignKey(Projekt, on_delete=models.CASCADE, related_name="vorgaenge", verbose_name="Projekt")
    bezeichnung = models.CharField("Bezeichnung", max_length=200)
    soll_aufwand = models.DecimalField("Soll-Aufwand (Stunden)", max_digits=8, decimal_places=2)
    enddatum = models.DateField("Enddatum")
    status = models.CharField("Status", max_length=20, choices=VorgangStatus.choices, default=VorgangStatus.GEPLANT)
    abgerechnet = models.BooleanField("Abgerechnet", default=False)

    class Meta:
        verbose_name = "Projektvorgang"
        verbose_name_plural = "Projektvorgänge"
        ordering = ["enddatum"]

    def __str__(self):
        return self.bezeichnung

    @property
    def _geleistete_stunden(self):
        return sum((e.stunden for e in self.tagebuch_eintraege.all()), Decimal("0"))

    @property
    def restaufwand(self):
        """Soll-Aufwand − Σ(geleistete Tagebuch-Stunden), in Stunden (kann negativ sein)."""
        return self.soll_aufwand - self._geleistete_stunden

    @property
    def ist_ueberfaellig(self):
        """Nicht abgeschlossen und Enddatum überschritten."""
        return self.status != VorgangStatus.ABGESCHLOSSEN and self.enddatum < timezone.localdate()

    @property
    def laeuft_aus_plan(self):
        """heute + (Restaufwand / STUNDEN_PRO_ARBEITSTAG) > Enddatum (nur offene Vorgänge)."""
        if self.status == VorgangStatus.ABGESCHLOSSEN:
            return False
        resttage = math.ceil(float(max(self.restaufwand, Decimal("0"))) / STUNDEN_PRO_ARBEITSTAG)
        return timezone.localdate() + timedelta(days=resttage) > self.enddatum

    @property
    def personalkosten(self):
        """Σ(Tagebuch-Stunden) × Betriebs-Stundensatz."""
        return self._geleistete_stunden * STUNDENSATZ

    @property
    def materialkosten(self):
        """Σ(Produktmenge × Verkaufspreis) + 10 % Werkstoffpauschale."""
        produktsumme = sum(
            (pos.menge * pos.produkt.verkaufspreis
             for eintrag in self.tagebuch_eintraege.all()
             for pos in eintrag.materialpositionen.all()),
            Decimal("0"),
        )
        return produktsumme * (Decimal("1") + WERKSTOFFPAUSCHALE)

    @property
    def rechnungsbetrag(self):
        """Personalkosten + Materialkosten."""
        return self.personalkosten + self.materialkosten

    @property
    def ist_abrechenbar(self):
        """Abgeschlossen und noch nicht abgerechnet."""
        return self.status == VorgangStatus.ABGESCHLOSSEN and not self.abgerechnet

    def rechnungsaufschluesselung(self):
        """Aufschlüsselung des Rechnungsbetrags für die Rechnungs-View (TICKET-3)
        und als Prüfgrundlage im Chat (TICKET-4): Personal, je Produkt aggregierte
        Materialzeilen, Werkstoffpauschale und Summe. Reine Lese-Berechnung."""
        stunden = self._geleistete_stunden
        personalkosten = stunden * STUNDENSATZ

        agg = {}
        for eintrag in self.tagebuch_eintraege.all():
            for pos in eintrag.materialpositionen.all():
                z = agg.setdefault(pos.produkt_id, {
                    "bezeichnung": pos.produkt.bezeichnung,
                    "einheit": pos.produkt.einheit,
                    "einzelpreis": pos.produkt.verkaufspreis,
                    "menge": Decimal("0"),
                })
                z["menge"] += pos.menge

        material_zeilen = sorted(agg.values(), key=lambda z: z["bezeichnung"])
        produktsumme = Decimal("0")
        for z in material_zeilen:
            z["betrag"] = z["menge"] * z["einzelpreis"]
            produktsumme += z["betrag"]

        werkstoffpauschale = produktsumme * WERKSTOFFPAUSCHALE
        summe = personalkosten + produktsumme + werkstoffpauschale
        return {
            "stunden": stunden,
            "stundensatz": STUNDENSATZ,
            "personalkosten": personalkosten,
            "material_zeilen": material_zeilen,
            "produktsumme": produktsumme,
            "werkstoffpauschale_prozent": (WERKSTOFFPAUSCHALE * 100).quantize(Decimal("1")),
            "werkstoffpauschale": werkstoffpauschale,
            "summe": summe,
        }


class Projekttagebuch(models.Model):
    projekt = models.ForeignKey(Projekt, on_delete=models.CASCADE, related_name="tagebuch_eintraege", verbose_name="Projekt")
    vorgang = models.ForeignKey(Projektvorgang, on_delete=models.CASCADE, related_name="tagebuch_eintraege", verbose_name="Vorgang")
    monteur = models.ForeignKey(Monteur, on_delete=models.PROTECT, related_name="tagebuch_eintraege", verbose_name="Monteur")
    datum = models.DateTimeField("Datum", default=timezone.now)
    stunden = models.DecimalField("Stunden", max_digits=6, decimal_places=2)
    text = models.TextField("Fortschritts-Update", blank=True)

    class Meta:
        verbose_name = "Projekttagebuch-Eintrag"
        verbose_name_plural = "Projekttagebuch"
        ordering = ["-datum"]

    def __str__(self):
        return f"{self.datum:%Y-%m-%d} – {self.monteur}"


class Materialposition(models.Model):
    eintrag = models.ForeignKey(Projekttagebuch, on_delete=models.CASCADE, related_name="materialpositionen", verbose_name="Tagebuch-Eintrag")
    produkt = models.ForeignKey(
        Produkt, on_delete=models.PROTECT, related_name="materialpositionen", verbose_name="Produkt",
        help_text="Pflicht – zwingend auf ein Katalog-Produkt gemappt.",
    )
    menge = models.DecimalField("Menge", max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = "Materialposition"
        verbose_name_plural = "Materialpositionen"
        ordering = ["id"]

    def __str__(self):
        return f"{self.menge} × {self.produkt}"

    @property
    def kosten(self):
        """Menge × Verkaufspreis (ohne Werkstoffpauschale)."""
        return self.menge * self.produkt.verkaufspreis


# --------------------------------------------------------------------------- #
# Rechnung
# --------------------------------------------------------------------------- #
class Rechnung(models.Model):
    nummer = models.CharField("Rechnungsnummer", max_length=30, unique=True)
    projekt = models.ForeignKey(Projekt, on_delete=models.PROTECT, related_name="rechnungen", verbose_name="Projekt")
    vorgang = models.ForeignKey(Projektvorgang, on_delete=models.PROTECT, related_name="rechnungen", verbose_name="Vorgang")
    betrag = models.DecimalField("Betrag", max_digits=12, decimal_places=2, help_text="Festgeschriebene Summe (Personal + Material)")
    erstellt_am = models.DateTimeField("Erstellt am", default=timezone.now)

    class Meta:
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"
        ordering = ["-erstellt_am"]

    def __str__(self):
        return self.nummer

    @property
    def view_url(self):
        """Link auf die HTML-Rechnungs-View (``/rechnung/<id>/``). Deterministisch
        über die URLconf bestimmbar, daher kein DB-Feld."""
        if not self.pk:
            return ""
        return reverse("rechnung", args=[self.pk])
