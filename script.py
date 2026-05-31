import psycopg2
import psycopg2.extras
import json
from fastmcp import FastMCP
from SafeSQLDriver import SafeSQLDriver

mcp = FastMCP("My MCP Server")

driver = SafeSQLDriver()

@mcp.tool()
def analizar_esquema_base_datos(schema: str = "public") -> dict:
    """
    Analiza el esquema de una base PostgreSQL usando SafeSQLDriver.
    Devuelve tablas, columnas, claves primarias y claves foráneas.
    """


    tablas_result = driver.execute_readonly(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema,)
    )

    tablas = tablas_result["rows"]

    resultado = {
        "schema": schema,
        "entidades": {}
    }

    for tabla in tablas:
        table_name = tabla["table_name"]

        columnas_result = driver.execute_readonly(
            """
            SELECT
                column_name,
                data_type,
                udt_name,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table_name)
        )

        columnas = columnas_result["rows"]

        pk_result = driver.execute_readonly(
            """
            SELECT
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
            """,
            (schema, table_name)
        )

        primary_keys = [row["column_name"] for row in pk_result["rows"]]

        fk_result = driver.execute_readonly(
            """
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s
            """,
            (schema, table_name)
        )

        foreign_keys = fk_result["rows"]

        atributos = {}

        for columna in columnas:
            nombre_columna = columna["column_name"]

            tipo = columna["data_type"]

            if columna["data_type"] == "USER-DEFINED":
                tipo = f"Enum({columna['udt_name']})"
            elif columna["character_maximum_length"]:
                tipo = f"{columna['data_type']}({columna['character_maximum_length']})"

            atributo = {
                "tipo": tipo,
                "nullable": columna["is_nullable"] == "YES",
                "default": columna["column_default"],
                "descripcion": generar_descripcion_basica(table_name, nombre_columna)
            }

            for fk in foreign_keys:
                if fk["column_name"] == nombre_columna:
                    atributo["clave_foranea"] = {
                        "tabla": fk["foreign_table"],
                        "atributo": fk["foreign_column"]
                    }

            atributos[nombre_columna] = atributo

        resultado["entidades"][table_name] = {
            "descripcion": f"Tabla {table_name}.",
            "clave_primaria": primary_keys[0] if len(primary_keys) == 1 else primary_keys,
            "atributos": atributos
        }

    resultado["relaciones"] = inferir_relaciones(resultado["entidades"])

    return resultado

def generar_descripcion_basica(tabla: str, columna: str) -> str:
    if columna.startswith("id_"):
        return f"Identificador asociado a {columna.replace('id_', '')}."
    if columna == "titulo":
        return "Título del registro."
    if columna == "resumen":
        return "Resumen o descripción textual del registro."
    if columna == "fecha_envio":
        return "Fecha de envío o registro."
    return f"Campo {columna} de la tabla {tabla}."


def inferir_relaciones(entidades: dict) -> list:
    relaciones = []

    for tabla, info in entidades.items():
        atributos = info.get("atributos", {})

        fks = [
            (col, data["clave_foranea"])
            for col, data in atributos.items()
            if "clave_foranea" in data
        ]

        if len(fks) == 2 and len(atributos) == 2:
            relaciones.append({
                "tipo": "posible_muchos_a_muchos",
                "tabla_intermedia": tabla,
                "desde": fks[0][1]["tabla"],
                "hacia": fks[1][1]["tabla"],
                "descripcion": f"La tabla {tabla} parece representar una relación muchos a muchos."
            })

    return relaciones


@mcp.tool()
def consultar_base_segura(sql: str) -> dict:
    """
    Ejecuta una consulta SQL de solo lectura contra la base de datos.
    Solo permite SELECT, bloquea escritura y aplica LIMIT automáticamente.
    """
    return driver.execute_readonly(sql)
if __name__ == "__main__":
    mcp.run(transport="http", port=8000)