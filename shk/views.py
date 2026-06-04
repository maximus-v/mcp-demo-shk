"""Views für die SHK-MCP-Demo.

Aktuell: die HTML-Rechnungs-View (TICKET-3). Sie rendert eine bestehende
``Rechnung`` als semi-corporate, druckfreundliche Seite. Der Link wird vom
MCP-Tool ``erstelle_rechnung`` (TICKET-4) zurückgegeben; der Nutzer zieht sich
daraus per Browser-Druck selbst ein PDF.
"""

from django.shortcuts import get_object_or_404, render

from .models import BETRIEB_ADRESSE, BETRIEB_NAME, Rechnung


def rechnung_view(request, pk):
    rechnung = get_object_or_404(Rechnung.objects.select_related("projekt", "vorgang"), pk=pk)
    context = {
        "rechnung": rechnung,
        "projekt": rechnung.projekt,
        "vorgang": rechnung.vorgang,
        "betrieb_name": BETRIEB_NAME,
        "betrieb_adresse": BETRIEB_ADRESSE,
        "auf": rechnung.vorgang.rechnungsaufschluesselung(),
    }
    return render(request, "shk/rechnung.html", context)
