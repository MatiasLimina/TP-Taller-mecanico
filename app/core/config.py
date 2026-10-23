"""Configuración de la aplicación (pydantic-settings).

Toda la configuración sale del entorno o de un `.env` local no versionado.
`postgres_password` y `secret_key` no tienen default: si faltan o están vacíos
la aplicación se niega a arrancar.

No loguear `Settings.model_dump()`: incluye `database_url` con la contraseña.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

SECRET_KEY_MIN_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Base de datos
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = Field(5432, ge=1, le=65535)

    # Seguridad
    secret_key: SecretStr
    access_token_expire_seconds: int = Field(1800, gt=0)
    bcrypt_cost: int = Field(12, ge=4, le=31)
    bcrypt_max_concurrency: int = Field(4, ge=1)
    cookie_secure: bool = False

    # Pool y diagnóstico
    pool_size: int = Field(5, ge=1)
    max_overflow: int = Field(10, ge=0)
    sql_echo: bool = False

    @field_validator("postgres_password", "secret_key")
    @classmethod
    def _secreto_no_vacio(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("no puede estar vacío")
        return value

    @field_validator("secret_key")
    @classmethod
    def _secret_key_longitud(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < SECRET_KEY_MIN_LENGTH:
            raise ValueError(
                f"debe tener al menos {SECRET_KEY_MIN_LENGTH} caracteres"
            )
        return value

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
