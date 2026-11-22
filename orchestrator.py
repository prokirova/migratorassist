"""
orchestrator.py — ядро системы: конечный автомат, переключающий роли агентов.

ПРАКТИКА 3. Что делает студент:
  1. описать роли в ROLES — минимум две, с разными зонами ответственности
  2. заполнить INTENT_TO_ROLE и TRANSITIONS — граф переходов автомата
  3. реализовать detect_intent() — определение интента пользователя

Готово и трогать не нужно: route(), handle(), подключение MCP и LLM.

Критерии приёмки:
  - ролей не меньше двух, у каждой описана своя зона ответственности
  - граф переходов задан структурой данных, а не цепочкой if по всему файлу
  - смена интента в диалоге переключает роль, это видно в логе
  - неизвестный интент не роняет процесс, а уходит в состояние по умолчанию
  - контекст при переходе не теряется: вторая роль видит найденное первой
  - вызов инструмента идёт через MCP-клиент, а не прямым импортом функции поиска

НЕ МЕНЯТЬ: сигнатуру handle(session_id, text) -> str. Это единственная точка
входа в систему, и её вызывают оба канала (app.py, vk_bot.py) и test_suite.py.

Порядок сдачи. На П3 сквозного ответа ещё не будет: build_messages() и клиент LLM
пишутся на П4. Проверяйте автомат отдельно — вызовом detect_intent() и route()
на наборе фраз. Сквозной ответ появится на П4, память подключится на П5.
"""

import logging

import guardrails
import memory
import prompts
from contracts import Chunk
from llm_client import build_client
from mcp_client import MCPTools
import re

log = logging.getLogger(__name__)


VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+)*\b")
UPGRADE_WORDS = ("обнов", "апгрейд", "перейти", "переход", "мигр", "upgrade")
SOURCE_WORDS = ("xml-rpc", "xmlrpc", "pypi")
HOWTO_WORDS = ("заменить", "замена", "вместо", "переписать", "миграц", "мигрир", "pydantic", "v1")
BREAKING_WORDS = ("breaking", "сломает", "сломатс", "перестан", "удал", "срочно", "несовместим")
BLOCKED_REPLY = "Запрос отклонён слоем безопасности. Переформулируйте вопрос по существу темы."


class Orchestrator:
    """Оркестратор ролей на конечном автомате."""

    # --- Роли. Одна заполнена как образец, вторую добавляете вы (П3). ---
    ROLES: dict[str, dict] = {
        "analyst": {
            "description": "находит пункт release notes, migration guide или XML-RPC "
                           "reference и ссылается на него; ищет по всему индексу, "
                           "потому что вопрос может касаться любого из трёх документов; "
                           "версию не выясняет",
            "temperature": 0.2,
            "filters": {},
        },
        "breaking": {
            "description": "отвечает только по ломающим изменениям (удалено, "
                           "несовместимо): ему нужно знать, что чинить срочно, "
                           "а не как переписывать; ищет только в рубрике breaking",
            "temperature": 0.1,
            "filters": {"category": "breaking"},
        },
        "migration": {
            "description": "отвечает, как переписать код при переходе (Pydantic v1 -> v2): "
                           "ищет только в migration guide, потому что ему нужен "
                           "рецепт замены, а не список изменений",
            "temperature": 0.2,
            "filters": {"category": "migration"},
        },
        "clarifier": {
            "description": "когда про обновление спросили без целевой версии, "
                           "задаёт один встречный вопрос вместо ответа; "
                           "найденное по запросу не применяет",
            "temperature": 0.3,
            "filters": {},
        },
    }




    INITIAL_ROLE = "analyst"
    FALLBACK_ROLE = "analyst"

    # --- Граф переходов: из какой роли в какие можно перейти (П3). ---
    TRANSITIONS: dict[str, set[str]] = {
        "analyst": {"analyst", "breaking", "migration", "clarifier"},
        "breaking": {"analyst", "breaking", "migration", "clarifier"},
        "migration": {"analyst", "breaking", "migration", "clarifier"},
        "clarifier": {"analyst", "breaking", "migration"},  # два вопроса подряд нельзя
    }

    # --- Какой интент какой ролью обслуживается (П3). ---
    INTENT_TO_ROLE: dict[str, str] = {
        "question": "analyst",
        "urgent": "breaking",
        "howto": "migration",
        "vague_upgrade": "clarifier",
    }

    def __init__(self):
        self.tools = MCPTools()
        self.llm = build_client()
        memory.create_schema()
        self._state: dict[str, str] = {}      # session_id -> текущая роль
        self._context: dict[str, list[Chunk]] = {}  # session_id -> что нашла прошлая роль
        self.usage: list[dict] = []           # расход токенов по вызовам, на нём считается TCO (П8)

    # --- Ваша часть (П3) ---

    def detect_intent(self, text: str) -> str:
        """Определить интент реплики. Возвращает ключ из INTENT_TO_ROLE.

        Достаточно правил: ключевые слова, длина, наличие вопросительного знака.
        LLM для маршрутизации не нужна — она недетерминирована и стоит денег,
        а маршрут должен быть предсказуемым (Л3: FSM как детерминированная маршрутизация).

        На нераспознанной фразе верните "question" — пусть система отвечает,
        а не отказывается.
        """
        low = text.lower()
        if any(w in low for w in SOURCE_WORDS):
            return "question"
        if any(w in low for w in UPGRADE_WORDS) and not VERSION_RE.search(low):
            return "vague_upgrade"
        if any(w in low for w in BREAKING_WORDS):
            return "urgent"
        if any(w in low for w in HOWTO_WORDS):
            return "howto"
        return "question"

    # --- Готовая механика: менять не нужно ---

    def route(self, session_id: str, intent: str) -> str:
        """Перевести автомат в новое состояние и вернуть активную роль."""
        current = self._state.get(session_id, self.INITIAL_ROLE)
        target = self.INTENT_TO_ROLE.get(intent, self.FALLBACK_ROLE)

        allowed = self.TRANSITIONS.get(current, {self.FALLBACK_ROLE})
        rolled_back = target not in allowed
        if rolled_back:
            log.warning("Переход %s -> %s запрещён, откат в %s",
                        current, target, self.FALLBACK_ROLE)
            target = self.FALLBACK_ROLE

        if target != current:
            # Про откат сказано прямо: иначе строка «verifier -> analyst (интент verify)»
            # читается как «интент verify обслуживается ролью analyst», то есть наоборот.
            log.info("Сессия %s: роль %s -> %s (интент %s%s)",
                     session_id, current, target, intent, ", откат" if rolled_back else "")

        self._state[session_id] = target
        return target

    def handle(self, session_id: str, text: str) -> str:
        """Единственная точка входа. Оба канала и тесты идут сюда.

        Конвейер: guardrail -> память -> интент -> роль -> поиск через MCP ->
        сборка промпта -> LLM -> память -> ответ.
        """
        verdict = guardrails.check(text)
        if not verdict.allowed:
            guardrails.log_attempt(session_id, text, verdict)
            log.warning("Сессия %s: запрос заблокирован (%s)", session_id, verdict.reason)
            return BLOCKED_REPLY

        previous_role = self._state.get(session_id, self.INITIAL_ROLE)
        intent = self.detect_intent(text)
        role = self.route(session_id, intent)
        role_config = self.ROLES[role]

        filters = role_config.get("filters") or {}
        if filters:
            chunks = self.tools.search_filtered(text, filters)
        else:
            chunks = self.tools.search(text)

        # Контекст переезжает между ролями: при переключении новая роль видит
        # и свои фрагменты, и то, что нашла предыдущая, — иначе разговор рвётся.
        # Признак переноса — смена роли, а не пустая выдача: поиск по реплике
        # «а в моём случае?» возвращает не ноль фрагментов, а пять нерелевантных.
        if role != previous_role:
            known = {(c.source, c.page, c.text[:80]) for c in chunks}
            chunks = chunks + [c for c in self._context.get(session_id, [])
                               if (c.source, c.page, c.text[:80]) not in known]
        self._context[session_id] = chunks

        history = memory.window(session_id)

        # Реплика пользователя сохраняется после чтения окна, а не до него.
        # Иначе текущий вопрос уходил бы в модель дважды — в истории и в блоке
        # с фрагментами, — а полезная глубина окна была бы N−1, а не N.
        memory.save(session_id, "user", text)

        messages = prompts.build_messages(role, text, chunks, history)

        # Считается одним вызовом по склеенному тексту, а не по сообщению на вызов:
        # у облачного клиента count_tokens() — обращение к API, и поштучный подсчёт
        # добавлял бы к каждому вопросу столько сетевых запросов, сколько сообщений.
        prompt_size = self.llm.count_tokens("\n".join(m["content"] for m in messages))
        log.info("Сессия %s: роль %s, чанков %d, промпт ~%d токенов",
                 session_id, role, len(chunks), prompt_size)

        answer = self.llm.generate(messages, temperature=role_config["temperature"])

        # Вход и выход считаются раздельно: они тарифицируются по разным ценам (П8)
        self.usage.append({
            "session_id": session_id,
            "role": role,
            "prompt_tokens": prompt_size,
            "completion_tokens": self.llm.count_tokens(answer),
        })

        memory.save(session_id, "assistant", answer)
        return answer

    def reset(self, session_id: str) -> None:
        """Сбросить сессию: состояние автомата, контекст и историю."""
        self._state.pop(session_id, None)
        self._context.pop(session_id, None)
        memory.clear(session_id)

    def close(self) -> None:
        self.tools.close()
