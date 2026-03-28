import os

from banking.utils.logger import get_logger

logger = get_logger(__name__)


class LangfuseService:
    """Service for managing Langfuse observability integration."""

    _instance = None
    _handler: object | None = None
    _client: object | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = False
            self._enabled = False

    def initialize(self) -> bool:
        if self._initialized:
            logger.info("LangfuseService already initialized")
            return self._enabled

        langfuse_enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
        if not langfuse_enabled:
            logger.info("Langfuse observability is disabled")
            self._initialized = True
            return False

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        if not public_key or not secret_key:
            logger.warning("Langfuse keys not configured - observability disabled")
            self._initialized = True
            return False

        try:
            from langfuse import get_client
            from langfuse.langchain import CallbackHandler

            self._handler = CallbackHandler()
            self._client = get_client()

            logger.info("Langfuse observability initialized successfully")
            logger.info("Host: %s", host)

            if self.verify_connection():
                self._enabled = True
                self._initialized = True
                return True

            logger.error("Langfuse connection verification failed")
            self._handler = None
            self._client = None
            self._initialized = True
            return False
        except ImportError:
            logger.warning("Langfuse package not installed")
            self._initialized = True
            return False
        except Exception as exc:
            logger.error("Failed to initialize Langfuse: %s", exc)
            self._initialized = True
            return False

    def verify_connection(self) -> bool:
        if not self._client:
            return False
        try:
            if self._client.auth_check():
                logger.info("Langfuse connection verified successfully")
                return True
        except Exception as exc:
            logger.error("Langfuse connection error: %s", exc)
        return False

    def get_handler(self):
        return self._handler

    def flush(self):
        if self._handler and hasattr(self._handler, "flush"):
            self._handler.flush()
        if self._client and hasattr(self._client, "flush"):
            self._client.flush()


langfuse_service = LangfuseService()
