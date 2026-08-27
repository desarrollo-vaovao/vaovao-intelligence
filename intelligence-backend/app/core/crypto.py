"""
Cifrado de credenciales sensibles (token de Meta, etc.) con Fernet.
El token NUNCA se guarda en texto plano en la base: se cifra antes de guardar
y se descifra solo en el momento de usarlo para llamar a Meta.

Requiere ENCRYPTION_KEY en el entorno. Si no está, fallar es lo correcto:
mejor no guardar un secreto que guardarlo sin proteger.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY no está configurada. Genera una con: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    """Cifra un texto y devuelve el resultado como string para guardar en la base."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """
    Descifra. Devuelve None si el dato está corrupto o la llave no corresponde
    (típicamente porque ENCRYPTION_KEY se rotó y los datos quedaron cifrados
    con la anterior). El dato sigue ahí: quien llama cuenta esos casos y avisa.

    Una ENCRYPTION_KEY con FORMATO inválido no entra por aquí a propósito.
    Eso no es un dato ilegible sino un servidor mal configurado, y se deja
    salir el ValueError de `_fernet()` para que se vea como lo que es. Antes
    se atrapaba junto con InvalidToken, así que una llave de 64 chars hex
    (`openssl rand -hex 32`, que no es Fernet) se veía idéntica a "la llave
    rotó" y mandaba a buscar una llave anterior que nunca existió.
    """
    fernet = _fernet()
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None


def mask(secret: str, visible: int = 4, dots: int = 8) -> str:
    """
    Devuelve una versión enmascarada para mostrar en UI sin exponer el secreto.
    Los tokens de Meta son larguísimos (100+ caracteres); `dots` limita cuántos
    puntos se muestran para que no se vea una fila interminable en la UI.
    """
    if not secret:
        return ""
    if len(secret) <= visible:
        return "•" * len(secret)
    return "•" * dots + secret[-visible:]
