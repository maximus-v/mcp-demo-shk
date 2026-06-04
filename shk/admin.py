"""Admin-Pflegeoberfläche für das SHK-Datenmodell.

Alle sieben Entitäten sind registriert. Berechnete Werte (``restaufwand``,
``ist_ueberfaellig``, ``laeuft_aus_plan``, ``ist_kosten``, ``budgetauslastung``,
``rechnungsbetrag`` …) erscheinen ausschließlich read-only und sind keine
pflegbaren Felder.
"""

from django.contrib import admin

from .models import (
    Materialposition,
    Monteur,
    Produkt,
    Projekt,
    Projekttagebuch,
    Projektvorgang,
    Rechnung,
)


# --------------------------------------------------------------------------- #
# Inlines
# --------------------------------------------------------------------------- #
class MonteurZuordnungInline(admin.TabularInline):
    """Monteur-Zuordnung am Projekt (Auto-Through der M2M Monteur.projekte)."""
    model = Monteur.projekte.through
    extra = 0
    verbose_name = "Monteur-Zuordnung"
    verbose_name_plural = "Monteur-Zuordnungen"


class ProjektvorgangInline(admin.TabularInline):
    model = Projektvorgang
    extra = 0
    readonly_fields = ("restaufwand_anzeige", "ist_ueberfaellig_anzeige", "laeuft_aus_plan_anzeige")

    @admin.display(description="Restaufwand (h)")
    def restaufwand_anzeige(self, obj):
        return obj.restaufwand if obj.pk else "—"

    @admin.display(description="Überfällig", boolean=True)
    def ist_ueberfaellig_anzeige(self, obj):
        return obj.ist_ueberfaellig if obj.pk else False

    @admin.display(description="Aus dem Plan", boolean=True)
    def laeuft_aus_plan_anzeige(self, obj):
        return obj.laeuft_aus_plan if obj.pk else False


class ProjekttagebuchInline(admin.TabularInline):
    model = Projekttagebuch
    extra = 0
    autocomplete_fields = ("monteur", "vorgang")


class MaterialpositionInline(admin.TabularInline):
    model = Materialposition
    extra = 0
    autocomplete_fields = ("produkt",)
    readonly_fields = ("kosten_anzeige",)

    @admin.display(description="Kosten")
    def kosten_anzeige(self, obj):
        return obj.kosten if obj.pk else "—"


# --------------------------------------------------------------------------- #
# ModelAdmins
# --------------------------------------------------------------------------- #
@admin.register(Produkt)
class ProduktAdmin(admin.ModelAdmin):
    list_display = ("bezeichnung", "verkaufspreis", "einheit")
    search_fields = ("bezeichnung",)


@admin.register(Projekt)
class ProjektAdmin(admin.ModelAdmin):
    list_display = ("nummer", "titel", "projekttyp", "projektart", "status", "enddatum",
                    "kostenvoranschlag", "ist_kosten_anzeige", "budgetauslastung_anzeige", "laeuft_aus_plan_anzeige")
    list_filter = ("projekttyp", "projektart", "status")
    search_fields = ("nummer", "titel")
    readonly_fields = ("ist_kosten_anzeige", "budgetauslastung_anzeige", "laeuft_aus_plan_anzeige")
    inlines = (MonteurZuordnungInline, ProjektvorgangInline, ProjekttagebuchInline)

    @admin.display(description="Ist-Kosten (berechnet)")
    def ist_kosten_anzeige(self, obj):
        return obj.ist_kosten if obj.pk else "—"

    @admin.display(description="Budgetauslastung (berechnet)")
    def budgetauslastung_anzeige(self, obj):
        if not obj.pk:
            return "—"
        b = obj.budgetauslastung
        return f"{b:.0%}" if b is not None else "—"

    @admin.display(description="Aus dem Plan", boolean=True)
    def laeuft_aus_plan_anzeige(self, obj):
        return obj.laeuft_aus_plan if obj.pk else False


@admin.register(Monteur)
class MonteurAdmin(admin.ModelAdmin):
    list_display = ("name", "anzahl_projekte_anzeige")
    search_fields = ("name",)
    filter_horizontal = ("projekte",)

    @admin.display(description="Anzahl Projekte")
    def anzahl_projekte_anzeige(self, obj):
        return obj.anzahl_projekte


@admin.register(Projektvorgang)
class ProjektvorgangAdmin(admin.ModelAdmin):
    list_display = ("bezeichnung", "projekt", "soll_aufwand", "restaufwand_anzeige", "enddatum",
                    "status", "abgerechnet", "ist_ueberfaellig_anzeige", "laeuft_aus_plan_anzeige", "ist_abrechenbar_anzeige")
    list_filter = ("status", "abgerechnet", "projekt")
    search_fields = ("bezeichnung",)
    autocomplete_fields = ("projekt",)
    inlines = (ProjekttagebuchInline,)
    readonly_fields = ("restaufwand_anzeige", "personalkosten_anzeige", "materialkosten_anzeige",
                       "rechnungsbetrag_anzeige", "ist_ueberfaellig_anzeige", "laeuft_aus_plan_anzeige", "ist_abrechenbar_anzeige")

    @admin.display(description="Restaufwand (h)")
    def restaufwand_anzeige(self, obj):
        return obj.restaufwand if obj.pk else "—"

    @admin.display(description="Personalkosten")
    def personalkosten_anzeige(self, obj):
        return obj.personalkosten if obj.pk else "—"

    @admin.display(description="Materialkosten")
    def materialkosten_anzeige(self, obj):
        return obj.materialkosten if obj.pk else "—"

    @admin.display(description="Rechnungsbetrag")
    def rechnungsbetrag_anzeige(self, obj):
        return obj.rechnungsbetrag if obj.pk else "—"

    @admin.display(description="Überfällig", boolean=True)
    def ist_ueberfaellig_anzeige(self, obj):
        return obj.ist_ueberfaellig if obj.pk else False

    @admin.display(description="Aus dem Plan", boolean=True)
    def laeuft_aus_plan_anzeige(self, obj):
        return obj.laeuft_aus_plan if obj.pk else False

    @admin.display(description="Abrechenbar", boolean=True)
    def ist_abrechenbar_anzeige(self, obj):
        return obj.ist_abrechenbar if obj.pk else False


@admin.register(Projekttagebuch)
class ProjekttagebuchAdmin(admin.ModelAdmin):
    list_display = ("projekt", "vorgang", "monteur", "datum", "stunden")
    list_filter = ("projekt", "monteur")
    search_fields = ("text", "monteur__name")
    date_hierarchy = "datum"
    autocomplete_fields = ("projekt", "vorgang", "monteur")
    inlines = (MaterialpositionInline,)


@admin.register(Materialposition)
class MaterialpositionAdmin(admin.ModelAdmin):
    list_display = ("eintrag", "produkt", "menge", "kosten_anzeige")
    autocomplete_fields = ("eintrag", "produkt")
    readonly_fields = ("kosten_anzeige",)

    @admin.display(description="Kosten")
    def kosten_anzeige(self, obj):
        return obj.kosten if obj.pk else "—"


@admin.register(Rechnung)
class RechnungAdmin(admin.ModelAdmin):
    list_display = ("nummer", "projekt", "vorgang", "betrag", "erstellt_am", "view_url_anzeige")
    list_filter = ("projekt",)
    search_fields = ("nummer",)
    autocomplete_fields = ("projekt", "vorgang")
    readonly_fields = ("view_url_anzeige",)

    @admin.display(description="View-URL")
    def view_url_anzeige(self, obj):
        return obj.view_url if obj.pk else "—"
