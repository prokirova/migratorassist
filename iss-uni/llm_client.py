"""
llm_client.py — доступ к языковой модели за общим интерфейсом.

ПРАКТИКА 4. Что делает студент:
  1. GigaChatClient.generate() — вызов Сбер GigaChat через официальный SDK
  2. OllamaClient.generate()   — вызов локальной модели через HTTP API Ollama
  3. count_tokens()            — оценка длины промпта до отправки

Готово и трогать не нужно: build_client() и выбор бэкенда по LLM_BACKEND.

Критерии приёмки:
  - смена LLM_BACKEND с gigachat на ollama не требует правки orchestrator.py
  - длина промпта считается до отправки и логируется
  - оба клиента принимают один и тот же список messages и возвращают строку

НЕ МЕНЯТЬ: сигнатуру generate(messages, temperature) — она объявлена в contracts.py
и на неё опирается оркестратор.

Зачем абстракция. Учебные квоты кончаются, сеть в аудитории падает, а занятие
должно продолжаться. Ollama — фолбэк, который работает офлайн. Заодно это
материал для сравнения авторегрессионной модели и reasoning-модели из Л4:
у DeepSeek-R1 в ответе виден блок рассуждений, у GigaChat — нет.

Третий бэкенд — fake_llm.FakeClient, офлайн-заглушка без сети и ключей. Она
нужна для отладки, когда недоступны оба клиента, и ваши реализации не заменяет:
работа, сданная на LLM_BACKEND=fake, не принимается.
"""

import math
import re

import requests

import config
from contracts import LLMClient

OLLAMA_TIMEOUT = 600


class OllamaClient:
    """Клиент локального инференса через Ollama."""

    def __init__(self):
        self.model = config.OLLAMA_MODEL
        self.host = config.OLLAMA_HOST.rstrip("/")

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": 1024, "num_ctx": 4096},
        }
        try:
            r = requests.post(f"{self.host}/api/chat", json=payload,
                              timeout=OLLAMA_TIMEOUT)
            r.raise_for_status()
            m = r.json()["message"]
            text = r.json()["message"]["content"]
        except requests.Timeout:
            return "Ошибка: Ollama не ответила вовремя."
        except requests.ConnectionError:
            return "Ошибка: Ollama недоступна, проверьте, что сервис запущен."
        except requests.HTTPError as e:
            return f"Ошибка Ollama: HTTP {e.response.status_code}."
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return "Ошибка: некорректный ответ Ollama."

        # Рассуждения reasoning-модели пользователю не показываем
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return text or "Ошибка: Ollama вернула пустой ответ."

    def count_tokens(self, text: str) -> int:
        return max(0, math.ceil(len(text) / 3))


class GigaChatClient:
    """Клиент Сбер GigaChat API."""

    def __init__(self):
        self.model = config.GIGACHAT_MODEL
        # TODO (П4): создать клиент
        # from gigachat import GigaChat
        # self._client = GigaChat(credentials=config.GIGACHAT_CREDENTIALS,
        #                         model=self.model,
        #                         verify_ssl_certs=config.GIGACHAT_VERIFY_SSL)

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        """Отправить диалог в GigaChat и вернуть текст ответа.

        SDK принимает структуру вида {"messages": [...], "temperature": ...}.
        Ответ лежит в response.choices[0].message.content.
        Не забудьте обработать сетевую ошибку: занятие не должно падать трассировкой.
        """
        raise NotImplementedError("П4: реализуйте вызов GigaChat")

    def count_tokens(self, text: str) -> int:
        """Оценка длины в токенах.

        У GigaChat есть метод tokens_count. Если он недоступен, дайте оценку:
        для русского текста примерно один токен на 3 символа. Точность здесь
        не главное — важно видеть порядок величины и связать его со стоимостью.
        """
        raise NotImplementedError("П4: реализуйте подсчёт токенов")



def build_client() -> LLMClient:
    """Выбрать бэкенд по конфигурации. Готово, менять не нужно."""
    if config.LLM_BACKEND == "ollama":
        return OllamaClient()
    if config.LLM_BACKEND == "gigachat":
        return GigaChatClient()
    if config.LLM_BACKEND == "fake":
        # Импорт внутри ветки: без него fake_llm тянулся бы при любом бэкенде
        from fake_llm import FakeClient

        return FakeClient()
    raise ValueError(
        f"Неизвестный LLM_BACKEND: {config.LLM_BACKEND!r}. "
        f"Допустимо: gigachat | ollama | fake"
    )
