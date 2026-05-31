from dotenv import load_dotenv
import os
import re
import sqlparse
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

class SafeSQLDriver:
    def __init__(self):
        self.conn_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
        }

        self.allowed_statements = {"SELECT"}
        self.blocked_keywords = {
            "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
            "TRUNCATE", "GRANT", "REVOKE", "MERGE", "CALL", "EXECUTE",
            "COPY", "VACUUM", "ANALYZE"
        }

        self.default_limit = 50
        self.max_limit = 200

    def connect(self):
        return psycopg2.connect(**self.conn_params)

    def execute_readonly(self, sql: str, params: tuple | None = None) -> dict:
        sql = self._normalize_sql(sql)
        self._validate_readonly_sql(sql)

        sql = self._ensure_limit(sql)

        with self.connect() as conn:
            conn.set_session(readonly=True, autocommit=True)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if params is None:
                    cur.execute(sql)
                else:
                    cur.execute(sql, params)
                rows = cur.fetchall()

        return {
            "success": True,
            "sql": sql,
            "row_count": len(rows),
            "rows": [dict(row) for row in rows],
        }

    def _normalize_sql(self, sql: str) -> str:
        if not sql or not sql.strip():
            raise ValueError("La consulta SQL está vacía")

        sql = sql.strip()

        if "\x00" in sql:
            raise ValueError("La consulta contiene caracteres inválidos")

        return sql

    def _validate_readonly_sql(self, sql: str) -> None:
        parsed = sqlparse.parse(sql)

        if len(parsed) != 1:
            raise ValueError("Solo se permite una sentencia SQL por ejecución")

        statement = parsed[0]
        statement_type = statement.get_type().upper()

        if statement_type not in self.allowed_statements:
            raise ValueError(f"Solo se permiten consultas SELECT. Recibido: {statement_type}")

        upper_sql = sql.upper()

        for keyword in self.blocked_keywords:
            if re.search(rf"\b{keyword}\b", upper_sql):
                raise ValueError(f"Keyword no permitida: {keyword}")

        if ";" in sql.rstrip(";"):
            raise ValueError("No se permiten múltiples sentencias SQL")

        if "--" in sql or "/*" in sql or "*/" in sql:
            raise ValueError("No se permiten comentarios SQL")

    def _ensure_limit(self, sql: str) -> str:
        upper_sql = sql.upper()

        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", upper_sql)

        if limit_match:
            limit_value = int(limit_match.group(1))

            if limit_value > self.max_limit:
                sql = re.sub(
                    r"\bLIMIT\s+\d+\b",
                    f"LIMIT {self.max_limit}",
                    sql,
                    flags=re.IGNORECASE
                )

            return sql

        return f"{sql.rstrip(';')} LIMIT {self.max_limit}"