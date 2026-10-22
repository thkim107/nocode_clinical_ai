from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import uuid
import os
import json
import requests
import time as _time
from enum import Enum, auto
from research.logger_config import logger
import ast
import re
from dotenv import load_dotenv

# 외부 라이브러리 가져오기
import anthropic
from openai import OpenAI

from audit_logger import audit_log_sync
from telemetry import record_llm_call_sync

load_dotenv()


@dataclass
class LLMResponse:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    response_id: Optional[str] = None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _sum_tokens(input_tokens: Optional[int], output_tokens: Optional[int], total_tokens: Optional[int]) -> Optional[int]:
    if total_tokens is not None:
        return total_tokens
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def _chat_completion_result(response: Any) -> LLMResponse:
    choices = _value(response, "choices", []) or []
    if not choices:
        raise RuntimeError("LLM 응답에 텍스트가 없습니다.")
    choice = choices[0]
    message = _value(choice, "message")
    text = _value(message, "content", "") or ""
    usage = _value(response, "usage")
    input_tokens = _value(usage, "prompt_tokens")
    output_tokens = _value(usage, "completion_tokens")
    total_tokens = _sum_tokens(input_tokens, output_tokens, _value(usage, "total_tokens"))
    prompt_details = _value(usage, "prompt_tokens_details")
    completion_details = _value(usage, "completion_tokens_details")
    return LLMResponse(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=_value(prompt_details, "cached_tokens"),
        reasoning_tokens=_value(completion_details, "reasoning_tokens"),
        finish_reason=_value(choice, "finish_reason"),
        response_id=_value(response, "id"),
    )


# 환경 변수 또는 기본값 설정

# LLM 제공자를 위한 Enum 추가
class LLMProviderType(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    SNUHLLM = "snuhllm"

class LLMProvider(ABC):
    """
    LLM 제공자를 위한 추상 기본 클래스.
    모든 LLM 구현은 이 클래스를 상속해야 합니다.
    """
    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._available_models = []
        self._default_model = None
        
    @property
    def api_key(self) -> str:
        return self._api_key
    
    @api_key.setter
    def api_key(self, key: str):
        self._api_key = key
        self._initialize_client()
    
    @property
    def available_models(self) -> List[str]:
        return self._available_models
    
    @property
    def default_model(self) -> str:
        return self._default_model
    
    @default_model.setter
    def default_model(self, model: str):
        if model in self._available_models:
            self._default_model = model
        else:
            raise ValueError(f"모델 '{model}'이(가) 사용 가능한 모델 목록에 없습니다.")
    
    @abstractmethod
    def _initialize_client(self):
        """API 클라이언트를 초기화합니다."""
        pass
    
    @abstractmethod
    def get_response(self, system_prompt: str, user_input: str, model: Optional[str] = None) -> LLMResponse:
        """
        사용자 입력과 시스템 프롬프트에 기반한 응답을 생성합니다.
        
        Args:
            system_prompt: LLM에게 전달할 시스템 지시사항
            user_input: 사용자의 입력/질문
            model: 사용할 특정 모델 (기본값: 제공자의 기본 모델)
            
        Returns:
            LLM의 텍스트 응답
        """
        pass
    
    def refresh_available_models(self) -> List[str]:
        """
        API를 통해 사용 가능한 최신 모델 목록을 가져옵니다.
        기본 구현은 정적으로 정의된 목록을 반환합니다.
        
        Returns:
            사용 가능한 모델 목록
        """
        return self._available_models


class AnthropicLLM(LLMProvider):
    """Anthropic의 Claude API 구현"""
    
    def __init__(self, api_key: str = ""):
        super().__init__(api_key)
        self._available_models = [
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-haiku-4-5",
        ]
        self._default_model = "claude-haiku-4-5"
        self._client = None
        if api_key:
            self._initialize_client()
    
    def _initialize_client(self):
        self._client = anthropic.Anthropic(api_key=self._api_key)
    
    def get_response(self, system_prompt: str, user_input: str, model: Optional[str] = None) -> LLMResponse:
        if not self._client:
            raise ValueError("API 키가 설정되지 않았습니다.")
        
        use_model = model if model else self._default_model
        
        # 메시지 구성
        messages = [
            {"role": "user", "content": user_input}
        ]
        
        # API 요청 매개변수 설정
        params = {
            "model": use_model,
            "messages": messages,
            "max_tokens": 10000,
        }
        
        # system_prompt가 제공된 경우 추가
        if system_prompt:
            params["system"] = system_prompt
        
        response = self._client.messages.create(**params)
        usage = _value(response, "usage")
        input_tokens = _value(usage, "input_tokens")
        output_tokens = _value(usage, "output_tokens")
        content = _value(response, "content", []) or []
        text = "".join(_value(block, "text", "") or "" for block in content)
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_sum_tokens(input_tokens, output_tokens, None),
            cached_input_tokens=_value(usage, "cache_read_input_tokens"),
            finish_reason=_value(response, "stop_reason"),
            response_id=_value(response, "id"),
        )
            
    def refresh_available_models(self) -> List[str]:
        """
        Anthropic API를 통해 사용 가능한 모델 목록을 가져옵니다.
        
        Returns:
            사용 가능한 모델 목록
        """
        if not self._client:
            return self._available_models
            
        try:
            # Anthropic API에서는 현재 모든 모델 목록을 가져오는 엔드포인트가 없음
            # 따라서 정적 목록 사용
            return self._available_models
        except Exception as e:
            print(f"Anthropic 모델 목록 가져오기 실패: {e}")
            return self._available_models


class OpenAILLM(LLMProvider):
    """OpenAI의 ChatGPT API 구현"""
    
    def __init__(self, api_key: str = ""):
        super().__init__(api_key)
        self._available_models = [
            "gpt-4o-2024-05-13",
            "gpt-4-turbo-2024-04-09",
            "gpt-4-0125-preview",
            "gpt-4-1106-preview",
            "gpt-4",
            "gpt-3.5-turbo-0125",
            "gpt-3.5-turbo"
        ]
        self._default_model = "gpt-4o-2024-05-13"
        self._client = None
        if api_key:
            self._initialize_client()
    
    def _initialize_client(self):
        self._client = OpenAI(api_key=self._api_key)
    
    def get_response(self, system_prompt: str, user_input: str, model: Optional[str] = None) -> LLMResponse:
        if not self._client:
            raise ValueError("API 키가 설정되지 않았습니다.")
        
        use_model = model if model else self._default_model
        
        response = self._client.responses.create(
            model=use_model,
            instructions=system_prompt,
            input=user_input,
        )
        usage = _value(response, "usage")
        input_tokens = _value(usage, "input_tokens")
        output_tokens = _value(usage, "output_tokens")
        input_details = _value(usage, "input_tokens_details")
        output_details = _value(usage, "output_tokens_details")
        return LLMResponse(
            text=_value(response, "output_text", "") or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_sum_tokens(input_tokens, output_tokens, _value(usage, "total_tokens")),
            cached_input_tokens=_value(input_details, "cached_tokens"),
            reasoning_tokens=_value(output_details, "reasoning_tokens"),
            finish_reason=_value(response, "status"),
            response_id=_value(response, "id"),
        )
    
    def refresh_available_models(self) -> List[str]:
        """
        OpenAI API를 통해 사용 가능한 모델 목록을 가져옵니다.
        
        Returns:
            사용 가능한 모델 목록
        """
        if not self._client:
            return self._available_models
            
        try:
            response = self._client.models.list()
            # GPT 모델만 필터링
            models = [model.id for model in response.data if 
                     model.id.startswith(('gpt-3', 'gpt-4'))]
            
            # 결과가 있을 경우에만 업데이트
            if models:
                self._available_models = models
                
            return self._available_models
        except Exception as e:
            print(f"OpenAI 모델 목록 가져오기 실패: {e}")
            return self._available_models


class OpenRouterLLM(LLMProvider):
    """OpenRouter API 구현 - OpenAI 호환 인터페이스, 모델명 직접 입력 방식"""

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str = "", model: str = "anthropic/claude-sonnet-4"):
        super().__init__(api_key)
        self._default_model = model
        self._available_models = [model]  # 사용자가 입력한 모델만 목록에 포함
        self._client = None
        if api_key:
            self._initialize_client()

    def _initialize_client(self):
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self.OPENROUTER_BASE_URL
        )

    def set_model(self, model: str):
        """사용자가 모델명을 직접 설정"""
        self._default_model = model
        if model not in self._available_models:
            self._available_models = [model]

    def get_response(self, system_prompt: str, user_input: str, model: Optional[str] = None) -> LLMResponse:
        TAG = 'openrouter-get-response'
        if not self._client:
            raise ValueError("API 키가 설정되지 않았습니다.")

        use_model = model if model else self._default_model
        logger.debug(f"{TAG} - model: {use_model}")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        response = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            max_tokens=10000,
        )
        return _chat_completion_result(response)

    def refresh_available_models(self) -> List[str]:
        """OpenRouter는 사용자 입력 모델을 사용하므로 현재 설정된 모델 반환"""
        return self._available_models


class SnuhLLM(LLMProvider):
    """SNUHLLM OpenAI compatible API 구현"""

    def __init__(self, api_key: str = "", base_url: str = "http://localhost:8000/v1", model: str = "default"):
        super().__init__(api_key)
        self._base_url = base_url
        self._default_model = model
        self._available_models = [model]
        self._client = None
        if api_key or base_url:
            self._initialize_client()

    def _initialize_client(self):
        self._client = OpenAI(
            api_key=self._api_key if self._api_key else "not-needed",
            base_url=self._base_url
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str):
        self._base_url = url
        self._initialize_client()

    def set_model(self, model: str):
        """모델명 설정"""
        self._default_model = model
        if model not in self._available_models:
            self._available_models = [model]

    def set_base_url(self, base_url: str):
        """Base URL 설정"""
        self._base_url = base_url
        self._initialize_client()

    def get_response(self, system_prompt: str, user_input: str, model: Optional[str] = None) -> LLMResponse:
        TAG = 'snuhllm-get-response'
        if not self._client:
            raise ValueError("클라이언트가 초기화되지 않았습니다.")

        use_model = model if model else self._default_model
        logger.debug(f"{TAG} - model: {use_model}, base_url: {self._base_url}")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        response = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            max_tokens=10000,
        )
        return _chat_completion_result(response)

    def refresh_available_models(self) -> List[str]:
        """SNUHLLM 서버에서 사용 가능한 모델 목록 가져오기 시도"""
        if not self._client:
            return self._available_models

        try:
            response = self._client.models.list()
            models = [model.id for model in response.data]
            if models:
                self._available_models = models
            return self._available_models
        except Exception as e:
            logger.debug(f"SNUHLLM 모델 목록 가져오기 실패: {e}")
            return self._available_models


class LLMManager:
    """
    다양한 LLM 제공자를 관리하고 사용자 요청을 처리하는 매니저 클래스
    """
    
    def __init__(self):
        self._providers = {
            LLMProviderType.ANTHROPIC: AnthropicLLM(),
            LLMProviderType.OPENAI: OpenAILLM(),
            LLMProviderType.OPENROUTER: OpenRouterLLM(),
            LLMProviderType.SNUHLLM: SnuhLLM()
        }
        self._current_provider = LLMProviderType.SNUHLLM
        self._current_model = None
        self._load_from_env()
    
    def _load_from_env(self):
        """API keys, default provider and model come from environment variables (.env)."""
        self._apply_env_overrides()
        if not self._current_model:
            self._current_model = self._providers[self._current_provider].default_model

    @staticmethod
    def _read_env(key: str) -> str:
        value = os.environ.get(key, "")
        return value.strip() if value else ""

    def _apply_env_overrides(self):
        """환경변수(.env 포함) 값을 config보다 우선 적용"""
        provider_env_keys = {
            LLMProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
            LLMProviderType.OPENAI: "OPENAI_API_KEY",
            LLMProviderType.OPENROUTER: "OPENROUTER_API_KEY",
            LLMProviderType.SNUHLLM: "SNUHLLM_API_KEY",
        }

        for provider, env_key in provider_env_keys.items():
            env_value = self._read_env(env_key)
            if env_value:
                self._providers[provider].api_key = env_value

        openrouter_model = self._read_env("OPENROUTER_MODEL")
        if openrouter_model:
            self._providers[LLMProviderType.OPENROUTER].set_model(openrouter_model)

        snuh_base_url = self._read_env("SNUHLLM_BASE_URL")
        if snuh_base_url:
            self._providers[LLMProviderType.SNUHLLM].set_base_url(snuh_base_url)

        snuh_model = self._read_env("SNUHLLM_MODEL")
        if snuh_model:
            self._providers[LLMProviderType.SNUHLLM].set_model(snuh_model)

        env_provider = self._read_env("LLM_DEFAULT_PROVIDER") or self._read_env("DEFAULT_PROVIDER")
        if env_provider:
            if env_provider in LLMProviderType._value2member_map_:
                self._current_provider = LLMProviderType(env_provider)
            else:
                logger.warning(f"유효하지 않은 LLM_DEFAULT_PROVIDER 값: {env_provider}")
        else:
            # default provider가 명시되지 않은 경우, 현재 provider에 키가 없으면
            # 키가 있는 provider로 자동 전환해 불필요한 인증 오류를 줄입니다.
            if not self._providers[self._current_provider].api_key:
                for candidate in [
                    LLMProviderType.ANTHROPIC,
                    LLMProviderType.OPENAI,
                    LLMProviderType.OPENROUTER,
                    LLMProviderType.SNUHLLM,
                ]:
                    if self._providers[candidate].api_key:
                        self._current_provider = candidate
                        logger.info(f"LLM 기본 provider 자동 전환: {candidate.value}")
                        break

        env_model = self._read_env("LLM_DEFAULT_MODEL")
        if env_model:
            if self._current_provider == LLMProviderType.OPENROUTER:
                self._providers[LLMProviderType.OPENROUTER].set_model(env_model)
                self._current_model = env_model
            elif self._current_provider == LLMProviderType.SNUHLLM:
                self._providers[LLMProviderType.SNUHLLM].set_model(env_model)
                self._current_model = env_model
            elif env_model in self._providers[self._current_provider].available_models:
                self._current_model = env_model
            else:
                logger.warning(
                    f"현재 provider({self._current_provider.value})에서 사용할 수 없는 LLM_DEFAULT_MODEL: {env_model}"
                )

        if not self._current_model or self._current_model not in self._providers[self._current_provider].available_models:
            self._current_model = self._providers[self._current_provider].default_model
    
    @property
    def current_provider(self) -> str:
        return self._current_provider.value
    
    @current_provider.setter
    def current_provider(self, provider: str):
        if provider in LLMProviderType._value2member_map_:
            self._current_provider = LLMProviderType(provider)
            # 현재 모델을 해당 제공자의 기본 모델로 설정
            self._current_model = self._providers[self._current_provider].default_model
        else:
            raise ValueError(f"제공자 '{provider}'가 유효하지 않습니다. 유효한 값: {', '.join([p.value for p in LLMProviderType])}")
    
    @property
    def current_model(self) -> str:
        if not self._current_model:
            self._current_model = self._providers[self._current_provider].default_model
        return self._current_model
    
    @current_model.setter
    def current_model(self, model: str):
        if model in self._providers[self._current_provider].available_models:
            self._current_model = model
        else:
            available_models = self._providers[self._current_provider].available_models
            raise ValueError(f"모델 '{model}'이(가) 현재 제공자의 사용 가능한 모델 목록에 없습니다. 사용 가능한 모델: {', '.join(available_models)}")
    
    def refresh_models(self, provider: Optional[str] = None) -> Dict[str, List[str]]:
        """
        지정된 제공자 또는 모든 제공자의 모델 목록을 새로고침합니다.
        
        Args:
            provider: 모델 목록을 새로고침할 제공자 (None인 경우 모든 제공자)
            
        Returns:
            새로고침된 모델 목록
        """
        try:
            if provider:
                if provider in LLMProviderType._value2member_map_:
                    provider_obj = self._providers[LLMProviderType(provider)]
                    models = provider_obj.refresh_available_models()
                    return {provider: models}
                else:
                    raise ValueError(f"유효하지 않은 제공자: {provider}")
            else:
                result = {}
                for provider_name, provider_obj in self._providers.items():
                    result[provider_name.value] = provider_obj.refresh_available_models()
                return result
        except Exception as e:
            print(f"모델 목록 새로고침 중 오류 발생: {e}")
            # 오류 발생 시 기존 모델 목록 반환
            return self.get_available_models(provider)

    def get_available_models(self, provider: Optional[str] = None) -> Dict[str, List[str]]:
        """사용 가능한 모델 목록 반환"""
        if provider:
            if provider in LLMProviderType._value2member_map_:
                return {provider: self._providers[LLMProviderType(provider)].available_models}
            else:
                raise ValueError(f"유효하지 않은 제공자: {provider}")
        else:
            return {p.value: self._providers[p].available_models for p in self._providers}
    
    def get_response(
        self, system_prompt: str, user_input: str,
        provider: Optional[str] = None, model: Optional[str] = None,
        telemetry_operation: Optional[str] = None,
        telemetry_section: Optional[str] = None,
        telemetry_attempt: Optional[int] = None,
        telemetry_metadata: Optional[dict] = None,
    ) -> str:
        """Generate text and record provider-reported usage for the current run."""
        use_provider = LLMProviderType(provider) if provider else self._current_provider

        if use_provider not in self._providers:
            return f"오류: 유효하지 않은 제공자 '{use_provider.value}'"

        use_model = model if model else self._providers[use_provider].default_model
        call_id = str(uuid.uuid4())
        response_data: Optional[LLMResponse] = None
        result_text = ""
        error_msg = None
        t0 = _time.time()
        try:
            provider_result = self._providers[use_provider].get_response(
                system_prompt=system_prompt,
                user_input=user_input,
                model=use_model,
            )
            response_data = (
                provider_result if isinstance(provider_result, LLMResponse)
                else LLMResponse(text=str(provider_result))
            )
            result_text = response_data.text
            return result_text
        except Exception as e:
            key_set = bool(self._providers[use_provider].api_key)
            error_msg = str(e)
            result_text = (
                f"LLM 응답 생성 중 오류 발생(provider={use_provider.value}, "
                f"model={use_model}, key_set={key_set}): {str(e)}"
            )
            return result_text
        finally:
            duration_ms = int((_time.time() - t0) * 1000)
            usage_summary = {
                "input_tokens": response_data.input_tokens if response_data else None,
                "output_tokens": response_data.output_tokens if response_data else None,
                "total_tokens": response_data.total_tokens if response_data else None,
            }
            audit_log_sync(
                "platform", use_provider.value, "get_response", "POST",
                request_summary={
                    "model": use_model,
                    "system_prompt_len": len(system_prompt),
                    "user_input_len": len(user_input),
                    "operation": telemetry_operation,
                    "section": telemetry_section,
                    "attempt": telemetry_attempt,
                },
                response_status=200 if error_msg is None else 500,
                response_summary={"response_len": len(result_text), "usage": usage_summary},
                duration_ms=duration_ms,
                error=error_msg,
            )
            metadata = dict(telemetry_metadata or {})
            if response_data and response_data.response_id:
                metadata["provider_response_id"] = response_data.response_id
            record_llm_call_sync(
                call_id=call_id,
                provider=use_provider.value,
                model=use_model,
                duration_ms=duration_ms,
                input_tokens=response_data.input_tokens if response_data else None,
                output_tokens=response_data.output_tokens if response_data else None,
                total_tokens=response_data.total_tokens if response_data else None,
                cached_input_tokens=response_data.cached_input_tokens if response_data else None,
                reasoning_tokens=response_data.reasoning_tokens if response_data else None,
                finish_reason=response_data.finish_reason if response_data else None,
                request_chars=len(system_prompt) + len(user_input),
                response_chars=len(result_text),
                message_count=2 if system_prompt else 1,
                tool_definition_count=0,
                attempt=telemetry_attempt,
                status="succeeded" if error_msg is None else "failed",
                error=error_msg,
                operation=telemetry_operation,
                section=telemetry_section,
                metadata=metadata or None,
            )

def to_json(text):
    """Parse JSON from LLM response, supporting ```json ... ``` format"""
    # First, try to extract from ```json ... ``` code block
    json_block_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_block_match:
        json_str = json_block_match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Also try ast.literal_eval for Python dict format (single quotes)
            try:
                return ast.literal_eval(json_str)
            except:
                pass

    # Fallback: find raw JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        dict_str = match.group()
        try:
            return json.loads(dict_str)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(dict_str)
            except:
                pass

    return None

# 싱글톤 인스턴스 생성
llm_manager = LLMManager()

# 하위 호환성을 위한 함수
def get_response(
    system_prompt, user_input, provider=None, model=None,
    *, telemetry_operation=None, telemetry_section=None,
    telemetry_attempt=None, telemetry_metadata=None,
):
    """기존 코드 호환성을 위한 함수
    
    Args:
        system_prompt (str): LLM에게 전달할 시스템 지시사항
        user_input (str): 사용자의 입력/질문
        provider (str, optional): 사용할 LLM 제공자. None인 경우 기본값 사용
        model (str, optional): 사용할 모델. None인 경우 제공자의 기본 모델 사용
        telemetry_*: 작업별 사용량 추적에 필요한 선택 항목
        
    Returns:
        str: LLM의 텍스트 응답
    """
    return llm_manager.get_response(
        system_prompt=system_prompt, 
        user_input=user_input, 
        provider=provider, 
        model=model,
        telemetry_operation=telemetry_operation,
        telemetry_section=telemetry_section,
        telemetry_attempt=telemetry_attempt,
        telemetry_metadata=telemetry_metadata,
    )

# 기존 글로벌 변수를 속성으로 매핑
@property
def now_api():
    return llm_manager.current_provider

@now_api.setter
def now_api(provider):
    llm_manager.current_provider = provider

@property
def now_model():
    return llm_manager.current_model

@now_model.setter
def now_model(model):
    llm_manager.current_model = model
