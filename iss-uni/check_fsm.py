import logging
logging.basicConfig(level=logging.INFO)

from orchestrator import Orchestrator

o = Orchestrator()
phrases = [
    "Что сломается при обновлении FastAPI?",
    "А при апгрейде Pydantic?",
    "Что сломается при переходе на 0.115?",
    "Как заменить validator в Pydantic?",
    "Какие методы XML-RPC PyPI уже удалены?",
    "Как заменить validator в Pydantic?",
    "asdf qwerty",
]

for p in phrases:
    intent = o.detect_intent(p)
    role = o.route("test", intent)
    print(f"{p[:40]:<42} интент {intent:<14} роль {role}")
o.close()