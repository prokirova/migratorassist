"""Диалог из трёх реплик и дамп build_messages() для третьей."""
import logging
logging.basicConfig(level=logging.INFO)
import uuid
import prompts
from orchestrator import Orchestrator

original = prompts.build_messages
captured = {}

def spy(role, question, chunks, history):
    msgs = original(role, question, chunks, history)
    captured["messages"] = msgs
    captured["role"] = role
    captured["question"] = question
    return msgs

prompts.build_messages = spy

o = Orchestrator()
sid = f"demo:{uuid.uuid4()}"

questions = [
    "Как в Pydantic v2 заменить parse_obj?",
    "А для parse_raw что используется?",
    "А какие из этих двух методов вообще устарели?",
]

for q in questions:
    print(f"— {q}")
    print(o.handle(sid, q), "\n")

print("--- Дамп build_messages() для третьей реплики ---")
for i, m in enumerate(captured["messages"], 1):
    print(f" {i}. [{m['role']}] {m['content'][:70]}")

o.close()