from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, List, Optional
import traceback

from research import llm_manager
from research.logger_config import logger

# LLM 관리용 라우터 생성
llm_router = APIRouter(
    prefix="/llm",
    tags=["llm"]
)

class ProviderModelData(BaseModel):
    provider: str
    model: str

@llm_router.get("/providers", summary="사용 가능한 LLM 제공자 목록을 반환합니다")
async def get_providers():
    TAG = 'get_providers'
    logger.info(f"{TAG} - 시작")
    
    try:
        providers = list(llm_manager.llm_manager._providers.keys())
        current = llm_manager.llm_manager.current_provider
        
        logger.info(f"{TAG} - 종료")
        return {
            "providers": providers,
            "current": current
        }
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"제공자 목록 조회 중 오류 발생: {str(e)}"
        )

@llm_router.post("/provider", summary="현재 사용 중인 LLM 제공자를 변경합니다")
async def set_provider(provider: str):
    TAG = 'set_provider'
    logger.info(f"{TAG} - 시작")
    
    try:
        llm_manager.llm_manager.current_provider = provider
        logger.debug(f"{TAG} - 제공자 변경: {provider}")
        
        logger.info(f"{TAG} - 종료")
        return {"message": f"제공자가 {provider}로 변경되었습니다", "model": llm_manager.llm_manager.current_model}
    except ValueError as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"제공자 변경 중 오류 발생: {str(e)}"
        )

@llm_router.get("/models", summary="사용 가능한 모델 목록을 반환합니다")
async def get_models(provider: Optional[str] = None, refresh: bool = False):
    TAG = 'get_models'
    logger.info(f"{TAG} - 시작")
    
    try:
        # refresh가 True거나 provider가 제공된 경우 API에서 최신 모델 목록을 가져옵니다
        if refresh or provider:
            logger.debug(f"{TAG} - 실시간 모델 목록 요청 중: provider={provider}")
            models = llm_manager.llm_manager.refresh_models(provider)
        else:
            logger.debug(f"{TAG} - 캐시된 모델 목록 요청 중")
            models = llm_manager.llm_manager.get_available_models(provider)
            
        current_provider = llm_manager.llm_manager.current_provider
        current_model = llm_manager.llm_manager.current_model
        
        logger.info(f"{TAG} - 종료")
        return {
            "models": models,
            "current_provider": current_provider,
            "current_model": current_model
        }
    except ValueError as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"모델 목록 조회 중 오류 발생: {str(e)}"
        )

@llm_router.post("/model", summary="현재 사용 중인 모델을 변경합니다")
async def set_model(model: str):
    TAG = 'set_model'
    logger.info(f"{TAG} - 시작")
    
    try:
        llm_manager.llm_manager.current_model = model
        logger.debug(f"{TAG} - 모델 변경: {model}")
        
        logger.info(f"{TAG} - 종료")
        return {"message": f"모델이 {model}로 변경되었습니다"}
    except ValueError as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"모델 변경 중 오류 발생: {str(e)}"
        )

@llm_router.post("/provider_model", summary="제공자와 모델을 동시에 설정합니다")
async def set_provider_model(data: ProviderModelData):
    TAG = 'set_provider_model'
    logger.info(f"{TAG} - 시작")
    
    try:
        # 먼저 제공자 변경
        llm_manager.llm_manager.current_provider = data.provider
        logger.debug(f"{TAG} - 제공자 변경: {data.provider}")
        
        # 그 다음 모델 변경
        llm_manager.llm_manager.current_model = data.model
        logger.debug(f"{TAG} - 모델 변경: {data.model}")
        
        logger.info(f"{TAG} - 종료")
        return {"message": f"제공자가 {data.provider}로, 모델이 {data.model}로 변경되었습니다"}
    except ValueError as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"제공자 및 모델 변경 중 오류 발생: {str(e)}"
        )

@llm_router.get("/config", summary="현재 LLM 설정을 반환합니다")
async def get_config():
    TAG = 'get_config'
    logger.info(f"{TAG} - 시작")

    try:
        config = {
            "current_provider": llm_manager.llm_manager.current_provider,
            "current_model": llm_manager.llm_manager.current_model,
            "providers": [p.value for p in llm_manager.llm_manager._providers.keys()],
            "available_models": llm_manager.llm_manager.get_available_models(),
            "openrouter_model": llm_manager.llm_manager._providers[llm_manager.LLMProviderType.OPENROUTER].default_model
        }

        logger.info(f"{TAG} - 종료")
        return config
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 조회 중 오류 발생: {str(e)}"
        )