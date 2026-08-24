"""
core/db_locks.py

Serializacion de secciones criticas con advisory locks de PostgreSQL.

Los secuenciales (factura, guia, nota de credito, lote) se generaban con
"leer el maximo + 1" sin bloqueo: dos procesos concurrentes leian el mismo
maximo y producian el mismo numero. La restriccion unica evitaba el duplicado,
pero el segundo INSERT fallaba y la operacion (facturar, recibir) reventaba.

Con un advisory lock por transaccion se serializa solo esa serie: el segundo
proceso espera a que el primero confirme, y entonces lee un maximo ya
actualizado. No hay fila natural que bloquear con select_for_update —el numero
es un max() sobre un conjunto filtrado, y la serie puede estar vacia— por eso
un advisory lock y no un lock de fila.

Requisitos:
- Llamarse DENTRO de transaction.atomic: pg_advisory_xact_lock se libera al
  terminar la transaccion, cubriendo desde la lectura del maximo hasta el
  INSERT. Fuera de una transaccion, atomic auto-envuelve cada sentencia y el
  lock se soltaria de inmediato, sin serializar nada.
- PostgreSQL (django-tenants ya lo exige).
"""
from django.db import connection


def lock_series(*parts) -> None:
    """
    Toma un advisory lock de transaccion para la serie identificada por parts.

    La clave incluye el schema del tenant: dos empresas distintas que emiten el
    mismo numero de serie no se bloquean entre si (el lock es global a la base,
    compartido entre schemas, asi que el schema desambigua).
    """
    schema = getattr(connection, "schema_name", "public")
    clave = "|".join(["seq", schema, *(str(p) for p in parts)])
    with connection.cursor() as cur:
        # hashtextextended -> bigint (64 bits): menos colisiones que hashtext.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [clave])
