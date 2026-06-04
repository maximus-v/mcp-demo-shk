"""Erzeugt eine Beispielrechnung für die Rechnungs-View (TICKET-3).

Wählt einen abgeschlossenen, noch nicht abgerechneten Vorgang (mit erfasstem
Aufwand) und schreibt dafür eine ``Rechnung`` – analog zum späteren MCP-Tool
``erstelle_rechnung`` (TICKET-4): Betrag = ``vorgang.rechnungsbetrag``, Vorgang
wird als ``abgerechnet`` markiert. Idempotent: existiert bereits eine Rechnung
zum gewählten Vorgang, wird diese wiederverwendet.

Beispiel:
    python manage.py seed_beispielrechnung
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shk.models import Rechnung, Projektvorgang, VorgangStatus


class Command(BaseCommand):
    help = "Erzeugt eine Beispielrechnung für einen abgeschlossenen Vorgang (Rechnungs-View)."

    def handle(self, *args, **options):
        offen = list(Projektvorgang.objects.filter(
            status=VorgangStatus.ABGESCHLOSSEN, abgerechnet=False))
        # Bevorzugt ein Vorgang MIT Material (zeigt Materialzeilen + Werkstoffpauschale),
        # sonst irgendein abgeschlossener, nicht abgerechneter Vorgang mit Aufwand.
        kandidat = next(
            (v for v in offen if v.rechnungsaufschluesselung()["produktsumme"] > 0), None)
        if kandidat is None:
            kandidat = next((v for v in offen if v.rechnungsbetrag > 0), None)
        # Fallback: bereits abgerechneter Vorgang (Wiederverwendung der Rechnung).
        if kandidat is None:
            kandidat = next(
                (v for v in Projektvorgang.objects.filter(status=VorgangStatus.ABGESCHLOSSEN)
                 if v.rechnungsbetrag > 0),
                None,
            )
        if kandidat is None:
            raise CommandError(
                "Kein abgeschlossener Vorgang mit erfasstem Aufwand gefunden. "
                "Zuerst 'python manage.py seed_demo --flush' ausführen."
            )

        bestehend = Rechnung.objects.filter(vorgang=kandidat).first()
        if bestehend:
            self.stdout.write(self.style.WARNING(
                f"Rechnung existiert bereits: {bestehend.nummer} (Vorgang {kandidat.bezeichnung})."
            ))
            self._info(bestehend)
            return

        jahr = timezone.now().year
        laufnr = Rechnung.objects.count() + 1
        nummer = f"RE-{jahr}-{laufnr:04d}"
        betrag = kandidat.rechnungsbetrag.quantize(Decimal("0.01"))

        rechnung = Rechnung.objects.create(
            nummer=nummer,
            projekt=kandidat.projekt,
            vorgang=kandidat,
            betrag=betrag,
        )
        kandidat.abgerechnet = True
        kandidat.save(update_fields=["abgerechnet"])

        self.stdout.write(self.style.SUCCESS(f"Beispielrechnung erstellt: {nummer}"))
        self._info(rechnung)

    def _info(self, rechnung):
        self.stdout.write(
            f"  Projekt:  {rechnung.projekt.nummer} – {rechnung.projekt.titel}\n"
            f"  Vorgang:  {rechnung.vorgang.bezeichnung}\n"
            f"  Betrag:   {rechnung.betrag} EUR\n"
            f"  View:     http://127.0.0.1:8000{rechnung.view_url}  (id={rechnung.pk})"
        )
