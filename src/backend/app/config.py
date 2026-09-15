import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_env: str
    cors_origins: tuple[str, ...]
    database_url: str = 'sqlite:///' + (Path(__file__).resolve().parents[2] / 'artifacts/operations.db').as_posix()
    auto_migrate: bool = True
    model_directory: str = (Path(__file__).resolve().parents[2] / 'artifacts/models').as_posix()
    operator_api_key: str = field(default='', repr=False)
    request_body_limit_bytes: int = 1048576
    expensive_requests_per_minute: int = 30
    job_lease_seconds: int = 900
    readiness_require_model: bool = False
    readiness_require_data: bool = False
    demo_seed_on_start: bool = False
    demo_train_on_start: bool = False
    demo_dataset_directory: str = ''

    def __post_init__(self):
        if self.app_env not in ('development', 'test', 'production'):
            raise ValueError('APP_ENV must be development, test or production')
        if '*' in self.cors_origins:
            raise ValueError('Use explicit CORS origins, never wildcard credentials')
        for origin in self.cors_origins:
            url = urlsplit(origin)
            url.port  # reject malformed port specifications
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
                raise ValueError('CORS_ORIGINS must contain exact HTTP(S) origins without paths')
        if self.operator_api_key and len(self.operator_api_key) < 32:
            raise ValueError('OPERATOR_API_KEY must contain at least 32 characters')
        if self.operator_api_key and not self.operator_api_key.strip():
            raise ValueError('OPERATOR_API_KEY cannot be whitespace')
        if self.app_env == 'production' and not self.operator_api_key:
            raise ValueError('Production requires OPERATOR_API_KEY')
        if self.app_env == 'production' and (self.demo_seed_on_start or self.demo_train_on_start):
            raise ValueError('Demo seeding/training is prohibited in production')
        if self.demo_train_on_start and not self.demo_seed_on_start:
            raise ValueError('DEMO_TRAIN_ON_START requires DEMO_SEED_ON_START')
        if not 1024 <= self.request_body_limit_bytes <= 10485760:
            raise ValueError('REQUEST_BODY_LIMIT_BYTES must be 1024..10485760')
        if not 1 <= self.expensive_requests_per_minute <= 1000:
            raise ValueError('EXPENSIVE_REQUESTS_PER_MINUTE must be 1..1000')
        if not 30 <= self.job_lease_seconds <= 3600:
            raise ValueError('JOB_LEASE_SECONDS must be 30..3600')


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    environment = os.getenv('APP_ENV', 'development').strip().lower()
    url = os.getenv('DATABASE_URL', Settings.database_url)
    if environment == 'production' and not url.startswith('postgresql'):
        raise ValueError('Production requires a PostgreSQL DATABASE_URL')
    return Settings(
        app_env=environment,
        cors_origins=tuple(
            origin.strip() for origin in os.getenv(
                'CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173'
            ).split(',') if origin.strip()
        ),
        database_url=url,
        auto_migrate=os.getenv('AUTO_MIGRATE', 'false' if environment == 'production' else 'true').lower() == 'true',
        model_directory=str((Path(__file__).resolve().parents[2] / os.getenv('MODEL_DIRECTORY', 'artifacts/models')).resolve()),
        operator_api_key=os.getenv('OPERATOR_API_KEY', ''),
        request_body_limit_bytes=int(os.getenv('REQUEST_BODY_LIMIT_BYTES', '1048576')),
        expensive_requests_per_minute=int(os.getenv('EXPENSIVE_REQUESTS_PER_MINUTE', '30')),
        job_lease_seconds=int(os.getenv('JOB_LEASE_SECONDS', '900')),
        readiness_require_model=os.getenv('READINESS_REQUIRE_MODEL', 'true' if environment == 'production' else 'false').lower() == 'true',
        readiness_require_data=os.getenv('READINESS_REQUIRE_DATA', 'true' if environment == 'production' else 'false').lower() == 'true',
        demo_seed_on_start=os.getenv('DEMO_SEED_ON_START', 'false').lower() == 'true',
        demo_train_on_start=os.getenv('DEMO_TRAIN_ON_START', 'false').lower() == 'true',
        demo_dataset_directory=os.getenv('DEMO_DATASET_DIRECTORY', ''),
    )
