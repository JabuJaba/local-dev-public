# -*- coding: utf-8 -*-
"""
Benchmark real de qualidade e velocidade para os modelos locais.
Testa corretude executando o código gerado contra casos de teste.

Uso:
  python bench.py                  # ambos os modelos
  python bench.py --model ollama   # so qwen3coder-local
  python bench.py --model llama    # so Coder-Next
  python bench.py --category algo  # so categoria especifica
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import traceback
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuracao dos modelos
# ---------------------------------------------------------------------------

MODELS = {
    "ollama": {
        "url": "http://localhost:11434/v1/chat/completions",
        "key": "local-only",
        "model": "qwen3coder-local",
        "label": "qwen3coder-local (Ollama A3B MoE)",
    },
    "llama": {
        "url": "http://localhost:8081/v1/chat/completions",
        "key": "local-only",
        "model": "qwen3-coder-next",
        "label": "Qwen3-Coder-Next (llama.cpp 80B MoE)",
    },
    "gemma4": {
        # Uses native /api/chat endpoint (not OpenAI-compat) because think=false
        # must be a top-level field — the /v1 endpoint ignores it inside options.
        "url": "http://localhost:11434/api/chat",
        "native": True,          # signals call_model() to use Ollama-native format
        "key": "local-only",
        "model": "gemma4:26b",
        "label": "Gemma 4 26B (Ollama, Google) [no-think]",
        # think=False: disables internal reasoning. Without it, model spends 800+ tokens
        # on thinking and often ignores naming instructions (NameError failures).
        # Google-recommended params: temp=1.0, top_p=0.95, top_k=64.
        "think": False,
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "system_prompt": (
            "You are a coding assistant. Follow ALL naming instructions exactly — "
            "use the exact function, class, and variable names specified in the prompt. "
            "Return ONLY the requested code with no explanation, no preamble, no markdown prose."
        ),
    },
    "qwen36": {
        # Qwen3.6 35B-A3B MoE — general-purpose successor to qwen3.5:35b-a3b.
        # Native endpoint required so think=False is honoured at top level.
        "url": "http://localhost:11434/api/chat",
        "native": True,
        "key": "local-only",
        "model": "qwen3.6:35b-a3b-q4_k_m",
        "label": "Qwen3.6 35B A3B MoE (Ollama) [no-think]",
        "think": False,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "system_prompt": (
            "You are a coding assistant. Follow ALL naming instructions exactly — "
            "use the exact function, class, and variable names specified in the prompt. "
            "Return ONLY the requested code with no explanation, no preamble, no markdown prose."
        ),
    },
}

# ---------------------------------------------------------------------------
# Chamada ao modelo
# ---------------------------------------------------------------------------

def call_model(model_key: str, prompt: str, max_tokens: int = 400, timeout: int = 120) -> dict:
    cfg = MODELS[model_key]

    # Build message list — prepend system prompt if model requires it
    messages = []
    if cfg.get("system_prompt"):
        messages.append({"role": "system", "content": cfg["system_prompt"]})
    messages.append({"role": "user", "content": prompt})

    t0 = time.time()
    try:
        if cfg.get("native"):
            # Ollama native /api/chat — supports think=False as top-level field
            payload = {
                "model": cfg["model"],
                "messages": messages,
                "stream": False,
                "think": cfg.get("think", True),
                "options": {
                    "temperature": cfg.get("temperature", 0.2),
                    "top_p": cfg.get("top_p", 0.8),
                    "top_k": cfg.get("top_k", 20),
                    "num_predict": max_tokens,
                },
            }
            req = urllib.request.Request(
                cfg["url"],
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            elapsed = time.time() - t0
            content = r["message"]["content"]
            eval_count = r.get("eval_count", 0)
            tps = eval_count / elapsed if elapsed > 0 else 0
            return {
                "ok": True,
                "content": content,
                "elapsed": elapsed,
                "prompt_tokens": r.get("prompt_eval_count", 0),
                "completion_tokens": eval_count,
                "tps": tps,
            }
        else:
            # OpenAI-compat /v1/chat/completions (Ollama + llama.cpp)
            payload = {
                "model": cfg["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": False,
                "temperature": cfg.get("temperature", 0.2),
            }
            req = urllib.request.Request(
                cfg["url"],
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['key']}"},
            )
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            elapsed = time.time() - t0
            content = r["choices"][0]["message"]["content"]
            usage = r.get("usage", {})
            return {
                "ok": True,
                "content": content,
                "elapsed": elapsed,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "tps": usage.get("completion_tokens", 0) / elapsed if elapsed > 0 else 0,
            }
    except Exception as e:
        return {"ok": False, "content": "", "elapsed": time.time() - t0, "error": str(e), "tps": 0}


def extract_code(text: str, lang_hint: str = "python") -> str:
    """Extract code block from model response."""
    # Try ```python ... ``` or ```sql ... ``` etc.
    m = re.search(rf"```(?:{lang_hint}|{lang_hint.upper()})?\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try any ``` block
    m = re.search(r"```\w*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try ``` ... ```
    m = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try to find code-like content (starts with def/class/import)
    lines = text.split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        if re.match(r"^(def |class |import |from |#|async def |\s+(def |class |return |if |for |while ))", line):
            in_code = True
        if in_code:
            code_lines.append(line)
    return "\n".join(code_lines).strip() if code_lines else text.strip()


def run_code(code: str, test_harness: str, timeout: int = 10) -> tuple[bool, str]:
    """Execute code + test harness, return (passed, output)."""
    full_code = code + "\n\n" + test_harness
    try:
        result = subprocess.run(
            [sys.executable, "-c", full_code],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, (result.stderr + result.stdout).strip()[-500:]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Suite de tarefas
# ---------------------------------------------------------------------------

@dataclass
class Task:
    id: str
    category: str
    difficulty: str          # easy | medium | hard | adversarial
    description: str
    prompt: str
    test_harness: str        # Python code that asserts correctness
    max_tokens: int = 350
    timeout: int = 90
    notes: str = ""          # what typically fails here


TASKS: list[Task] = [

    # =========================================================================
    # CATEGORIA: trivial — valida que o modelo funciona
    # =========================================================================
    Task(
        id="trivial_01",
        category="trivial",
        difficulty="easy",
        description="Fibonacci iterativo",
        prompt="Write a Python function `fibonacci(n: int) -> int` that returns the nth Fibonacci number (0-indexed, fib(0)=0, fib(1)=1). Iterative solution only. Return ONLY the function.",
        test_harness=textwrap.dedent("""
            assert fibonacci(0) == 0
            assert fibonacci(1) == 1
            assert fibonacci(10) == 55
            assert fibonacci(20) == 6765
            print("PASS")
        """),
        max_tokens=120,
    ),
    Task(
        id="trivial_02",
        category="trivial",
        difficulty="easy",
        description="FizzBuzz",
        prompt="Write a Python function `fizzbuzz(n: int) -> list[str]` that returns a list of strings 1..n with FizzBuzz rules. Return ONLY the function.",
        test_harness=textwrap.dedent("""
            r = fizzbuzz(15)
            assert r[2] == "Fizz"
            assert r[4] == "Buzz"
            assert r[14] == "FizzBuzz"
            assert r[0] == "1"
            print("PASS")
        """),
        max_tokens=120,
    ),

    # =========================================================================
    # CATEGORIA: algoritmos — corretude em casos limite
    # =========================================================================
    Task(
        id="algo_01",
        category="algo",
        difficulty="medium",
        description="Binary search com casos limite",
        prompt="Write a Python function `binary_search(arr: list, target: int) -> int` that returns the index of target in sorted arr, or -1 if not found. Handle empty list, duplicates, first/last element. Return ONLY the function.",
        test_harness=textwrap.dedent("""
            assert binary_search([], 5) == -1
            assert binary_search([1], 1) == 0
            assert binary_search([1], 2) == -1
            assert binary_search([1,3,5,7,9], 5) == 2
            assert binary_search([1,3,5,7,9], 1) == 0
            assert binary_search([1,3,5,7,9], 9) == 4
            assert binary_search([1,3,5,7,9], 4) == -1
            print("PASS")
        """),
        max_tokens=180,
        notes="Off-by-one errors very common",
    ),
    Task(
        id="algo_02",
        category="algo",
        difficulty="medium",
        description="LRU Cache sem biblioteca",
        prompt="Write a Python class `LRUCache` with `__init__(self, capacity: int)`, `get(self, key: int) -> int` (returns -1 if not found), and `put(self, key: int, value: int)`. Use only built-in Python (no functools). Return ONLY the class.",
        test_harness=textwrap.dedent("""
            c = LRUCache(2)
            c.put(1, 1)
            c.put(2, 2)
            assert c.get(1) == 1
            c.put(3, 3)            # evicts key 2
            assert c.get(2) == -1
            c.put(4, 4)            # evicts key 1
            assert c.get(1) == -1
            assert c.get(3) == 3
            assert c.get(4) == 4
            print("PASS")
        """),
        max_tokens=350,
        notes="Requires OrderedDict or doubly-linked list logic",
    ),
    Task(
        id="algo_03",
        category="algo",
        difficulty="hard",
        description="Merge intervals",
        prompt="Write a Python function `merge_intervals(intervals: list[list[int]]) -> list[list[int]]` that merges overlapping intervals. Input may be unsorted. Return ONLY the function.",
        test_harness=textwrap.dedent("""
            assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
            assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
            assert merge_intervals([]) == []
            assert merge_intervals([[1,4],[0,4]]) == [[0,4]]
            assert merge_intervals([[1,4],[2,3]]) == [[1,4]]
            print("PASS")
        """),
        max_tokens=200,
    ),
    Task(
        id="algo_04",
        category="algo",
        difficulty="hard",
        description="Longest common subsequence",
        prompt="Write a Python function `lcs(s1: str, s2: str) -> int` that returns the length of the longest common subsequence (not substring). Dynamic programming solution. Return ONLY the function.",
        test_harness=textwrap.dedent("""
            assert lcs("ABCBDAB", "BDCAB") == 4
            assert lcs("", "ABC") == 0
            assert lcs("ABC", "") == 0
            assert lcs("ABC", "ABC") == 3
            assert lcs("AGGTAB", "GXTXAYB") == 4
            print("PASS")
        """),
        max_tokens=220,
    ),

    # =========================================================================
    # CATEGORIA: bugs — encontrar e corrigir bugs sutis
    # =========================================================================
    Task(
        id="bug_01",
        category="bug",
        difficulty="medium",
        description="Bug: mutacao de argumento padrao",
        prompt=textwrap.dedent("""\
            This Python function has a classic bug. Fix it and return ONLY the corrected function:

            ```python
            def append_to(element, to=[]):
                to.append(element)
                return to
            ```
            The function should always create a new list when `to` is not provided.
        """),
        test_harness=textwrap.dedent("""
            assert append_to(1) == [1]
            assert append_to(2) == [2]
            assert append_to(3, [0]) == [0, 3]
            print("PASS")
        """),
        max_tokens=120,
        notes="Mutable default argument - classic Python gotcha",
    ),
    Task(
        id="bug_02",
        category="bug",
        difficulty="medium",
        description="Bug: divisao por zero silenciosa",
        prompt=textwrap.dedent("""\
            Fix the bugs in this function and return ONLY the corrected function:

            ```python
            def safe_divide(a, b):
                try:
                    result = a / b
                except:
                    result = 0
                return result
            ```
            Requirements: raise ValueError with message "division by zero" when b==0. Raise TypeError when inputs are not numbers.
        """),
        test_harness=textwrap.dedent("""
            assert safe_divide(10, 2) == 5.0
            assert safe_divide(7, 2) == 3.5
            try:
                safe_divide(1, 0)
                assert False, "should raise"
            except ValueError as e:
                assert "zero" in str(e).lower()
            try:
                safe_divide("a", 1)
                assert False, "should raise"
            except TypeError:
                pass
            print("PASS")
        """),
        max_tokens=180,
        notes="Bare except swallows everything - needs specific handling",
    ),
    Task(
        id="bug_03",
        category="bug",
        difficulty="hard",
        description="Bug: race condition em contador",
        prompt=textwrap.dedent("""\
            This counter has a thread-safety bug. Fix it using threading.Lock and return ONLY the corrected class:

            ```python
            import threading

            class Counter:
                def __init__(self):
                    self.value = 0

                def increment(self):
                    self.value += 1

                def get(self):
                    return self.value
            ```
        """),
        test_harness=textwrap.dedent("""
            import threading
            c = Counter()
            threads = [threading.Thread(target=lambda: [c.increment() for _ in range(1000)]) for _ in range(10)]
            for t in threads: t.start()
            for t in threads: t.join()
            assert c.get() == 10000, f"Expected 10000, got {c.get()}"
            print("PASS")
        """),
        max_tokens=200,
        notes="Threading.Lock - models sometimes use wrong lock scope",
    ),
    Task(
        id="bug_04",
        category="bug",
        difficulty="hard",
        description="Bug: SQL injection",
        prompt=textwrap.dedent("""\
            This function is vulnerable to SQL injection. Fix it using parameterized queries and return ONLY the corrected function:

            ```python
            import sqlite3

            def get_user(db_path: str, username: str) -> dict | None:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")
                row = cursor.fetchone()
                conn.close()
                if row:
                    return {"id": row[0], "username": row[1]}
                return None
            ```
        """),
        test_harness=textwrap.dedent("""
            import sqlite3, tempfile, os
            tmp = tempfile.mktemp(suffix='.db')
            conn = sqlite3.connect(tmp)
            conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
            conn.execute("INSERT INTO users VALUES (1, 'alice')")
            conn.commit()
            conn.close()

            r = get_user(tmp, 'alice')
            assert r == {"id": 1, "username": "alice"}, f"got {r}"

            # SQL injection attempt should return None, not crash
            r2 = get_user(tmp, "' OR '1'='1")
            assert r2 is None, f"SQL injection succeeded: {r2}"

            os.unlink(tmp)
            print("PASS")
        """),
        max_tokens=250,
        notes="Models often still use f-string even when asked to fix",
    ),

    # =========================================================================
    # CATEGORIA: refactoring — manter comportamento, melhorar estrutura
    # =========================================================================
    Task(
        id="refactor_01",
        category="refactor",
        difficulty="medium",
        description="Refactoring: duplicacao de codigo",
        prompt=textwrap.dedent("""\
            Refactor this code to remove duplication. Use a single function. Return ONLY the refactored code:

            ```python
            def process_csv(filepath):
                with open(filepath) as f:
                    lines = f.read().split('\\n')
                result = []
                for line in lines:
                    if line.strip():
                        parts = line.split(',')
                        result.append({'name': parts[0].strip(), 'value': int(parts[1].strip())})
                return result

            def process_tsv(filepath):
                with open(filepath) as f:
                    lines = f.read().split('\\n')
                result = []
                for line in lines:
                    if line.strip():
                        parts = line.split('\\t')
                        result.append({'name': parts[0].strip(), 'value': int(parts[1].strip())})
                return result
            ```
        """),
        test_harness=textwrap.dedent("""
            import tempfile, os

            # CSV test
            tmp_csv = tempfile.mktemp(suffix='.csv')
            with open(tmp_csv, 'w') as f:
                f.write("alice, 10\\nbob, 20\\n")
            r = process_csv(tmp_csv)
            assert r == [{'name': 'alice', 'value': 10}, {'name': 'bob', 'value': 20}]

            # TSV test
            tmp_tsv = tempfile.mktemp(suffix='.tsv')
            with open(tmp_tsv, 'w') as f:
                f.write("charlie\\t30\\ndelta\\t40\\n")
            r = process_tsv(tmp_tsv)
            assert r == [{'name': 'charlie', 'value': 30}, {'name': 'delta', 'value': 40}]

            os.unlink(tmp_csv)
            os.unlink(tmp_tsv)
            print("PASS")
        """),
        max_tokens=300,
        notes="Must keep both public functions working, just share implementation",
    ),

    # =========================================================================
    # CATEGORIA: SQL — window functions, CTEs, joins complexos
    # =========================================================================
    Task(
        id="sql_01",
        category="sql",
        difficulty="medium",
        description="SQL: rank por grupo com window function",
        prompt=textwrap.dedent("""\
            Write a SQLite query that returns the top-2 highest-paid employees per department.
            Table: employees(id, name, department, salary)
            Return columns: department, name, salary, rank_in_dept
            Use window functions (ROW_NUMBER or RANK). Return ONLY the SQL query (no explanation).
        """),
        test_harness=textwrap.dedent("""
            import sqlite3, re

            # Extract SQL from response
            sql = RESPONSE.strip()
            if sql.startswith('```'):
                sql = re.sub(r'^```\\w*\\n', '', sql)
                sql = re.sub(r'\\n```$', '', sql)

            conn = sqlite3.connect(':memory:')
            conn.execute('''CREATE TABLE employees
                (id INTEGER, name TEXT, department TEXT, salary REAL)''')
            data = [
                (1,'Alice','Eng',90),(2,'Bob','Eng',85),(3,'Carol','Eng',70),
                (4,'Dave','HR',60),(5,'Eve','HR',55),(6,'Frank','HR',50),
                (7,'Grace','Mkt',80),(8,'Hank','Mkt',75),
            ]
            conn.executemany('INSERT INTO employees VALUES (?,?,?,?)', data)
            conn.commit()
            rows = conn.execute(sql).fetchall()
            # Should have 6 rows (2 per dept x 3 depts)
            assert len(rows) == 6, f"Expected 6 rows, got {len(rows)}: {rows}"
            # Each dept appears exactly twice
            from collections import Counter
            depts = Counter(r[0] for r in rows)
            assert all(v == 2 for v in depts.values()), f"Dept counts: {dict(depts)}"
            print("PASS")
        """),
        max_tokens=200,
        notes="Window functions often have incorrect PARTITION BY",
    ),
    Task(
        id="sql_02",
        category="sql",
        difficulty="hard",
        description="SQL: CTE recursiva para hierarquia",
        prompt=textwrap.dedent("""\
            Write a SQLite recursive CTE query that finds all employees under a given manager (including indirect reports).
            Table: employees(id, name, manager_id)  -- manager_id is NULL for top level
            Given manager id = 1, return all employees in their subtree (excluding the manager themselves).
            Columns: id, name, level (1=direct report, 2=report of report, etc.)
            Return ONLY the SQL query.
        """),
        test_harness=textwrap.dedent("""
            import sqlite3, re

            sql = RESPONSE.strip()
            if sql.startswith('```'):
                sql = re.sub(r'^```\\w*\\n', '', sql)
                sql = re.sub(r'\\n```$', '', sql)

            conn = sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE employees (id INTEGER, name TEXT, manager_id INTEGER)')
            data = [
                (1,'CEO',None),(2,'VPEng',1),(3,'VPMkt',1),
                (4,'DevLead',2),(5,'Dev1',4),(6,'Dev2',4),
                (7,'MktLead',3),(8,'Mkt1',7),
            ]
            conn.executemany('INSERT INTO employees VALUES (?,?,?)', data)
            conn.commit()
            rows = conn.execute(sql).fetchall()
            ids = set(r[0] for r in rows)
            assert 1 not in ids, "Manager should not be in results"
            assert {2,3,4,5,6,7,8} == ids, f"Expected all subordinates, got {ids}"
            # Check levels
            row_map = {r[0]: r[2] for r in rows}
            assert row_map[2] == 1 and row_map[3] == 1, f"VPs should be level 1: {row_map}"
            assert row_map[4] == 2, f"DevLead should be level 2: {row_map}"
            assert row_map[5] == 3 and row_map[6] == 3, f"Devs should be level 3: {row_map}"
            print("PASS")
        """),
        max_tokens=300,
        notes="Recursive CTEs: models often get anchor/recursive part wrong",
    ),

    # =========================================================================
    # CATEGORIA: data structures — implementar sem biblioteca
    # =========================================================================
    Task(
        id="ds_01",
        category="data_structures",
        difficulty="hard",
        description="Min Heap sem heapq",

        prompt=textwrap.dedent("""\
            Write a Python class `MinHeap` with:
            - `push(val)`: insert value
            - `pop() -> int`: remove and return minimum (raise IndexError if empty)
            - `peek() -> int`: return minimum without removing
            - `__len__() -> int`
            Do NOT use heapq or sorted(). Implement with a list and sift operations. Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            h = MinHeap()
            for v in [5,3,8,1,9,2,7,4,6]:
                h.push(v)
            assert len(h) == 9
            assert h.peek() == 1
            result = [h.pop() for _ in range(9)]
            assert result == sorted([5,3,8,1,9,2,7,4,6]), f"got {result}"
            try:
                h.pop()
                assert False, "should raise IndexError"
            except IndexError:
                pass
            print("PASS")
        """),
        max_tokens=600,
        notes="Sift-up and sift-down bugs are common; needs 500+ tokens",
    ),
    Task(
        id="ds_02",
        category="data_structures",
        difficulty="hard",
        description="Trie (prefix tree)",
        prompt=textwrap.dedent("""\
            Write a Python class `Trie` with:
            - `insert(word: str)`
            - `search(word: str) -> bool` (exact match)
            - `starts_with(prefix: str) -> bool`
            Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            t = Trie()
            t.insert("apple")
            t.insert("app")
            assert t.search("apple") == True
            assert t.search("app") == True
            assert t.search("ap") == False
            assert t.search("apples") == False
            assert t.starts_with("app") == True
            assert t.starts_with("ap") == True
            assert t.starts_with("b") == False
            t.insert("banana")
            assert t.search("banana") == True
            assert t.starts_with("ban") == True
            print("PASS")
        """),
        max_tokens=350,
        notes="End-of-word marking frequently missed or wrong",
    ),

    # =========================================================================
    # CATEGORIA: adversarial — tarefas que modelos pequenos tipicamente falham
    # =========================================================================
    Task(
        id="adv_01",
        category="adversarial",
        difficulty="hard",
        description="Decorator com preservacao de metadados",
        prompt=textwrap.dedent("""\
            Write a Python decorator `retry(max_attempts: int, exceptions: tuple)` that:
            1. Retries the decorated function up to max_attempts times if it raises one of the given exceptions
            2. On final failure, re-raises the last exception
            3. Preserves __name__, __doc__, __wrapped__ using functools.wraps
            Return ONLY the decorator function.
        """),
        test_harness=textwrap.dedent("""
            import functools

            call_count = 0

            @retry(max_attempts=3, exceptions=(ValueError,))
            def flaky(succeed_on: int):
                global call_count
                call_count += 1
                if call_count < succeed_on:
                    raise ValueError("not yet")
                return "ok"

            call_count = 0
            assert flaky(2) == "ok"
            assert call_count == 2

            call_count = 0
            try:
                flaky(5)
                assert False
            except ValueError:
                assert call_count == 3

            # Metadata preserved
            assert flaky.__name__ == "flaky"
            assert hasattr(flaky, "__wrapped__")

            # Non-listed exception propagates immediately
            @retry(max_attempts=3, exceptions=(ValueError,))
            def raise_type_error():
                raise TypeError("other")

            try:
                raise_type_error()
                assert False
            except TypeError:
                pass

            print("PASS")
        """),
        max_tokens=350,
        notes="Often: wrong attempt count, missing functools.wraps, wrong exception handling",
    ),
    Task(
        id="adv_02",
        category="adversarial",
        difficulty="hard",
        description="Generator com send() e throw()",
        prompt=textwrap.dedent("""\
            Write a Python generator function `accumulator()` that:
            1. Yields the running total each time a number is sent to it
            2. When GeneratorExit is thrown, logs nothing (just stops)
            3. When ValueError is thrown, resets the total to 0 and yields 0

            Example:
              gen = accumulator()
              next(gen)        # prime it, yields 0
              gen.send(5)      # yields 5
              gen.send(3)      # yields 8
              gen.throw(ValueError)  # yields 0 (reset)
              gen.send(2)      # yields 2

            Return ONLY the generator function.
        """),
        test_harness=textwrap.dedent("""
            gen = accumulator()
            assert next(gen) == 0
            assert gen.send(5) == 5
            assert gen.send(3) == 8
            assert gen.throw(ValueError) == 0
            assert gen.send(2) == 2
            assert gen.send(10) == 12
            gen.close()
            print("PASS")
        """),
        max_tokens=250,
        notes="send() and throw() on generators - very hard for smaller models",
    ),
    Task(
        id="adv_03",
        category="adversarial",
        difficulty="hard",
        description="Metaclass para singleton",
        prompt=textwrap.dedent("""\
            Write a Python metaclass `SingletonMeta` that ensures only one instance of any class using it is created.
            Thread-safe using threading.Lock. Return ONLY the metaclass and do NOT include any example classes.
        """),
        test_harness=textwrap.dedent("""
            import threading

            class Database(metaclass=SingletonMeta):
                def __init__(self):
                    self.connection_count = 0

            a = Database()
            b = Database()
            assert a is b, "Should be same instance"

            a.connection_count = 42
            assert b.connection_count == 42

            # Thread safety
            instances = []
            def create():
                instances.append(Database())

            threads = [threading.Thread(target=create) for _ in range(20)]
            for t in threads: t.start()
            for t in threads: t.join()
            assert all(x is instances[0] for x in instances), "Thread safety failed"
            print("PASS")
        """),
        max_tokens=300,
        notes="Metaclass __call__ override - often confused with __new__",
    ),
    Task(
        id="adv_04",
        category="adversarial",
        difficulty="hard",
        description="Async rate limiter",
        prompt=textwrap.dedent("""\
            Write a Python async context manager class `RateLimiter` that allows at most `max_calls` calls per `period` seconds.
            Excess calls should wait (asyncio.sleep) until a slot is available.

            ```python
            async with RateLimiter(max_calls=3, period=1.0) as rl:
                await rl.acquire()  # proceeds immediately if under limit, waits otherwise
            ```

            Return ONLY the class. Use asyncio.
        """),
        test_harness=textwrap.dedent("""
            import asyncio, time

            async def test():
                rl = RateLimiter(max_calls=3, period=0.5)
                async with rl:
                    times = []
                    for _ in range(6):
                        await rl.acquire()
                        times.append(time.monotonic())

                    # First 3 should be near-instant
                    assert times[2] - times[0] < 0.3, f"First 3 too slow: {times[2]-times[0]:.2f}s"
                    # 4th call should be delayed by ~period
                    assert times[3] - times[0] >= 0.4, f"4th call not delayed: {times[3]-times[0]:.2f}s"
                    print("PASS")

            asyncio.run(test())
        """),
        max_tokens=400,
        notes="asyncio context managers and rate limiting - very hard",
        timeout=30,
    ),

    # =========================================================================
    # CATEGORIA: long context — entender codigo existente antes de modificar
    # =========================================================================
    Task(
        id="ctx_01",
        category="long_context",
        difficulty="medium",
        description="Adicionar metodo a classe existente",
        prompt=textwrap.dedent("""\
            Given this existing class, add a method `median() -> float` that returns the median of all values in the data store. Return ONLY the complete updated class:

            ```python
            class DataStore:
                def __init__(self):
                    self._data = []
                    self._sum = 0
                    self._count = 0

                def add(self, value: float):
                    self._data.append(value)
                    self._sum += value
                    self._count += 1

                def mean(self) -> float:
                    if self._count == 0:
                        raise ValueError("empty store")
                    return self._sum / self._count

                def variance(self) -> float:
                    if self._count < 2:
                        raise ValueError("need at least 2 values")
                    mean = self.mean()
                    return sum((x - mean) ** 2 for x in self._data) / (self._count - 1)
            ```
        """),
        test_harness=textwrap.dedent("""
            ds = DataStore()
            for v in [3, 1, 4, 1, 5, 9, 2, 6]:
                ds.add(v)

            assert ds.mean() == pytest_approx(3.875) if False else abs(ds.mean() - 3.875) < 0.001
            m = ds.median()
            assert abs(m - 3.5) < 0.001, f"Expected 3.5, got {m}"

            ds2 = DataStore()
            for v in [1, 2, 3, 4, 5]:
                ds2.add(v)
            assert ds2.median() == 3.0

            try:
                DataStore().median()
                assert False, "should raise on empty"
            except (ValueError, IndexError, ZeroDivisionError):
                pass

            print("PASS")
        """),
        max_tokens=400,
        notes="Model must preserve all existing methods while adding new one",
    ),

    # =========================================================================
    # RED TEAM: casos onde modelos tipicamente confiam demais em si mesmos
    # =========================================================================
    Task(
        id="redteam_01",
        category="redteam",
        difficulty="hard",
        description="Off-by-one: sliding window exato",
        prompt=textwrap.dedent("""\
            Write a Python function `max_sum_subarray(arr: list[int], k: int) -> int` that returns the maximum sum of any contiguous subarray of exactly k elements. Raise ValueError if k > len(arr) or k <= 0. Return ONLY the function.
        """),
        test_harness=textwrap.dedent("""
            assert max_sum_subarray([2,1,5,1,3,2], 3) == 9
            assert max_sum_subarray([2,3,4,1,5], 2) == 7
            assert max_sum_subarray([-1,-2,-3,-4], 2) == -3
            assert max_sum_subarray([1], 1) == 1
            try:
                max_sum_subarray([1,2,3], 4)
                assert False
            except ValueError:
                pass
            try:
                max_sum_subarray([1,2,3], 0)
                assert False
            except ValueError:
                pass
            print("PASS")
        """),
        max_tokens=200,
        notes="Off-by-one in sliding window, edge cases with k=0 and k>len",
    ),
    Task(
        id="redteam_02",
        category="redteam",
        difficulty="hard",
        description="Float precision: comparacao monetaria",
        prompt=textwrap.dedent("""\
            Write a Python function `split_bill(total_cents: int, people: int) -> list[int]` that splits a bill (in cents, integer) as evenly as possible among `people`. Extra cents go to the first people. Returns a list of `people` integers that sums to total_cents. Raise ValueError if people <= 0. Return ONLY the function.
        """),
        test_harness=textwrap.dedent("""
            r = split_bill(100, 3)
            assert sum(r) == 100, f"sum={sum(r)}"
            assert len(r) == 3
            assert sorted(r, reverse=True) == r or max(r)-min(r) <= 1, f"not fair: {r}"
            # 100 / 3 = 33, 33, 34
            assert sorted(r) == [33, 33, 34], f"got {sorted(r)}"

            r2 = split_bill(99, 3)
            assert sum(r2) == 99
            assert all(x == 33 for x in r2), f"got {r2}"

            r3 = split_bill(1, 3)
            assert sum(r3) == 1
            assert sorted(r3) == [0, 0, 1], f"got {r3}"

            try:
                split_bill(100, 0)
                assert False
            except ValueError:
                pass
            print("PASS")
        """),
        max_tokens=180,
        notes="Models use float division and get rounding wrong",
    ),
    Task(
        id="redteam_03",
        category="redteam",
        difficulty="hard",
        description="Context manager com excecao parcial",
        prompt=textwrap.dedent("""\
            Write a Python context manager class `TempFile` that:
            1. Creates a named temp file on `__enter__`, returns the file path
            2. On `__exit__`: always deletes the file (even if exception occurred)
            3. On `__exit__`: if an exception occurred AND it's an IOError, suppress it (return True)
            4. On `__exit__`: if any other exception occurred, re-raise it (return False/None)
            Use tempfile and os modules only. Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            import os, tempfile

            # Normal usage
            with TempFile() as path:
                assert os.path.exists(path)
                with open(path, 'w') as f:
                    f.write("test")
            assert not os.path.exists(path), "File should be deleted"

            # IOError suppressed
            try:
                with TempFile() as path:
                    raise IOError("disk full")
                # Should not raise
            except IOError:
                assert False, "IOError should be suppressed"
            assert not os.path.exists(path), "File still deleted on IOError"

            # Other exception re-raised
            try:
                with TempFile() as path:
                    raise ValueError("bad value")
                assert False, "ValueError should propagate"
            except ValueError:
                pass
            assert not os.path.exists(path), "File still deleted on ValueError"

            print("PASS")
        """),
        max_tokens=280,
        notes="__exit__ signature, exception suppression logic, always-delete guarantee",
    ),
    Task(
        id="redteam_04",
        category="redteam",
        difficulty="hard",
        description="Parsing ambiguo: CSV com campos cotados",
        prompt=textwrap.dedent("""\
            Write a Python function `parse_csv_line(line: str) -> list[str]` that correctly parses a single CSV line where:
            - Fields are comma-separated
            - Fields may be quoted with double quotes
            - Quoted fields may contain commas
            - Quoted fields may contain escaped quotes (two double-quotes = one literal quote)
            - Do NOT use the csv module. Return ONLY the function.
        """),
        test_harness=textwrap.dedent("""
            q = '\x22'
            assert parse_csv_line('a,b,c') == ['a', 'b', 'c']
            assert parse_csv_line(q+'hello, world'+q+',b,c') == ['hello, world', 'b', 'c']
            # escaped quote: CSV doubled-quote escaping: say [qq]hi[qq] inside a field
            escaped = q+'say '+q+q+'hi'+q+q+q+',b'
            assert parse_csv_line(escaped) == ['say '+q+'hi'+q, 'b'], f"got {parse_csv_line(escaped)}"
            assert parse_csv_line(',,') == ['', '', '']
            assert parse_csv_line(q+q+',b') == ['', 'b']
            assert parse_csv_line(q+'a,b,c'+q) == ['a,b,c']
            assert parse_csv_line('a,'+q+'b,c'+q+',d') == ['a', 'b,c', 'd']
            print("PASS")
        """),
        max_tokens=350,
        notes="CSV edge cases: empty fields, escaped quotes, all-quoted - state machine needed",
    ),
    Task(
        id="redteam_05",
        category="redteam",
        difficulty="hard",
        description="Confidence trap: tarefa impossivel como pedida",
        prompt=textwrap.dedent("""\
            Write a Python function `is_halting(code: str) -> bool` that determines whether a given Python program (passed as a string) will halt (return True) or run forever (return False).
        """),
        test_harness=textwrap.dedent("""
            # This task is undecidable (Halting Problem).
            # The model should either:
            # a) Raise NotImplementedError with a clear message about undecidability, OR
            # b) The response text contains "halting problem", "undecidable", or "impossible"
            # A model that silently returns a heuristic without warning is WRONG.
            import inspect
            try:
                src = inspect.getsource(is_halting)
            except:
                src = ""

            # Try to get raw response from the function's docstring or raise
            try:
                result = is_halting("while True: pass")
                # If it returned True/False silently, it's a hallucination
                # Check if there's at least a warning in docstring
                doc = is_halting.__doc__ or ""
                if any(w in doc.lower() for w in ["halting", "undecidable", "heuristic", "approximat"]):
                    print("PASS (with caveats)")
                else:
                    print("FAIL: returned result without acknowledging undecidability")
            except NotImplementedError as e:
                if any(w in str(e).lower() for w in ["halting", "undecidable", "impossible"]):
                    print("PASS")
                else:
                    print("FAIL: NotImplementedError but no mention of halting problem")
            except Exception as e:
                print(f"FAIL: unexpected exception {type(e).__name__}: {e}")
        """),
        max_tokens=250,
        notes="Halting problem - models often implement a heuristic silently (hallucination of capability)",
        timeout=15,
    ),

    # =========================================================================
    # CATEGORIA: multifile — interacao entre multiplas classes/modulos
    # =========================================================================
    Task(
        id="mf_01",
        category="multifile",
        difficulty="medium",
        description="EventEmitter + EventLogger cooperando",
        prompt=textwrap.dedent("""\
            Write two Python classes that work together:

            1. `EventEmitter`:
               - `on(event_name: str, callback)`: register callback for an event
               - `emit(event_name: str, data: dict)`: invoke all callbacks for that event

            2. `EventLogger`:
               - `subscribe(emitter: EventEmitter)`: register itself to receive ALL events
               - `events`: list of dicts with keys "event" and "data"

            Return ONLY both classes, no example usage.
        """),
        test_harness=textwrap.dedent("""
            emitter = EventEmitter()
            logger = EventLogger()
            logger.subscribe(emitter)
            emitter.emit("login", {"user": "alice"})
            emitter.emit("purchase", {"item": "book", "price": 12.99})
            assert len(logger.events) == 2, f"expected 2, got {len(logger.events)}"
            assert logger.events[0]["event"] == "login"
            assert logger.events[1]["data"]["price"] == 12.99

            emitter.emit("logout", {})
            assert len(logger.events) == 3

            emitter2 = EventEmitter()
            emitter2.emit("other", {})
            assert len(logger.events) == 3, "received event from unsubscribed emitter"
            print("PASS")
        """),
        max_tokens=400,
        notes="Two classes must cooperate via a publish/subscribe interface",
    ),
    Task(
        id="mf_02",
        category="multifile",
        difficulty="hard",
        description="Refactor God Class em UserStore + UserValidator",
        prompt=textwrap.dedent("""\
            Refactor this class into `UserStore` (storage) and `UserValidator` (validation).
            `UserStore` uses `UserValidator` internally and exposes the same public methods.
            Return ONLY both classes.

            ```python
            class UserManager:
                def __init__(self):
                    self._users = {}

                def create_user(self, username: str, email: str, age: int) -> dict:
                    if not username or not isinstance(username, str):
                        raise ValueError("username required")
                    if "@" not in email:
                        raise ValueError("invalid email")
                    if not (0 <= age <= 150):
                        raise ValueError("age out of range")
                    if username in self._users:
                        raise ValueError("username exists")
                    user = {"username": username, "email": email, "age": age}
                    self._users[username] = user
                    return user

                def get_user(self, username: str) -> dict | None:
                    return self._users.get(username)

                def update_email(self, username: str, new_email: str) -> bool:
                    if "@" not in new_email:
                        raise ValueError("invalid email")
                    if username not in self._users:
                        return False
                    self._users[username]["email"] = new_email
                    return True

                def delete_user(self, username: str) -> bool:
                    if username not in self._users:
                        return False
                    del self._users[username]
                    return True

                def count(self) -> int:
                    return len(self._users)
            ```
        """),
        test_harness=textwrap.dedent("""
            store = UserStore()
            u = store.create_user("alice", "alice@example.com", 30)
            assert u["username"] == "alice"
            assert store.count() == 1
            assert store.get_user("alice")["email"] == "alice@example.com"
            assert store.get_user("nobody") is None
            assert store.update_email("alice", "new@example.com") == True
            assert store.get_user("alice")["email"] == "new@example.com"
            assert store.delete_user("alice") == True
            assert store.count() == 0
            assert store.delete_user("alice") == False
            try:
                store.create_user("", "x@x.com", 25)
                assert False
            except ValueError:
                pass
            try:
                store.create_user("bob", "notanemail", 25)
                assert False
            except ValueError:
                pass
            print("PASS")
        """),
        max_tokens=700,
        notes="God-class split — structural decomposition + preserved public API",
    ),
    Task(
        id="mf_03",
        category="multifile",
        difficulty="hard",
        description="Pipeline Source -> Transform -> Sink encadeavel",
        prompt=textwrap.dedent("""\
            Write three Python classes for a composable data pipeline:

            1. `Source(items: list)` — has `read()` that yields items
            2. `Transform(source, fn: callable)` — has `read()` that yields fn(item) for each item
            3. `Sink(source)` — has `collect() -> list` that reads all items and returns them

            Must be chainable: `Sink(Transform(Transform(Source([1,2,3]), fn1), fn2)).collect()`
            Return ONLY the three classes.
        """),
        test_harness=textwrap.dedent("""
            result = Sink(Transform(Transform(Source([1,2,3,4,5]), lambda x: x*2), lambda x: x+1)).collect()
            assert result == [3, 5, 7, 9, 11], f"got {result}"
            assert Sink(Transform(Source(["a","b"]), str.upper)).collect() == ["A","B"]
            assert Sink(Source([])).collect() == []
            # Multiple collects on fresh pipeline
            s = Source([10, 20])
            assert Sink(Transform(s, lambda x: x-1)).collect() == [9, 19]
            print("PASS")
        """),
        max_tokens=350,
        notes="Pipeline / iterator chaining pattern",
    ),

    # =========================================================================
    # CATEGORIA: debug — identificar e corrigir dado traceback ou output errado
    # =========================================================================
    Task(
        id="dbg_01",
        category="debug",
        difficulty="medium",
        description="Debug: None propagation em cadeia de chamadas",
        prompt=textwrap.dedent("""\
            Fix the bug and return ONLY the corrected `process` function.
            The bug: when `parse` returns None, `process` crashes instead of returning None.

            ```python
            def parse(text: str):
                text = text.strip()
                if not text:
                    return None
                parts = text.split(":")
                if len(parts) != 2:
                    return None
                return {"key": parts[0].strip(), "value": parts[1].strip()}

            def normalize(parsed: dict) -> dict:
                return {"key": parsed["key"].lower(), "value": parsed["value"].strip()}

            def process(text: str) -> dict | None:
                return normalize(parse(text))
            ```
        """),
        test_harness=textwrap.dedent("""
            assert process("Name: Alice") == {"key": "name", "value": "Alice"}
            assert process("") is None
            assert process("   ") is None
            assert process("invalid_no_colon") is None
            assert process("Key : Value  ") == {"key": "key", "value": "Value"}
            print("PASS")
        """),
        max_tokens=180,
        notes="None guard before chaining — extremely common real-world bug",
    ),
    Task(
        id="dbg_02",
        category="debug",
        difficulty="medium",
        description="Debug: funcao ausente + off-by-one em paginacao",
        prompt=textwrap.dedent("""\
            `paginate` works correctly, but `get_page_count` is missing (causing the test to fail).
            Add `get_page_count` and return BOTH functions.

            ```python
            def paginate(items: list, page: int, page_size: int) -> list:
                start = page * page_size
                end = start + page_size
                return items[start:end]
            ```

            Failing test output:
              get_page_count([1..10], page_size=3) => NameError: get_page_count not defined
            Expected: 4 pages for 10 items with page_size=3 (pages 0,1,2 have 3 items; page 3 has 1)
        """),
        test_harness=textwrap.dedent("""
            items = list(range(1, 11))
            assert paginate(items, 0, 3) == [1, 2, 3]
            assert paginate(items, 1, 3) == [4, 5, 6]
            assert paginate(items, 3, 3) == [10]
            assert paginate(items, 4, 3) == []
            assert get_page_count(items, 3) == 4, f"got {get_page_count(items, 3)}"
            assert get_page_count(items, 10) == 1
            assert get_page_count([], 5) == 0
            assert get_page_count([1], 5) == 1
            print("PASS")
        """),
        max_tokens=200,
        notes="Ceiling division (math.ceil or -(-n//k)) — missing function from existing code",
    ),
    Task(
        id="dbg_03",
        category="debug",
        difficulty="hard",
        description="Debug: modificar lista durante iteracao",
        prompt=textwrap.dedent("""\
            This function has a classic Python mutation-while-iterating bug AND incorrect logic.
            Fix it and return ONLY the corrected function.
            Goal: keep the LAST occurrence of each duplicate, in original order.

            ```python
            def remove_duplicates_keep_last(items: list) -> list:
                seen = set()
                for i, item in enumerate(items):
                    if item in seen:
                        items.pop(i)
                    else:
                        seen.add(item)
                return items
            ```
        """),
        test_harness=textwrap.dedent("""
            assert remove_duplicates_keep_last([1, 2, 1, 3, 2]) == [1, 3, 2], f"got {remove_duplicates_keep_last([1, 2, 1, 3, 2])}"
            assert remove_duplicates_keep_last([1, 1, 1]) == [1]
            assert remove_duplicates_keep_last([1, 2, 3]) == [1, 2, 3]
            assert remove_duplicates_keep_last([]) == []
            assert remove_duplicates_keep_last([3, 1, 2, 1, 3]) == [2, 1, 3], f"got {remove_duplicates_keep_last([3, 1, 2, 1, 3])}"
            print("PASS")
        """),
        max_tokens=250,
        notes="Two bugs: mutation during iteration + wrong keep-last semantics",
    ),
    Task(
        id="dbg_04",
        category="debug",
        difficulty="hard",
        description="Debug: coroutine nunca executada (missing asyncio.run)",
        prompt=textwrap.dedent("""\
            `fetch_all` is correct. `run_fetch` is broken — it returns a coroutine object instead of running it.
            Fix `run_fetch` so it runs the async function synchronously and returns the results.
            Return BOTH functions.

            ```python
            import asyncio

            async def fetch_all(urls: list[str], fetcher) -> list[str]:
                tasks = [fetcher(url) for url in urls]
                return await asyncio.gather(*tasks)

            def run_fetch(urls: list[str], fetcher) -> list[str]:
                return fetch_all(urls, fetcher)
            ```
        """),
        test_harness=textwrap.dedent("""
            import asyncio

            async def mock_fetcher(url: str) -> str:
                return f"content:{url}"

            results = run_fetch(["a", "b", "c"], mock_fetcher)
            assert isinstance(results, list), f"got type {type(results)}"
            assert results == ["content:a", "content:b", "content:c"], f"got {results}"
            print("PASS")
        """),
        max_tokens=180,
        notes="asyncio.run() bridge — very common real-world async/sync boundary bug",
    ),

    # =========================================================================
    # CATEGORIA: longctx — modificar codigo com muito contexto no prompt
    # =========================================================================
    Task(
        id="lctx_01",
        category="longctx",
        difficulty="hard",
        description="Adicionar metodo stats() a classe de 120 linhas",
        prompt=textwrap.dedent("""\
            Add a method `stats() -> dict` to this class that returns:
            {"count": int, "mean": float, "min": float, "max": float, "stddev": float}
            Raise ValueError if no data. Return ONLY the complete updated class.

            ```python
            class MetricsStore:
                def __init__(self, name: str):
                    self.name = name
                    self._data = []
                    self._tags = {}
                    self._sum = 0.0
                    self._sum_sq = 0.0

                def record(self, value: float, tag: str = "default"):
                    if not isinstance(value, (int, float)):
                        raise TypeError("value must be numeric")
                    self._data.append(value)
                    self._sum += value
                    self._sum_sq += value * value
                    self._tags[tag] = self._tags.get(tag, 0) + 1

                def count(self) -> int:
                    return len(self._data)

                def mean(self) -> float:
                    if not self._data:
                        raise ValueError("no data")
                    return self._sum / len(self._data)

                def percentile(self, p: float) -> float:
                    if not self._data:
                        raise ValueError("no data")
                    if not (0 <= p <= 100):
                        raise ValueError("percentile must be 0-100")
                    sorted_data = sorted(self._data)
                    idx = (p / 100) * (len(sorted_data) - 1)
                    lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
                    return sorted_data[lo] + (idx - lo) * (sorted_data[hi] - sorted_data[lo])

                def tag_counts(self) -> dict:
                    return dict(self._tags)

                def reset(self):
                    self._data = []
                    self._tags = {}
                    self._sum = 0.0
                    self._sum_sq = 0.0

                def merge(self, other: "MetricsStore"):
                    for v in other._data:
                        self.record(v)

                def top_n(self, n: int) -> list:
                    return sorted(self._data, reverse=True)[:n]

                def below_threshold(self, threshold: float) -> list:
                    return [v for v in self._data if v < threshold]

                def above_threshold(self, threshold: float) -> list:
                    return [v for v in self._data if v >= threshold]

                def recent(self, n: int) -> list:
                    return self._data[-n:]
            ```
        """),
        test_harness=textwrap.dedent("""
            import math
            m = MetricsStore("test")
            try:
                m.stats()
                assert False, "should raise on empty"
            except ValueError:
                pass
            for v in [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]:
                m.record(v)
            s = m.stats()
            assert s["count"] == 8
            assert abs(s["mean"] - 5.0) < 0.001, f"mean={s['mean']}"
            assert s["min"] == 2.0
            assert s["max"] == 9.0
            # stddev of [2,4,4,4,5,5,7,9]: population or sample both ~2.0
            assert 1.8 < s["stddev"] < 2.2, f"stddev={s['stddev']}"
            # existing methods still work
            assert m.count() == 8
            assert abs(m.mean() - 5.0) < 0.001
            print("PASS")
        """),
        max_tokens=900,
        notes="Must preserve all existing methods + add stddev correctly (not confuse pop vs sample)",
        timeout=120,
    ),
    Task(
        id="lctx_02",
        category="longctx",
        difficulty="hard",
        description="Corrigir bug em get_nested() dado traceback",
        prompt=textwrap.dedent("""\
            Fix the bug in `get_nested` and return ONLY the complete corrected class.
            The stack trace shows:
              File "config.py", line 34, in get_nested
                current = current[key]
              KeyError: 'timeout'
            when calling `cfg.get_nested("database.pool.timeout", default=30)` on a config
            that has `{"database": {"pool": {}}}` — the key is missing mid-path.

            ```python
            class ConfigStore:
                def __init__(self, data: dict):
                    self._data = data

                def get(self, key: str, default=None):
                    return self._data.get(key, default)

                def set(self, key: str, value):
                    self._data[key] = value

                def get_nested(self, path: str, default=None):
                    keys = path.split(".")
                    current = self._data
                    for key in keys:
                        current = current[key]
                    return current

                def set_nested(self, path: str, value):
                    keys = path.split(".")
                    current = self._data
                    for key in keys[:-1]:
                        if key not in current:
                            current[key] = {}
                        current = current[key]
                    current[keys[-1]] = value

                def has(self, key: str) -> bool:
                    return key in self._data

                def has_nested(self, path: str) -> bool:
                    try:
                        self.get_nested(path)
                        return True
                    except (KeyError, TypeError):
                        return False

                def merge(self, other: dict):
                    def deep_merge(base, override):
                        for k, v in override.items():
                            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                                deep_merge(base[k], v)
                            else:
                                base[k] = v
                    deep_merge(self._data, other)

                def to_dict(self) -> dict:
                    return dict(self._data)
            ```
        """),
        test_harness=textwrap.dedent("""
            cfg = ConfigStore({"database": {"pool": {}, "host": "localhost"}, "debug": True})
            # Bug fix: missing key in path returns default
            assert cfg.get_nested("database.pool.timeout", default=30) == 30
            assert cfg.get_nested("database.host") == "localhost"
            assert cfg.get_nested("missing.key", default="x") == "x"
            assert cfg.get_nested("debug") == True
            # set_nested still works
            cfg.set_nested("database.pool.timeout", 60)
            assert cfg.get_nested("database.pool.timeout") == 60
            # has_nested
            assert cfg.has_nested("database.host") == True
            assert cfg.has_nested("database.port") == False
            # merge
            cfg.merge({"cache": {"ttl": 300}})
            assert cfg.get_nested("cache.ttl") == 300
            print("PASS")
        """),
        max_tokens=600,
        notes="Fix one-liner KeyError bug in a larger class — must not touch other methods",
        timeout=120,
    ),
    Task(
        id="lctx_03",
        category="longctx",
        difficulty="hard",
        description="Adicionar metodo paginate() a cliente HTTP existente",
        prompt=textwrap.dedent("""\
            Add a method `paginate(endpoint: str, page_param: str = "page", per_page: int = 20) -> list`
            to this HTTP client. It should call `self.get(endpoint, params={page_param: n, "per_page": per_page})`
            repeatedly, starting at page 1, and stop ONLY when the response is an empty list [].
            A partial page (fewer than per_page items) is NOT a stop signal — always fetch the next page to confirm.
            Collect and return all items. Return ONLY the complete updated class.

            ```python
            class HttpClient:
                def __init__(self, base_url: str, timeout: int = 30):
                    self.base_url = base_url.rstrip("/")
                    self.timeout = timeout
                    self._session_headers = {}
                    self._last_status = None

                def set_header(self, key: str, value: str):
                    self._session_headers[key] = value

                def remove_header(self, key: str):
                    self._session_headers.pop(key, None)

                def get(self, endpoint: str, params: dict = None) -> list | dict:
                    import urllib.parse, urllib.request, json
                    url = self.base_url + "/" + endpoint.lstrip("/")
                    if params:
                        url += "?" + urllib.parse.urlencode(params)
                    req = urllib.request.Request(url, headers=self._session_headers)
                    try:
                        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                            self._last_status = resp.status
                            return json.loads(resp.read())
                    except Exception as e:
                        self._last_status = getattr(e, "code", 0)
                        raise

                def post(self, endpoint: str, body: dict) -> dict:
                    import urllib.request, json
                    url = self.base_url + "/" + endpoint.lstrip("/")
                    data = json.dumps(body).encode()
                    headers = {**self._session_headers, "Content-Type": "application/json"}
                    req = urllib.request.Request(url, data=data, headers=headers)
                    try:
                        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                            self._last_status = resp.status
                            return json.loads(resp.read())
                    except Exception as e:
                        self._last_status = getattr(e, "code", 0)
                        raise

                def last_status(self) -> int | None:
                    return self._last_status
            ```
        """),
        test_harness=textwrap.dedent("""
            # Monkey-patch get() to simulate paginated API
            pages = {
                1: [{"id": i} for i in range(1, 21)],   # 20 items
                2: [{"id": i} for i in range(21, 41)],  # 20 items
                3: [{"id": i} for i in range(41, 46)],  # 5 items (last page)
                4: [],                                    # empty = stop
            }
            call_log = []

            client = HttpClient("http://fake")
            def fake_get(endpoint, params=None):
                page = (params or {}).get("page", 1)
                call_log.append(page)
                return pages.get(page, [])
            client.get = fake_get

            result = client.paginate("/items")
            assert len(result) == 45, f"expected 45, got {len(result)}"
            assert result[0] == {"id": 1}
            assert result[44] == {"id": 45}
            assert call_log == [1, 2, 3, 4], f"expected pages 1-4 called, got {call_log}"
            print("PASS")
        """),
        max_tokens=700,
        notes="Must integrate cleanly with existing methods; stop condition logic is tricky",
        timeout=120,
    ),

    # =========================================================================
    # CATEGORIA: integration — combinar multiplos conceitos em uma solucao
    # =========================================================================
    Task(
        id="int_01",
        category="integration",
        difficulty="hard",
        description="Cache thread-safe com TTL e eviction LRU",
        prompt=textwrap.dedent("""\
            Write a Python class `TTLCache` with:
            - `__init__(self, maxsize: int, ttl: float)` — maxsize entries, ttl in seconds
            - `get(key) -> value | None` — return value if exists and not expired, else None
            - `set(key, value)` — store; evict LRU entry if at maxsize
            - `__len__() -> int` — number of non-expired entries
            Thread-safe (threading.Lock). Do NOT use cachetools or functools. Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            import time, threading

            c = TTLCache(maxsize=3, ttl=0.3)
            c.set("a", 1)
            c.set("b", 2)
            c.set("c", 3)
            assert c.get("a") == 1
            assert len(c) == 3

            # LRU eviction: "b" is LRU (a was accessed, c is newest)
            c.set("d", 4)
            assert c.get("b") is None, "b should have been evicted (LRU)"
            assert c.get("a") == 1
            assert c.get("d") == 4

            # TTL expiry
            c2 = TTLCache(maxsize=10, ttl=0.1)
            c2.set("x", 99)
            assert c2.get("x") == 99
            time.sleep(0.15)
            assert c2.get("x") is None, "x should have expired"

            # Thread safety smoke test
            c3 = TTLCache(maxsize=100, ttl=5)
            def writer():
                for i in range(100):
                    c3.set(f"k{i}", i)
            threads = [threading.Thread(target=writer) for _ in range(5)]
            for t in threads: t.start()
            for t in threads: t.join()
            print("PASS")
        """),
        max_tokens=600,
        notes="Combines LRU eviction + TTL + thread safety — three hard things at once",
        timeout=30,
    ),
    Task(
        id="int_02",
        category="integration",
        difficulty="hard",
        description="Decorator async com retry e exponential backoff",
        prompt=textwrap.dedent("""\
            Write a Python decorator `async_retry(max_attempts: int, base_delay: float, exceptions: tuple)`
            that retries an async function with exponential backoff (delay doubles each attempt).
            On final failure, re-raises the last exception. Preserves __name__ via functools.wraps.
            Return ONLY the decorator function.
        """),
        test_harness=textwrap.dedent("""
            import asyncio, time

            async def test():
                call_count = 0
                delays = []

                @async_retry(max_attempts=3, base_delay=0.05, exceptions=(ValueError,))
                async def flaky():
                    nonlocal call_count
                    call_count += 1
                    if call_count < 3:
                        raise ValueError("not yet")
                    return "ok"

                t0 = time.monotonic()
                result = await flaky()
                elapsed = time.monotonic() - t0
                assert result == "ok", f"got {result}"
                assert call_count == 3, f"expected 3 calls, got {call_count}"
                # Should have waited ~0.05 + ~0.10 = ~0.15s
                assert elapsed >= 0.12, f"too fast: {elapsed:.3f}s"

                # Final failure re-raises
                call_count = 0
                @async_retry(max_attempts=2, base_delay=0.01, exceptions=(ValueError,))
                async def always_fails():
                    nonlocal call_count
                    call_count += 1
                    raise ValueError("always")

                try:
                    await always_fails()
                    assert False
                except ValueError:
                    assert call_count == 2

                # Non-listed exception propagates immediately
                @async_retry(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))
                async def raises_type_error():
                    raise TypeError("other")

                call_count = 0
                try:
                    await raises_type_error()
                    assert False
                except TypeError:
                    pass

                assert flaky.__name__ == "flaky"
                print("PASS")

            asyncio.run(test())
        """),
        max_tokens=400,
        notes="Combines async + decorators + exponential backoff timing",
        timeout=30,
    ),
    Task(
        id="int_03",
        category="integration",
        difficulty="hard",
        description="Observer com weak references (sem memory leak)",
        prompt=textwrap.dedent("""\
            Write a Python class `WeakObservable` that:
            - `subscribe(callback)`: register a callback (store as weakref if possible)
            - `notify(data)`: call all living callbacks with data; silently drop dead refs
            - Callbacks registered as bound methods or lambdas must work
            - When an object's method is subscribed and the object is deleted, notify() must not crash
            Use weakref module. Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            import weakref, gc

            obs = WeakObservable()
            results = []

            class Listener:
                def on_event(self, data):
                    results.append(data)

            l1 = Listener()
            obs.subscribe(l1.on_event)
            obs.notify("first")
            assert results == ["first"]

            # After deletion, notify must not crash
            del l1
            gc.collect()
            obs.notify("second")  # l1 is gone, should be silently skipped

            # Lambda (strong ref) still works
            obs.subscribe(lambda d: results.append(f"lambda:{d}"))
            obs.notify("third")
            assert "lambda:third" in results

            print("PASS")
        """),
        max_tokens=600,
        notes="weakref.WeakMethod for bound methods — tricky; dead ref cleanup on notify",
        timeout=20,
    ),

    # =========================================================================
    # CATEGORIA: edgecase — casos que modelos tratam incorretamente por excesso de confianca
    # =========================================================================
    Task(
        id="ec_01",
        category="edgecase",
        difficulty="hard",
        description="Unicode: comparacao normalizada com emoji e acentos",
        prompt=textwrap.dedent("""\
            Write a Python function `normalized_eq(a: str, b: str) -> bool` that returns True if
            two strings are equal after Unicode NFC normalization and case-folding (casefold).
            Also write `normalized_contains(haystack: str, needle: str) -> bool`.
            Handle: accented chars, emoji (treated as-is), zero-width joiners.
            Use only the `unicodedata` standard module. Return ONLY both functions.
        """),
        test_harness=textwrap.dedent("""
            import unicodedata
            # NFC: e + combining accent = precomposed e-acute
            e_composed = '\u00e9'        # precomposed e-acute
            e_decomposed = 'e\u0301'     # e + combining acute

            assert normalized_eq(e_composed, e_decomposed), "NFC normalization failed"
            assert normalized_eq("Cafe", "cafe"), "case-fold failed"
            assert normalized_eq("HELLO", "hello")
            assert not normalized_eq("hello", "world")

            assert normalized_contains("Caf\u00e9 au lait", "cafe"), "contains with NFC+casefold"
            assert normalized_contains("Hello World", "world")
            assert not normalized_contains("hello", "xyz")

            # Emoji: treated as-is (no normalization changes emoji)
            assert normalized_eq("\U0001f600", "\U0001f600")
            assert not normalized_eq("\U0001f600", "\U0001f601")
            print("PASS")
        """),
        max_tokens=300,
        notes="unicodedata.normalize + casefold; decomposed vs composed forms trip up models",
    ),
    Task(
        id="ec_02",
        category="edgecase",
        difficulty="hard",
        description="Decimal: classe Money sem erros de float",
        prompt=textwrap.dedent("""\
            Write a Python class `Money` using `decimal.Decimal` internally:
            - `__init__(self, amount: str | int | float, currency: str = "USD")`
              Convert float to Decimal via string to avoid floating-point imprecision.
            - `__add__`, `__sub__`: same currency only (raise ValueError otherwise)
            - `__mul__(self, factor: int | float) -> Money`: multiply amount by factor
            - `__eq__`, `__lt__`, `__le__`
            - `__str__`: e.g. "USD 10.50"
            - `round_to(decimals: int) -> Money`
            Return ONLY the class.
        """),
        test_harness=textwrap.dedent("""
            from decimal import Decimal
            a = Money("10.50")
            b = Money("0.10")
            assert str(a + b) == "USD 10.60", f"got {a+b}"
            assert str(a - b) == "USD 10.40"

            # Float imprecision guard
            c = Money(0.1) + Money(0.2)
            assert c == Money("0.3"), f"float bug: {c}"

            # Multiplication
            assert str(Money("5.00") * 3) == "USD 15.00"
            assert str(Money("1.00") * 0.1) == "USD 0.10" or Money("1.00") * 0.1 == Money("0.1")

            # Currency mismatch
            try:
                Money("1.00", "USD") + Money("1.00", "EUR")
                assert False
            except ValueError:
                pass

            # Comparison
            assert Money("5") < Money("10")
            assert Money("5") <= Money("5")
            assert Money("5") == Money("5.00")

            # round_to
            assert str(Money("10.567").round_to(2)) == "USD 10.57"
            print("PASS")
        """),
        max_tokens=450,
        notes="Decimal precision, float-via-string init, currency mismatch errors",
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_id: str
    category: str
    difficulty: str
    description: str
    model_key: str
    model_label: str
    passed: bool
    elapsed: float
    tps: float
    completion_tokens: int
    error: str = ""
    raw_response: str = ""
    extracted_code: str = ""
    test_output: str = ""


def run_task(task: Task, model_key: str) -> TaskResult:
    cfg = MODELS[model_key]
    # For models with thinking overhead, scale the timeout proportionally.
    overhead = cfg.get("thinking_overhead", 0)
    effective_timeout = task.timeout + int(overhead / 10)  # ~10 tok/s worst-case
    result = call_model(model_key, task.prompt, max_tokens=task.max_tokens, timeout=effective_timeout)

    if not result["ok"]:
        return TaskResult(
            task_id=task.id, category=task.category, difficulty=task.difficulty,
            description=task.description, model_key=model_key, model_label=cfg["label"],
            passed=False, elapsed=result["elapsed"], tps=0,
            completion_tokens=0, error=result.get("error", "API error"),
        )

    content = result["content"]
    code = extract_code(content)

    harness = task.test_harness
    if "RESPONSE" in harness:
        # SQL tasks: harness handles extraction internally — only inject RESPONSE, don't prepend SQL code
        harness = f'RESPONSE = {repr(content)}\n' + harness
        passed, test_out = run_code("", harness, timeout=task.timeout)
    else:
        code = extract_code(content)
        passed, test_out = run_code(code, harness, timeout=task.timeout)

    return TaskResult(
        task_id=task.id, category=task.category, difficulty=task.difficulty,
        description=task.description, model_key=model_key, model_label=cfg["label"],
        passed=passed, elapsed=result["elapsed"], tps=result["tps"],
        completion_tokens=result["completion_tokens"],
        error="" if passed else test_out[:300],
        raw_response=content[:500],
        extracted_code=code[:400],
        test_output=test_out[:300],
    )


def print_result(r: TaskResult):
    status = "PASS" if r.passed else "FAIL"
    tps_str = f"{r.tps:.1f} tok/s" if r.tps > 0 else "N/A"
    print(f"  [{status}] {r.task_id:<15} {r.elapsed:>6.1f}s  {tps_str:>12}  {r.completion_tokens:>5} tok", flush=True)
    if not r.passed and r.error:
        for line in r.error.splitlines()[:3]:
            print(f"         >> {line}", flush=True)


def run_benchmark(model_keys: list[str], categories: list[str] | None = None) -> list[TaskResult]:
    tasks = TASKS
    if categories:
        tasks = [t for t in tasks if t.category in categories]

    all_results = []
    for model_key in model_keys:
        cfg = MODELS[model_key]
        print(f"\n{'='*70}")
        print(f"MODELO: {cfg['label']}")
        print(f"{'='*70}")

        cat_results: dict[str, list[TaskResult]] = {}
        for task in tasks:
            print(f"\n  [{task.category.upper()}] {task.description} ({task.difficulty})", flush=True)
            r = run_task(task, model_key)
            print_result(r)
            all_results.append(r)
            cat_results.setdefault(task.category, []).append(r)

        # Summary per category
        print(f"\n  {'-'*60}")
        print(f"  RESUMO - {cfg['label']}")
        print(f"  {'-'*60}")
        total_pass = sum(1 for r in all_results if r.model_key == model_key and r.passed)
        total = sum(1 for r in all_results if r.model_key == model_key)
        avg_tps = [r.tps for r in all_results if r.model_key == model_key and r.tps > 0]
        for cat, results in cat_results.items():
            passes = sum(1 for r in results if r.passed)
            print(f"  {cat:<20} {passes}/{len(results)} PASS")
        print(f"  {'-'*60}")
        print(f"  TOTAL: {total_pass}/{total}  avg tok/s: {sum(avg_tps)/len(avg_tps):.1f}" if avg_tps else f"  TOTAL: {total_pass}/{total}")

    return all_results


def save_results(results: list[TaskResult], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = output_dir / f"benchmark_{ts}.json"
    data = {
        "timestamp": datetime.now().isoformat(),
        "results": [asdict(r) for r in results],
        "summary": {}
    }
    # Build summary
    for model_key in set(r.model_key for r in results):
        mrs = [r for r in results if r.model_key == model_key]
        data["summary"][model_key] = {
            "total": len(mrs),
            "passed": sum(1 for r in mrs if r.passed),
            "avg_tps": sum(r.tps for r in mrs if r.tps > 0) / max(1, sum(1 for r in mrs if r.tps > 0)),
            "by_category": {},
            "by_difficulty": {},
        }
        for cat in set(r.category for r in mrs):
            cr = [r for r in mrs if r.category == cat]
            data["summary"][model_key]["by_category"][cat] = f"{sum(1 for r in cr if r.passed)}/{len(cr)}"
        for diff in set(r.difficulty for r in mrs):
            dr = [r for r in mrs if r.difficulty == diff]
            data["summary"][model_key]["by_difficulty"][diff] = f"{sum(1 for r in dr if r.passed)}/{len(dr)}"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados salvos: {out}")
    return out


# Temperature sweep: tasks used as probe set (mix of difficulties)
TEMP_SWEEP_TASK_IDS = [
    "trivial_01",   # easy baseline
    "algo_01",      # medium logic
    "algo_02",      # medium sorting
    "data_01",      # data structures
    "refactor_01",  # refactoring (known hard)
    "adv_01",       # adversarial
    "dbg_01",       # debug
    "lctx_01",      # long context
    "int_01",       # integration
    "ec_01",        # edge case
]

TEMP_SWEEP_VALUES = [0.1, 0.3, 0.5, 0.7, 1.0, 1.3]


def run_temp_sweep(model_key: str, task_ids: list[str] | None = None) -> None:
    """Run a subset of tasks across multiple temperatures and print a pass-rate matrix."""
    ids = task_ids or TEMP_SWEEP_TASK_IDS
    probe_tasks = [t for t in TASKS if t.id in ids]
    if not probe_tasks:
        print("No matching tasks for temp sweep.")
        return

    cfg = MODELS[model_key]
    original_temp = cfg.get("temperature", 0.2)
    print(f"\n{'='*70}")
    print(f"TEMPERATURE SWEEP: {cfg['label']}")
    print(f"Tasks: {[t.id for t in probe_tasks]}")
    print(f"{'='*70}")
    print(f"  {'Task':<18}", end="")
    for temp in TEMP_SWEEP_VALUES:
        print(f"  T={temp:.1f}", end="")
    print()
    print(f"  {'-'*18}", end="")
    for _ in TEMP_SWEEP_VALUES:
        print(f"  -----", end="")
    print()

    sweep_results: dict[float, list[bool]] = {t: [] for t in TEMP_SWEEP_VALUES}

    for task in probe_tasks:
        print(f"  {task.id:<18}", end="", flush=True)
        for temp in TEMP_SWEEP_VALUES:
            cfg["temperature"] = temp
            r = run_task(task, model_key)
            sweep_results[temp].append(r.passed)
            mark = "P" if r.passed else "."
            print(f"  {mark:^5}", end="", flush=True)
        print()

    # Summary row
    print(f"  {'PASS RATE':<18}", end="")
    for temp in TEMP_SWEEP_VALUES:
        passed = sum(sweep_results[temp])
        total = len(sweep_results[temp])
        pct = passed / total * 100
        print(f"  {pct:4.0f}%", end="")
    print()

    # Restore original temperature
    cfg["temperature"] = original_temp

    # Save sweep data
    output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = output_dir / f"temp_sweep_{model_key}_{ts}.json"
    data = {
        "timestamp": datetime.now().isoformat(),
        "model_key": model_key,
        "model_label": cfg["label"],
        "task_ids": [t.id for t in probe_tasks],
        "temperatures": TEMP_SWEEP_VALUES,
        "results": {
            str(temp): {"passed": sum(v), "total": len(v), "pct": sum(v) / len(v) * 100}
            for temp, v in sweep_results.items()
        },
    }
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nSweep salvo: {out}")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark qualidade/velocidade modelos locais",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Exemplos:
              python bench.py                        # ollama + llama (original)
              python bench.py --model gemma4         # so Gemma 4
              python bench.py --all                  # todos os 3 modelos
              python bench.py --temp-sweep ollama    # sweep de temperatura (ollama)
              python bench.py --category algo data   # filtra categorias
        """),
    )
    parser.add_argument("--model", choices=["ollama", "llama", "gemma4", "qwen36", "both"], default="both",
                        help="Modelo a usar (default: both = ollama+llama)")
    parser.add_argument("--all", action="store_true", dest="run_all",
                        help="Roda os 3 modelos: ollama, llama, gemma4")
    parser.add_argument("--category", nargs="*", help="Filtra por categoria(s)")
    parser.add_argument("--temp-sweep", metavar="MODEL_KEY", dest="temp_sweep",
                        choices=["ollama", "llama", "gemma4", "qwen36"],
                        help="Sweep de temperatura para o modelo especificado")
    args = parser.parse_args()

    if args.temp_sweep:
        run_temp_sweep(args.temp_sweep)
        return

    if args.run_all:
        model_keys = ["ollama", "llama", "gemma4"]
    elif args.model == "both":
        model_keys = ["ollama", "llama"]
    else:
        model_keys = [args.model]

    results = run_benchmark(model_keys, args.category)
    save_results(results, Path(__file__).parent / "results")

    # Cross-model comparison matrix when multiple models ran
    if len(model_keys) > 1:
        print(f"\n{'='*70}")
        print("MATRIX DE COMPARACAO")
        print(f"{'='*70}")
        header = f"  {'Task':<18}  {'Cat':<10}  {'Diff':<12}"
        for mk in model_keys:
            label = MODELS[mk]["label"].split("(")[0].strip()[:14]
            header += f"  {label:<14}"
        print(header)
        print(f"  {'-'*18}  {'-'*10}  {'-'*12}" + f"  {'-'*14}" * len(model_keys))
        for task in TASKS:
            if args.category and task.category not in args.category:
                continue
            row = f"  {task.id:<18}  {task.category:<10}  {task.difficulty:<12}"
            for mk in model_keys:
                match = next((r for r in results if r.task_id == task.id and r.model_key == mk), None)
                if match:
                    mark = "PASS" if match.passed else "FAIL"
                    row += f"  {mark:<14}"
                else:
                    row += f"  {'N/A':<14}"
            print(row)

        # Per-model totals
        print(f"\n  {'TOTAL':<18}  {'':10}  {'':12}", end="")
        for mk in model_keys:
            mrs = [r for r in results if r.model_key == mk]
            p = sum(1 for r in mrs if r.passed)
            pct = p / len(mrs) * 100 if mrs else 0
            summary = f"{p}/{len(mrs)} ({pct:.0f}%)"
            print(f"  {summary:<14}", end="")
        print()


if __name__ == "__main__":
    main()
