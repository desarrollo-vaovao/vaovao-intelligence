"""
report_builder — une las piezas del motor de reportes.

Toma un activo comercial de la base y un rango de fechas; pide los datos a
Meta (meta_api) y los arma en la estructura que espera pdf_generator. Es el
"pegamento" entre traer datos y dibujarlos.

Un reporte es siempre de UN activo comercial: los activos de un mismo cliente
pueden ser marcas sin relación entre sí, y mezclarlas en un PDF no sirve.
"""
from datetime import date

from app.models import AdAccount
from app.services import meta_api, pdf_generator

_MESES = ["ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]

CURRENCY_SYMBOLS = {"USD": "$", "GTQ": "Q"}


def format_period(date_from: date, date_to: date) -> str:
    """Ej.: '1 – 15 jun 2026' o '20 may – 5 jun 2026' si cruza meses."""
    if date_from.month == date_to.month and date_from.year == date_to.year:
        return f"{date_from.day} – {date_to.day} {_MESES[date_to.month - 1]} {date_to.year}"
    return (f"{date_from.day} {_MESES[date_from.month - 1]} – "
            f"{date_to.day} {_MESES[date_to.month - 1]} {date_to.year}")


async def build_report_data(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD") -> dict:
    """
    Construye el diccionario que pdf_generator sabe dibujar, para UN activo
    comercial.
    `tokens` es una lista de candidatos en orden de preferencia (p. ej. el
    Facebook personal del usuario y, de respaldo, el token central de la
    organización): si el primero no tiene acceso a la cuenta, se reintenta con
    el siguiente antes de fallar.
    Lanza meta_api.MetaApiError si ningún token puede leer la cuenta.
    """
    data = await meta_api.get_account_data_with_fallback(
        tokens, account.meta_ad_account_id, date_from.isoformat(), date_to.isoformat()
    )
    return {
        "client_name": account.label,
        "period": format_period(date_from, date_to),
        "campaigns": data["campaigns"],
        "total_spend": data["total_spend"],
        "budget": budget,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, "$"),
    }


async def build_pdf(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD") -> tuple[bytes, str]:
    """
    Genera el PDF completo. Devuelve (bytes_del_pdf, nombre_de_archivo).
    """
    report_data = await build_report_data(account, tokens, date_from, date_to, budget, currency)
    pdf_bytes = await pdf_generator.generate_pdf(report_data)

    slug = "".join(ch if ch.isalnum() else "-" for ch in account.label.lower()).strip("-")
    filename = f"reporte-{slug}-{date_from.isoformat()}-a-{date_to.isoformat()}.pdf"
    return pdf_bytes, filename
