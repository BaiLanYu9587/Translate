from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class ApiProvider(ABC):
    def __init__(
        self,
        api_manager: Any,
        config: Any,
        model_info: Dict[str, Any],
        api_key: Optional[str],
        api_base: Optional[str] = None,
        provider_name: Optional[str] = None,  # Add provider_name
    ):
        self.api_manager = api_manager
        self.config = config
        self.model_info = model_info
        self.api_key = api_key
        self.api_base = api_base
        self.provider_name = provider_name  # Store provider_name

    @abstractmethod
    async def translate(
        self,
        prompt: str,
        gui_handler: Optional[Any] = None,
        is_retry: bool = False,
        original_text: Optional[str] = None,  # 添加 original_text 参数
    ) -> Dict[str, str]:
        pass
