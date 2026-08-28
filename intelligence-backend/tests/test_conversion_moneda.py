"""
Conversión USD<->GTQ en los reportes.

Contexto del bug que esto cierra
---------------------------------
El panel de Resumen mostraba "Q75.59" al elegir quetzales, pero era el
MISMO número que en dólares con el símbolo cambiado — nunca hubo
conversión real. La causa raíz de fondo era que la app no sabía en qué
moneda reporta gasto cada cuenta de Meta (algunas están configuradas
nativamente en quetzales, no todas en dólares), así que "convertir
siempre" habría sido tan incorrecto como "no convertir nunca".

Estas pruebas cubren la función pura (`_exchange_factor`/`_convert_money`)
sin red ni base de datos — la integración completa (con AdAccount y
Organization reales) está en test_ajustes_organizacion.py y se verificó
manualmente contra datos de Meta simulados durante el desarrollo.
"""
from __future__ import annotations

from app.services.report_builder import _convert_money, _exchange_factor


def test_mismo_origen_y_destino_no_convierte():
    assert _exchange_factor("USD", "USD", 7.75) == 1.0
    assert _exchange_factor("GTQ", "GTQ", 7.75) == 1.0


def test_usd_a_gtq_multiplica_por_la_tasa():
    assert _exchange_factor("USD", "GTQ", 7.75) == 7.75


def test_gtq_a_usd_es_el_inverso_no_la_misma_tasa():
    """Un error común: dividir donde toca multiplicar (o viceversa) deja el
    monto mil veces más grande o más chico en vez de solo mal por un factor
    chico difícil de notar a simple vista."""
    factor = _exchange_factor("GTQ", "USD", 7.75)
    assert abs(factor - (1 / 7.75)) < 1e-9


def test_par_no_soportado_no_revienta_y_no_inventa_un_factor():
    """Cualquier moneda que no sea USD/GTQ (hoy no seleccionable en el
    frontend, pero la cuenta de Meta podría estarlo) se deja sin convertir
    en vez de arriesgar un número inventado."""
    assert _exchange_factor("EUR", "GTQ", 7.75) is None


def test_convierte_spend_de_campana_y_de_anuncio_pero_no_metricas_no_monetarias():
    campaigns = [{
        "spend": 10.0,
        "insights": {"spend": 10.0, "cpm": 2.0, "cpc": 0.5, "impressions": 1000, "clicks": 40},
        "ads": [{"insights": {"spend": 6.0, "cpc": 0.4, "clicks": 15}}],
    }]

    converted, total = _convert_money(campaigns, total_spend=10.0, factor=7.75)

    c = converted[0]
    assert c["spend"] == 77.5
    assert c["insights"]["spend"] == 77.5
    assert c["insights"]["cpm"] == 15.5
    assert c["insights"]["cpc"] == 0.5 * 7.75
    # Impresiones y clics NO son dinero: deben quedar exactamente iguales.
    assert c["insights"]["impressions"] == 1000
    assert c["insights"]["clicks"] == 40
    assert c["ads"][0]["insights"]["spend"] == 46.5
    assert c["ads"][0]["insights"]["clicks"] == 15
    assert total == 77.5


def test_no_muta_las_campanas_originales():
    """build_report_data podría reusar `data["campaigns"]` para otra cosa
    (o el mismo dict venir de un cache) — convertir tiene que devolver
    copias, no pisar el original en su lugar."""
    original = [{"spend": 10.0, "insights": {"spend": 10.0}, "ads": []}]

    _convert_money(original, total_spend=10.0, factor=7.75)

    assert original[0]["spend"] == 10.0
    assert original[0]["insights"]["spend"] == 10.0


def test_campana_sin_insights_ni_ads_no_revienta():
    campaigns = [{"spend": 5.0}]
    converted, total = _convert_money(campaigns, total_spend=5.0, factor=2.0)
    assert converted[0]["spend"] == 10.0
    assert total == 10.0
