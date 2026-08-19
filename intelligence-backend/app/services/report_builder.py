"""
report_builder — une las piezas del motor de reportes.

Toma un cliente de la base, sus cuentas publicitarias y un rango de fechas;
pide los datos a Meta (meta_api) y los arma en la estructura que espera
pdf_generator. Es el "pegamento" entre traer datos y dibujarlos.

Maneja los dos casos:
- Cliente con UNA cuenta      → reporte simple (una página)
- Cliente multi-estación      → una página por cuenta
"""
import asyncio
from datetime import date

from app.models import Client
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


async def build_report_data(client: Client, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD") -> dict:
    """
    Construye el diccionario que pdf_generator sabe dibujar.
    `tokens` es una lista de candidatos en orden de preferencia (p. ej. el
    Facebook personal del usuario y, de respaldo, el token central de la
    organización): si el primero no tiene acceso a una cuenta puntual, se
    reintenta con el siguiente antes de fallar.
    Lanza meta_api.MetaApiError si ningún token puede leer alguna cuenta.
    """
    accounts = list(client.ad_accounts)
    if not accounts:
        raise ValueError("El cliente no tiene cuentas publicitarias registradas.")

    d_from = date_from.isoformat()
    d_to = date_to.isoformat()
    period = format_period(date_from, date_to)
    currency_symbol = CURRENCY_SYMBOLS.get(currency, "$")

    # ── Multi-estación: una página por cuenta ──
    if len(accounts) > 1:
        # Todas las cuentas se piden en paralelo, no una por una.
        results = await asyncio.gather(*(
            meta_api.get_account_data_with_fallback(tokens, acc.meta_ad_account_id, d_from, d_to)
            for acc in accounts
        ))
        # El presupuesto se reparte en partes iguales si viene uno global
        per_station = (budget / len(accounts)) if budget else None
        stations = [
            {
                "station_label": acc.label,
                "campaigns": data["campaigns"],
                "total_spend": data["total_spend"],
                "budget": per_station,
            }
            for acc, data in zip(accounts, results)
        ]
        return {
            "client_name": client.name,
            "period": period,
            "type": "multi-station",
            "stations": stations,
            "currency_symbol": currency_symbol,
        }

    # ── Cuenta única ──
    acc = accounts[0]
    data = await meta_api.get_account_data_with_fallback(tokens, acc.meta_ad_account_id, d_from, d_to)
    return {
        "client_name": client.name,
        "period": period,
        "type": "single",
        "campaigns": data["campaigns"],
        "total_spend": data["total_spend"],
        "budget": budget,
        "currency_symbol": currency_symbol,
    }


async def build_pdf(client: Client, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD") -> tuple[bytes, str]:
    """
    Genera el PDF completo. Devuelve (bytes_del_pdf, nombre_de_archivo).
    """
    report_data = await build_report_data(client, tokens, date_from, date_to, budget, currency)
    pdf_bytes = await pdf_generator.generate_pdf(report_data)

    slug = "".join(ch if ch.isalnum() else "-" for ch in client.name.lower()).strip("-")
    filename = f"reporte-{slug}-{date_from.isoformat()}-a-{date_to.isoformat()}.pdf"
    return pdf_bytes, filename
