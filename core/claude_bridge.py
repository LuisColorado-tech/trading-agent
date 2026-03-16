"""
LLMBridge — LangChain bridge hacia modelos LLM (OpenAI / Anthropic).
Módulo central de comunicación IA del Trading Agent.

Responsabilidades:
- Enviar payloads estructurados al LLM configurado via LangChain
- Parsear respuestas en JSON estandarizado
- Devolver resultado neutral si el LLM falla (nunca detener el sistema)
- Registrar latencia y tokens usados

Providers soportados:
- openai: GPT-4o-mini (default, más barato), GPT-4o, GPT-4-turbo
- anthropic: Claude Opus, Sonnet, Haiku

Puntos de intervención:
1. sentiment_analysis
2. signal_interpretation
3. anomaly_check
4. explain_trade
5. daily_briefing
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

load_dotenv('/opt/trading/config/.env')

TASK_TYPES = [
    'sentiment_analysis',
    'signal_interpretation',
    'anomaly_check',
    'explain_trade',
    'daily_briefing',
]


# ── Pydantic models for structured output ──

class SentimentResult(BaseModel):
    result: str = Field(description='Bullish|Neutral|Bearish')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class SignalInterpretationResult(BaseModel):
    consistency: str = Field(description='CONSISTENT|DIVERGENT|UNCLEAR')
    recommendation: str = Field(description='PROCEED|CAUTION|ABORT')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class AnomalyResult(BaseModel):
    anomaly_detected: bool = Field(description='true if anomaly found')
    severity: str = Field(description='LOW|MEDIUM|HIGH|CRITICAL')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class ExplainTradeResult(BaseModel):
    result: str = Field(description='explanation text')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of strings')


class DailyBriefingResult(BaseModel):
    result: str = Field(description='200 word market briefing')
    confidence: int = Field(description='overall market confidence 0-100')
    reasoning: str = Field(description='key catalysts')
    flags: List[str] = Field(default_factory=list, description='critical alerts for the day')


TASK_MODELS = {
    'sentiment_analysis': SentimentResult,
    'signal_interpretation': SignalInterpretationResult,
    'anomaly_check': AnomalyResult,
    'explain_trade': ExplainTradeResult,
    'daily_briefing': DailyBriefingResult,
}

_TEMPLATE = """You are a quantitative analyst for a multi-asset trading system.
Task: {task_type} | Asset(s): {asset}

Portfolio context:
{portfolio}

Data:
{data}

{format_instructions}

Rules:
- Be precise and data-driven.
- Maximum 3 sentence reasoning.
- Flag any critical risks.
- If data is insufficient, return confidence=0 and flag 'insufficient_data'."""


class ClaudeBridge:
    """LangChain bridge multi-provider (OpenAI default, Anthropic fallback)."""

    def __init__(self):
        self.llm = None
        self._configured = False
        self._provider = 'none'

        # Prioridad: OpenAI (más barato) > Anthropic
        openai_key = os.getenv('OPENAI_API_KEY', '')
        anthropic_key = os.getenv('ANTHROPIC_API_KEY', '')

        if openai_key and openai_key != 'CHANGE_ME':
            from langchain_openai import ChatOpenAI
            model = os.getenv('LLM_MODEL', 'gpt-4o-mini')
            self.llm = ChatOpenAI(
                model=model,
                api_key=openai_key,
                temperature=0.1,
                max_tokens=1000,
                timeout=30.0,
            )
            self._configured = True
            self._provider = f'openai/{model}'
            logger.info(f'LLMBridge: Using {self._provider}')

        elif anthropic_key and anthropic_key != 'sk-ant-CHANGE_ME':
            from langchain_anthropic import ChatAnthropic
            model = os.getenv('LLM_MODEL', 'claude-opus-4-5')
            self.llm = ChatAnthropic(
                model=model,
                anthropic_api_key=anthropic_key,
                temperature=0.1,
                max_tokens=1000,
                timeout=30.0,
            )
            self._configured = True
            self._provider = f'anthropic/{model}'
            logger.info(f'LLMBridge: Using {self._provider}')

        else:
            logger.warning('LLMBridge: No API key configured — running in dry-run mode')

        self._parsers = {
            k: JsonOutputParser(pydantic_object=v)
            for k, v in TASK_MODELS.items()
        }

    def call(
        self,
        task_type: str,
        asset: str,
        data: Dict[str, Any],
        portfolio_context: Dict = None,
    ) -> Dict:
        """Invoke Claude for a specific analysis task. Returns structured JSON."""
        if task_type not in TASK_TYPES:
            raise ValueError(f'Unknown task_type: {task_type}')

        if not self._configured:
            logger.info(f'LLMBridge dry-run: {task_type} for {asset}')
            return self._neutral_result(f'dry-run: no API key configured')

        parser = self._parsers[task_type]
        format_instructions = parser.get_format_instructions()

        prompt = PromptTemplate(
            input_variables=['task_type', 'asset', 'data', 'portfolio', 'format_instructions'],
            template=_TEMPLATE,
        )

        chain = prompt | self.llm | parser

        t0 = time.time()
        try:
            result = chain.invoke({
                'task_type': task_type,
                'asset': asset,
                'data': json.dumps(data, default=str),
                'portfolio': json.dumps(portfolio_context or {}, default=str),
                'format_instructions': format_instructions,
            })
            latency = int((time.time() - t0) * 1000)
            result['_latency_ms'] = latency
            logger.info(
                f'LLM [{self._provider}] {task_type} for {asset}: '
                f'{result.get("confidence", "?")}% conf, {latency}ms'
            )
            return result

        except Exception as e:
            logger.error(f'LLMBridge error: {e}')
            return self._neutral_result(str(e))

    @staticmethod
    def _neutral_result(reason: str) -> Dict:
        """Fallback neutral — nunca detener el sistema por fallo de LLM."""
        return {
            'result': 'NEUTRAL',
            'confidence': 0,
            'reasoning': f'LLM unavailable: {reason[:100]}',
            'flags': ['llm_unavailable'],
            '_latency_ms': -1,
        }
