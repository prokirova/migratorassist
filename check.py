import subprocess
import sys
import config
import memory

# 3.1 схема
memory.create_schema()
assert config.DB_PATH.exists(), "Файл БД не создан"
print(f"БД создана: {config.DB_PATH}")
memory.create_schema()
print("Повторный вызов create_schema не упал: ок")
conn = memory.connect()
try:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchall()
finally:
    conn.close()
assert tables, "Таблица messages не создана"
print("Таблица messages существует: ок")

# 3.2 save / clear
memory.clear("test")
memory.save("test", "user", "реплика 1")
memory.save("test", "assistant", "ответ 1")
conn = memory.connect()
try:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
        ("test",),
    ).fetchall()
finally:
    conn.close()
assert len(rows) == 2, f"Ожидалось 2 реплики, получено {len(rows)}"
assert rows[0] == ("user", "реплика 1"), rows[0]
assert rows[1] == ("assistant", "ответ 1"), rows[1]
print("save: реплики записаны в правильном порядке: ок")
memory.clear("test")
conn = memory.connect()
try:
    count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?", ("test",)
    ).fetchone()[0]
finally:
    conn.close()
assert count == 0, "clear не удалил реплики"
print("clear: реплики сессии удалены: ок")

# 3.3 окно
memory.clear("t1")
for i in range(1, 11):
    memory.save("t1", "user" if i % 2 else "assistant", f"сообщение {i}")
w = memory.window("t1", 4)
print([m.content for m in w])
assert [m.content for m in w] == [
    "сообщение 7", "сообщение 8", "сообщение 9", "сообщение 10"
], "Окно вернуло не те сообщения или не в том порядке"
print("окно: 4 последних в хронологическом порядке: ок")

# изоляция сессий
memory.clear("s1"); memory.clear("s2")
memory.save("s1", "user", "секрет первой сессии")
memory.save("s2", "user", "реплика второй сессии")
assert [m.content for m in memory.window("s1", 10)] == ["секрет первой сессии"]
assert [m.content for m in memory.window("s2", 10)] == ["реплика второй сессии"]
memory.clear("s1")
assert memory.window("s1", 10) == []
assert len(memory.window("s2", 10)) == 1, "clear s1 затронул s2"
print("изоляция сессий: ок")
memory.clear("s2")

# 3.4 перезапуск процесса
subprocess.run([sys.executable, "-c", """
import memory
memory.create_schema()
memory.clear("t2")
for i in range(1, 6):
    memory.save("t2", "user", f"реплика {i}")
print("записано 5 реплик")
"""], check=True)
subprocess.run([sys.executable, "-c", """
import memory
w = memory.window("t2", 10)
print([m.content for m in w])
assert len(w) == 5, "история не пережила перезапуск"
assert [m.content for m in w] == [f"реплика {i}" for i in range(1, 6)]
print("перезапуск: история на месте: ок")
"""], check=True)
memory.clear("t1"); memory.clear("t2")