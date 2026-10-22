"""
Prompts package - 환경변수 PROMPT_LANG에 따라 언어별 프롬프트 모듈을 동적으로 로드합니다.

사용법:
    from prompts import irb_prompt
    from prompts import research_prompt
    from prompts import pubmed_prompt

환경변수:
    PROMPT_LANG: 'ko' (기본값) 또는 'en'
"""

import os
import importlib

# 환경변수에서 언어 설정 읽기 (기본값: 'ko')
PROMPT_LANG = os.environ.get('PROMPT_LANG', 'ko').lower()

# 지원하는 언어 목록
SUPPORTED_LANGS = ['ko', 'en']

if PROMPT_LANG not in SUPPORTED_LANGS:
    raise ValueError(f"지원하지 않는 언어입니다: {PROMPT_LANG}. 지원 언어: {SUPPORTED_LANGS}")

# 동적으로 해당 언어의 프롬프트 모듈 로드
irb_prompt = importlib.import_module(f'.{PROMPT_LANG}.irb_prompt', package='research.prompts')
research_prompt = importlib.import_module(f'.{PROMPT_LANG}.research_prompt', package='research.prompts')
pubmed_prompt = importlib.import_module(f'.{PROMPT_LANG}.pubmed_prompt', package='research.prompts')

__all__ = ['irb_prompt', 'research_prompt', 'pubmed_prompt', 'PROMPT_LANG']
