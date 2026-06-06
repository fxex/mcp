import psycopg2
import psycopg2.extras
import json
import re
import uuid
import unicodedata
from typing import Literal, Any
from pydantic import BaseModel, Field
from fastmcp import FastMCP
from SafeSQLDriver import SafeSQLDriver

mcp = FastMCP("My MCP Server")

driver = SafeSQLDriver()

SQL_CONTEXT = {
    "agent_rules": {
        "mandatory_flow": [
            "No reescribir ni ampliar la pregunta del usuario original. Siempre tenerla en cuenta y cuando se responda alguna duda añadila en la pregunta original del usuario mas la aclaracion",
            "Primero llamar a preparar_consulta con la pregunta textual original del usuario.",
            "Si preparar_consulta devuelve status = needs_clarification, hacer exactamente esa pregunta al usuario y no hacer nada más.",
            "No llamar a consultar_base_segura hasta que preparar_consulta devuelva status = ready.",
            "Si preparar_consulta devuelve status = ready, generar SQL usando solamente la pregunta original, entities, filters, hints y este contexto.",
            "Después de generar SQL, llamar a consultar_base_segura con el preparation_token devuelto.",
        ],
        "sql_rules": [
            "Generar solamente SELECT.",
            "Usar LIMIT por defecto.",
            "Manejo de búsquedas de texto y nombres (CRÍTICO):",
            "  - Búsqueda Inexacta (Por defecto): Si el usuario busca nombres o frases sin comillas dobles (ej. Sandra Casas), DEBES separar las palabras y conectarlas con AND. Ejemplo: WHERE nombre ILIKE '%sandra%' AND nombre ILIKE '%casas%'. Esto es obligatorio para atrapar variantes como 'Sandra Isabel Casas'.",
            "  - Búsqueda Exacta: SOLO si el usuario encierra el término en comillas dobles (ej. \"Sandra Casas\"), asume contigüidad y no separes las palabras. Ejemplo: WHERE nombre ILIKE '%sandra casas%'.",
            "No usar unaccent(), porque no existe en esta base.",
            "Usar DISTINCT cuando haya riesgo de duplicados.",
            "No asumir que nombres iguales representan la misma entidad.",
        ]
    },

    "database_notes": [
        "La base no está normalizada.",
        "En la tabla autor, es posible que una misma persona aparezca bajo múltiples variaciones de nombre debido a inconsistencias en la base de datos. Por ejemplo en la base de datos puede ocurrir que exista sandra casas y sandra isabel casas con diferentes publicaciones",
        "El usuario es muy probable que no conozca algunos detalles como segundos nombres, temas, disciplinas, etc",
        "Existen autores y palabras clave repetidas con diferencias de mayúsculas, acentos, abreviaturas o palabras faltantes.",
        "Puede haber registros duplicados.",
        "Ante ambigüedad, pedir aclaración antes de generar SQL."
    ],
    "database_schema": {
        "tables": {
            "autor": {
                "description": (
                    "Personas autoras de publicaciones ICT. "
                    "No asumir unicidad del nombre porque puede haber"
                    "variaciones ortográficas o duplicados.",
                    "En esta tabla, es posible que una misma persona aparezca bajo múltiples variaciones de nombre debido a inconsistencias en la base de datos. Por ejemplo en la base de datos puede ocurrir que exista sandra casas y sandra isabel casas con diferentes publicaciones."
                ),
                "columns": {
                    "id_autor": {
                        "type": "integer",
                        "description": "Identificador único del autor."
                    },
                    "nombre": {
                        "type": "varchar(255)",
                        "description": (
                            "Nombre completo del autor. "
                            "Usar ILIKE para búsquedas porque puede haber "
                            "diferencias de mayúsculas o escritura."
                        )
                    }
                }
            },

            "ict": {
                "description": (
                    "Producciones académicas/publicaciones (papers, artículos, dossier)."
                ),
                "columns": {
                    "id_ict": {
                        "type": "integer",
                        "description": "Identificador único de la publicación."
                    },
                    "titulo": {
                        "type": "text",
                        "description": "Título de la publicación."
                    },
                    "resumen": {
                        "type": "text",
                        "description": "Resumen o abstract de la publicación."
                    },
                    "tipo": {
                        "type": "tipo_ict",
                        "description": (
                            "Tipo de publicación. "
                            "Valores permitidos: ARTICULO, DOSSIER."
                        )
                    },
                    "idioma": {
                        "type": "varchar(8)",
                        "description": (
                            "Idioma de la publicación. "
                            "Ejemplo: es, en, pt."
                        )
                    },
                    "disciplinas": {
                        "type": "varchar(50)",
                        "description": (
                            "Disciplina o área temática asociada."
                        )
                    },
                    "estado": {
                        "type": "estado_ict",
                        "description": (
                            "Estado editorial. "
                            "Valores permitidos: PUBLICADO, REVISION."
                        )
                    },
                    "doi": {
                        "type": "varchar(255)",
                        "description": "DOI de la publicación."
                    },
                    "fecha_envio": {
                        "type": "date",
                        "description": (
                            "Fecha de envío de la publicación. "
                            "Solo usar para 'últimos' o 'recientes' si el usuario "
                            "acepta usar esta fecha."
                        )
                    },
                    "volumen": {
                        "type": "int",
                        "description": "Volumen de la publicación."
                    },
                    "numero": {
                        "type": "int",
                        "description": "Número de edición."
                    },
                    "pagina_inicio": {
                        "type": "int",
                        "description": "Página inicial."
                    },
                    "pagina_fin": {
                        "type": "int",
                        "description": "Página final."
                    }
                }
            },

            "palabra_clave": {
                "description": (
                    "Palabras clave/ejes/tópicos asociados a publicaciones."
                ),
                "columns": {
                    "id_palabra": {
                        "type": "integer",
                        "description": "Identificador único."
                    },
                    "palabra": {
                        "type": "varchar(255)",
                        "description": (
                            "Texto de la palabra clave. "
                            "Puede tener duplicados o variaciones."
                        )
                    }
                }
            },

            "ict_autor": {
                "description": (
                    "Tabla intermedia muchos-a-muchos entre ict y autor."
                ),
                "columns": {
                    "id_ict": {
                        "type": "integer",
                        "description": "FK a ict.id_ict"
                    },
                    "id_autor": {
                        "type": "integer",
                        "description": "FK a autor.id_autor"
                    }
                }
            },

            "ict_palabra": {
                "description": (
                    "Tabla intermedia muchos-a-muchos entre ict y palabra_clave."
                ),
                "columns": {
                    "id_ict": {
                        "type": "integer",
                        "description": "FK a ict.id_ict"
                    },
                    "id_palabra": {
                        "type": "integer",
                        "description": "FK a palabra_clave.id_palabra"
                    }
                }
            }
        },

        "relationships": [
            {
                "from": "ict",
                "to": "autor",
                "through": "ict_autor",
                "join": [
                    "ict.id_ict = ict_autor.id_ict",
                    "autor.id_autor = ict_autor.id_autor"
                ],
                "description": (
                    "Relación muchos-a-muchos entre publicaciones y autores."
                )
            },
            {
                "from": "ict",
                "to": "palabra_clave",
                "through": "ict_palabra",
                "join": [
                    "ict.id_ict = ict_palabra.id_ict",
                    "palabra_clave.id_palabra = ict_palabra.id_palabra"
                ],
                "description": (
                    "Relación muchos-a-muchos entre publicaciones y palabras clave."
                )
            }
        ]
    },
    "table_synonyms": {
        "autor": [
            "autor", "autores", "investigador", "investigadores",
            "docente", "docentes", "no docente", "no docentes"
        ],
        "ict": [
            "publicacion", "publicaciones", "produccion",
            "paper", "papers", "articulo", "articulos",
            "trabajo", "trabajos"
        ],
        "palabra_clave": [
            "palabra clave", "palabras clave",
            "eje", "ejes", "topicos", "topico",
            "tópicos", "tópico",
            "tema", "temas", "contenido", "contenidos"
        ]
    },

    "column_synonyms": {
        "autor.nombre": [
            "nombre", "autor", "investigador", "docente",
            "apellido", "apellido y nombre"
        ],
        "ict.titulo": [
            "titulo", "título",
            "nombre del trabajo",
            "nombre de la publicacion",
            "nombre de la publicación",
            "paper", "articulo", "artículo"
        ],
        "ict.tipo_ict": [
            "tipo", "tipo de publicacion", "tipo de publicación",
            "tipo ict", "articulo", "artículo", "dossier"
        ],
        "ict.estado_ict": [
            "estado", "estado de publicacion",
            "estado de publicación",
            "publicado", "publicada", "revision", "revisión"
        ]
    },

    "data_values": {
        "ict.tipo_ict": {
            "ARTICULO": ["articulo", "artículo", "paper"],
            "DOSSIER": ["dossier"]
        },
        "ict.estado_ict": {
            "PUBLICADO": ["publicado", "publicada", "publicados"],
            "REVISION": ["revision", "revisión", "en revision", "en revisión"]
        }
    },

    "normalization_rules": {
        "text_search": [
            "Usar ILIKE para búsquedas textuales.",
            "Considerar diferencias de acentos y mayúsculas.",
            "No usar unaccent().",
            "Usar DISTINCT si hay riesgo de duplicados."
        ],
        "duplicates": [
            "No asumir que nombres iguales representan una única entidad.",
            "No asumir que palabras clave repetidas están normalizadas.",
            "Si el usuario pide conteos, aclarar si quiere contar filas o entidades únicas."
        ]
    },

    "ambiguity_rules": [
        {
            "term": "autor",
            "problem": "Puede referirse a la tabla autor o a una columna textual relacionada con ict.",
            "question": "¿Querés buscar datos del autor como persona o publicaciones asociadas a ese autor?"
        },
        {
            "term": "articulo",
            "problem": "Puede referirse al tipo_ict ARTICULO o a una publicación en general.",
            "question": "¿Querés filtrar por el tipo de paper o usar artículo como sinónimo general de paper?"
        },
        {
            "term": "tema/eje/tópico/contenido",
            "problem": "Puede referirse a palabra_clave o a una búsqueda textual en el título/resumen de la publicación.",
            "question": "¿Querés buscar por palabra clave/eje registrado o hacer una búsqueda textual en título/resumen?"
        }
    ]
}

class ConsultaPreparada(BaseModel):
    status: Literal["ready", "needs_clarification", "error"]

    original_question: str | None = None
    question: str | None = None
    reason: str | None = None
    preparation_token: str | None = None

    intent: str | None = None
    detected_entities: dict[str, Any] = Field(default_factory=dict)

    allowed_tables: list[str] = Field(default_factory=list)
    allowed_columns: list[str] = Field(default_factory=list)
    required_joins: list[str] = Field(default_factory=list)

    sql_constraints: dict[str, Any] = Field(default_factory=dict)
    generation_instructions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


PREPARATION_TOKENS: dict[str, ConsultaPreparada] = {}


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _contains_word(q: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(_norm(term))}\b", q) is not None


def _contains_any(q: str, terms: list[str]) -> bool:
    return any(_contains_word(q, term) for term in terms)


def _extract_quoted_terms(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"|\'([^\']+)\'', text)


def _flatten_quoted_terms(matches: list[tuple[str, str]]) -> list[str]:
    return [a or b for a, b in matches if a or b]


def _looks_like_author_query(q: str) -> bool:
    return _contains_any(q, [
        "autor", "autores", "investigador", "investigadores",
        "docente", "docentes", "escribio", "escribieron",
        "publico", "publicaron", "de", "participante", "coautor", "participo", "participantes", "coautores", 
        "creadores", "creador", "trabajo", "hizo"
    ])


def _looks_like_publication_query(q: str) -> bool:
    return _contains_any(q, [
        "publicacion", "publicaciones", "produccion", "producciones",
        "paper", "papers", "articulo", "articulos",
        "trabajo", "trabajos", "titulo", "resumen"
    ])


def _looks_like_keyword_query(q: str) -> bool:
    return _contains_any(q, [
        "palabra clave", "palabras clave", "palabras claves", "eje", "ejes",
        "tema", "temas", "topico", "topicos",
        "contenido", "contenidos", "sobre", "temáticas principales", "temática principal"
    ])


def _looks_like_count_query(q: str) -> bool:
    return _contains_any(q, [
        "cuantos", "cuantas", "cantidad", "total",
        "contar", "numero de", "número de"
    ])


def _looks_like_recent_query(q: str) -> bool:
    return _contains_any(q, [
        "ultimo", "ultimos", "ultima", "ultimas",
        "reciente", "recientes", "mas nuevo", "más nuevo"
    ])


def _detect_type_filter(q: str) -> str | None:
    if _contains_any(q, ["dossier", "dossiers"]):
        return "DOSSIER"

    if _contains_any(q, ["tipo articulo", "tipo artículos", "tipo paper"]):
        return "ARTICULO"

    if _contains_any(q, ["solo articulos", "solamente articulos", "solo articulos", "solo articulos"]):
        return "ARTICULO"

    return None


def _detect_estado_filter(q: str) -> str | None:
    if _contains_any(q, ["publicado", "publicada", "publicados", "publicadas"]):
        return "PUBLICADO"

    if _contains_any(q, ["revision", "revisión", "en revision", "en revisión"]):
        return "REVISION"

    return None


def _build_constraints() -> dict[str, Any]:
    return {
        "only_select": True,
        "limit_required": True,
        "default_limit": 25,
        "max_limit": 100,
        "no_select_star": True,
        "text_search_operator": "ILIKE",
        "forbidden_functions": ["unaccent"],
        "forbidden_statements": [
            "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
            "CREATE", "TRUNCATE", "GRANT", "REVOKE"
        ],
        "must_use_preparation_token": True
    }


def _base_columns() -> list[str]:
    return [
        "ict.id_ict",
        "ict.titulo",
        "ict.resumen",
        "ict.tipo",
        "ict.idioma",
        "ict.disciplinas",
        "ict.estado",
        "ict.doi",
        "ict.fecha_envio",
        "ict.volumen",
        "ict.numero",
        "ict.pagina_inicio",
        "ict.pagina_fin"
    ]


def _author_columns() -> list[str]:
    return [
        "autor.id_autor",
        "autor.nombre",
        "ict_autor.id_ict",
        "ict_autor.id_autor"
    ]


def _keyword_columns() -> list[str]:
    return [
        "palabra_clave.id_palabra",
        "palabra_clave.palabra",
        "ict_palabra.id_ict",
        "ict_palabra.id_palabra"
    ]


def _author_joins() -> list[str]:
    return [
        "ict.id_ict = ict_autor.id_ict",
        "autor.id_autor = ict_autor.id_autor"
    ]


def _keyword_joins() -> list[str]:
    return [
        "ict.id_ict = ict_palabra.id_ict",
        "palabra_clave.id_palabra = ict_palabra.id_palabra"
    ]


@mcp.resource("context://sql/semantic")
def sql_semantic_resource() -> dict:
    """Contexto semántico de la base SQL."""
    return SQL_CONTEXT

@mcp.tool
def get_sql_context() -> dict:
    """Devuelve sinónimos, reglas de joins y advertencias de la base."""
    return SQL_CONTEXT

@mcp.tool()
def preparar_consulta(pregunta: str) -> ConsultaPreparada:
    """
    Prepara una consulta SQL para que el LLM genere SQL de forma controlada.
    No genera SQL.
    Devuelve un contrato explícito: intención, tablas permitidas, joins requeridos,
    columnas permitidas, filtros detectados y restricciones obligatorias.
    """

    if not pregunta or not pregunta.strip():
        return ConsultaPreparada(
            status="error",
            reason="La pregunta está vacía."
        )

    original = pregunta.strip()
    q = _norm(original)

    habla_de_autor = _looks_like_author_query(q)
    habla_de_ict = _looks_like_publication_query(q)
    habla_de_palabra_clave = _looks_like_keyword_query(q)

    tipo_filter = _detect_type_filter(q)
    estado_filter = _detect_estado_filter(q)

    quoted_terms = _flatten_quoted_terms(_extract_quoted_terms(original))

    detected_entities: dict[str, Any] = {
        "quoted_terms": quoted_terms,
        "filters": {}
    }

    # Ambigüedad fuerte: "artículo" puede ser tipo o sinónimo general.
    habla_de_articulo = _contains_any(q, [
        "articulo", "articulos", "artículo", "artículos",
        "paper", "papers"
    ])

    if habla_de_articulo and tipo_filter is None and not _contains_any(q, [
        "publicacion", "publicaciones", "trabajo", "trabajos",
        "produccion", "producciones"
    ]):
        return ConsultaPreparada(
            status="needs_clarification",
            original_question=original,
            question=(
                "Cuando decís artículo/paper, ¿querés filtrar por "
                "ict.tipo = 'ARTICULO' o lo usás como sinónimo general de publicación?"
            ),
            reason="Artículo/paper puede ser un valor de ict.tipo o un sinónimo general de publicación."
        )

    # Ambigüedad: tema/contenido/sobre puede ser keyword registrada o texto libre.
    if _contains_any(q, ["tema", "temas", "topico", "topicos", "contenido", "contenidos", "sobre"]):
        if not _contains_any(q, ["palabra clave", "palabras clave", "eje", "ejes", "titulo", "resumen"]):
            return ConsultaPreparada(
                status="needs_clarification",
                original_question=original,
                question=(
                    "¿Querés buscar ese tema como palabra clave/eje registrado "
                    "o hacer una búsqueda textual en ict.titulo/ict.resumen?"
                ),
                reason="Tema/contenido puede mapear a palabra_clave o a búsqueda textual en título/resumen."
            )

    # Construcción del contrato permitido.
    allowed_tables = {"ict"}
    allowed_columns = set(_base_columns())
    required_joins: list[str] = []

    if habla_de_autor:
        allowed_tables.update(["autor", "ict_autor"])
        allowed_columns.update(_author_columns())
        required_joins.extend(_author_joins())

    if habla_de_palabra_clave:
        allowed_tables.update(["palabra_clave", "ict_palabra"])
        allowed_columns.update(_keyword_columns())
        required_joins.extend(_keyword_joins())

    if tipo_filter:
        detected_entities["filters"]["ict.tipo"] = tipo_filter

    if estado_filter:
        detected_entities["filters"]["ict.estado"] = estado_filter

    if quoted_terms:
        detected_entities["possible_text_terms"] = quoted_terms

    # Inferencia conservadora de intención.
    if habla_de_autor and not habla_de_ict:
        intent = "author_lookup_or_author_publications"
    elif habla_de_palabra_clave:
        intent = "publication_search_by_keyword_or_topic"
    else:
        intent = "publication_search"

    warnings = [
        "La base no está normalizada.",
        "Puede haber autores, palabras clave o publicaciones duplicadas.",
        "En los datos de la tabla autor, es posible que una misma persona aparezca bajo múltiples variaciones de nombre debido a inconsistencias en la base de datos. Por ejemplo en la base de datos puede ocurrir que exista sandra casas y sandra isabel casas con diferentes publicaciones",
        "Usar DISTINCT si hay joins muchos-a-muchos o riesgo de duplicados.",
        "No asumir que nombres iguales representan una única entidad.",
        "No usar columnas ni tablas fuera del contrato devuelto por preparar_consulta."
    ]

    generation_instructions = [
        "Generar una única consulta SQL.",
        "La consulta debe ser solamente SELECT.",
        "Usar únicamente allowed_tables, allowed_columns y required_joins.",
        "No usar SELECT *.",
        "Agregar LIMIT si el usuario no pidió explícitamente todos los resultados.",
        "Usar ILIKE para búsquedas textuales.",
        "No usar unaccent().",
        "Si hay joins con autor o palabra_clave, usar DISTINCT sobre ict.id_ict cuando se listen publicaciones.",
        "Después de generar SQL, llamar a consultar_base_segura con este preparation_token."
    ]

    token = str(uuid.uuid4())

    contract = ConsultaPreparada(
        status="ready",
        original_question=original,
        reason="No se detectaron ambigüedades bloqueantes.",
        preparation_token=token,
        intent=intent,
        detected_entities=detected_entities,
        allowed_tables=sorted(allowed_tables),
        allowed_columns=sorted(allowed_columns),
        required_joins=required_joins,
        sql_constraints=_build_constraints(),
        generation_instructions=generation_instructions,
        warnings=warnings
    )

    PREPARATION_TOKENS[token] = contract
    return contract

@mcp.tool()
def consultar_base_segura(sql: str, preparation_token: str) -> dict:
    """
    Ejecuta SQL readonly solo si antes se llamó correctamente a preparar_consulta.
    """
    contract = PREPARATION_TOKENS.get(preparation_token)

    if not contract:
        return {
            "success": False,
            "error": (
                "Token inválido. Primero debés llamar a preparar_consulta "
                "y usar el preparation_token devuelto."
            )
        }

    del PREPARATION_TOKENS[preparation_token]

    return driver.execute_readonly(sql)

if __name__ == "__main__":
    mcp.run(transport="http", port=8000)