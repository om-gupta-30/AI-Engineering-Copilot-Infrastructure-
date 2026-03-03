# core — shared configuration, settings, base primitives, LLM service, and Redis service.
#
# Import directly from sub-modules to avoid circular imports at startup:
#   from ai_copilot_infra.core.config import settings
#   from ai_copilot_infra.core.llm_service import LLMService, LLMServiceError
#   from ai_copilot_infra.core.redis_service import RedisService, RedisServiceError
