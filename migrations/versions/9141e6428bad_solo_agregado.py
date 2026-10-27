"""solo agregado

Revision ID: 9141e6428bad
Revises: 1c921a1fe62f
Create Date: 2026-10-27 11:06:47.538630

Escrita a mano (no autogenerada): la comparación automática de Alembic no ve funciones ni
disparadores. Hace cumplir en la base la regla RN15: `historial_estado_orden`, `movimiento_stock` e
`historial_precio_repuesto` son de sólo agregado; `UPDATE` y `DELETE` se rechazan, venga de donde venga
(aplicación, psql, dueño de la tabla). `INSERT` sigue permitido.

`TRUNCATE` no se bloquea a propósito: el disparador es por fila y `seed.py` (C-06) necesita vaciar las
tablas con `TRUNCATE … RESTART IDENTITY CASCADE`. La aplicación nunca lo ejecuta.

El rechazo usa SQLSTATE `P0001` (no clase 22 ni 23) para que la API lo responda 500 y no lo disfrace
de error del cliente. El mensaje es ASCII para que se lea bien en la consola de Windows.

Leída antes de aplicar (2026-10-27, apply de C-04 contra design D1–D7): migración manual sin
`--autogenerate`. Verificado en la lectura:
- Una sola función `rechazar_cambio_solo_agregado()` que siempre lanza la excepción (nunca
  `RETURN NULL`, que saltearía la fila en silencio); `CREATE FUNCTION`, no `OR REPLACE`.
- Tres disparadores `trg_solo_agregado`, `BEFORE UPDATE OR DELETE … FOR EACH ROW`, uno por tabla.
- Ninguna operación sobre tablas, columnas, índices ni datos: sólo la función y los disparadores.
- `downgrade()` en orden inverso: `DROP TRIGGER` x3 y después `DROP FUNCTION`, sin `CASCADE` ni
  `IF EXISTS`; no toca tablas ni filas.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9141e6428bad"
down_revision: str | Sequence[str] | None = "1c921a1fe62f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLAS_SOLO_AGREGADO = (
    "historial_estado_orden",
    "movimiento_stock",
    "historial_precio_repuesto",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE FUNCTION rechazar_cambio_solo_agregado() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = 'P0001',
                MESSAGE = format('%s rechazado: %s es de solo agregado', TG_OP, TG_TABLE_NAME),
                HINT = 'Registrar una fila nueva en lugar de modificar o borrar una existente';
        END;
        $$
        """
    )
    for tabla in TABLAS_SOLO_AGREGADO:
        op.execute(
            f"CREATE TRIGGER trg_solo_agregado BEFORE UPDATE OR DELETE ON {tabla} "
            "FOR EACH ROW EXECUTE FUNCTION rechazar_cambio_solo_agregado()"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for tabla in reversed(TABLAS_SOLO_AGREGADO):
        op.execute(f"DROP TRIGGER trg_solo_agregado ON {tabla}")
    op.execute("DROP FUNCTION rechazar_cambio_solo_agregado()")
