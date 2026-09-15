from contextlib import contextmanager
from threading import Lock

import oracledb

from app.config import Settings
from app.errors import ServiceError


class OracleDatabase:
    """Lazy, bounded pool. Writes are only for explicit backend command handlers, never model tools."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._pool = None
        self._lock = Lock()

    def pool(self):
        with self._lock:
            if self._pool is None:
                if not self.settings.database_ready:
                    raise ServiceError("DATABASE_NOT_CONFIGURED", "Oracle configuration is incomplete.", 503)
                self._pool = oracledb.create_pool(
                    user=self.settings.db_user, password=self.settings.db_password.get_secret_value(),
                    dsn=self.settings.db_tns_alias, config_dir=self.settings.wallet_path,
                    wallet_location=self.settings.wallet_path,
                    wallet_password=self.settings.db_wallet_password.get_secret_value(),
                    min=self.settings.db_pool_min, max=self.settings.db_pool_max,
                    increment=self.settings.db_pool_increment,
                    getmode=oracledb.POOL_GETMODE_TIMEDWAIT, wait_timeout=5000,
                    tcp_connect_timeout=5, retry_count=0,
                )
            return self._pool

    @contextmanager
    def read(self):
        try:
            with self.pool().acquire() as connection:
                connection.call_timeout = 10000
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION READ ONLY")
                        cursor.execute("""SELECT USER, SYS_CONTEXT('USERENV','SESSION_USER'),
                            SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual""")
                        if cursor.fetchone() != ("AI_POD_STAFFING",) * 3:
                            raise ServiceError("WRONG_SCHEMA", "Unexpected Oracle schema. Operation stopped.", 503)
                    yield connection
                finally:
                    connection.rollback()
        except oracledb.Error as error:
            # Never return driver messages: they can contain connect descriptors or SQL input.
            raise ServiceError("DATABASE_UNAVAILABLE", "Oracle is temporarily unavailable.", 503) from error

    def ping(self):
        with self.read() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM dual")
            if cursor.fetchone() != (1,):
                raise ServiceError("DATABASE_UNAVAILABLE", "Oracle readiness check failed.", 503)

    @contextmanager
    def write(self):
        try:
            with self.pool().acquire() as connection:
                connection.call_timeout = 10000
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("ALTER SESSION DISABLE PARALLEL DML")
                        cursor.execute("ALTER SESSION DISABLE PARALLEL QUERY")
                        cursor.execute("SELECT USER, SYS_CONTEXT('USERENV','SESSION_USER'), SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual")
                        if cursor.fetchone() != ("AI_POD_STAFFING",) * 3:
                            raise ServiceError("WRONG_SCHEMA", "Unexpected Oracle schema. Operation stopped.", 503)
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except oracledb.Error as error:
            raise ServiceError("DATABASE_UNAVAILABLE", "Oracle write could not be confirmed. Check the operation ID before retrying.", 503) from error

    def close(self):
        with self._lock:
            if self._pool is not None:
                self._pool.close(force=True)
                self._pool = None
