"""URL-Routen der shk-App.

``rechnung`` ist die benannte Route hinter ``Rechnung.view_url`` und wird vom
MCP-Tool ``erstelle_rechnung`` (TICKET-4) verlinkt.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("rechnung/<int:pk>/", views.rechnung_view, name="rechnung"),
]
