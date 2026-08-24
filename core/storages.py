"""
core/storages.py

Almacenamiento para archivos que NUNCA deben servirse por HTTP.

El certificado .p12 vivia en MEDIA_ROOT/sri_certs/, y nginx sirve /media/
entero. Cualquiera que acertara el nombre del archivo podia descargarlo y, con
el, firmar comprobantes suplantando a la empresa.

PrivateStorage lo saca de ahi: escribe en PRIVATE_ROOT, que esta fuera de la
raiz que sirve nginx, y ademas hace que url() falle. Eso ultimo no es adorno:
FileSystemStorage cae a MEDIA_URL cuando no tiene base_url, asi que sin este
override un template que hiciera {{ config.certificate_file.url }} volveria a
publicar un enlace que apunta a /media/.
"""
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Archivos accesibles solo desde el codigo: sin URL publica."""

    def url(self, name):
        raise SuspiciousOperation(
            "El archivo privado no tiene URL publica y no puede servirse por HTTP."
        )


def private_storage() -> PrivateStorage:
    """
    Callable (no instancia) a proposito: asi las migraciones guardan la
    referencia a esta funcion en vez de congelar una ruta absoluta de la
    maquina donde se genero la migracion.
    """
    return PrivateStorage(location=settings.PRIVATE_ROOT)
