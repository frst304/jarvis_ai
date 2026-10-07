"""Outils d'execution : commandes shell, scripts Python, calculatrice securisee."""

from __future__ import annotations

import ast
import math
import operator
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import IS_WINDOWS
from ..osutils import CREATE_NO_WINDOW
from . import ToolError, tool


def _clip(text: str, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[{len(text) - limit} caracteres tronques]"


@tool(
    "run_shell_command",
    "Execute une commande dans le terminal du PC (PowerShell sous Windows, bash/zsh sinon) et renvoie la sortie. "
    "Utile pour l'automatisation avancee, l'administration, git, winget/brew/apt, etc. "
    "Toujours expliquer brievement ce que fait la commande.",
    {
        "command": {"type": "string"},
        "cwd": {"type": "string", "description": "Dossier de travail (optionnel)."},
        "timeout": {"type": "integer", "description": "Delai max en secondes (defaut 60, max 600)."},
    },
    required=["command"],
    risk="danger",
    category="automatisation",
    confirm=lambda a: f"Executer la commande : {a.get('command')}",
)
def run_shell_command(command: str, cwd: str = "", timeout: int = 60) -> str:
    timeout = max(1, min(int(timeout or 60), 600))
    if IS_WINDOWS:
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        shell = False
    else:
        args, shell = command, True
    try:
        proc = subprocess.run(
            args, shell=shell, cwd=cwd or None, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Commande interrompue apres {timeout}s.") from exc
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    result = f"code retour: {proc.returncode}\n"
    if out:
        result += f"--- sortie ---\n{_clip(out)}\n"
    if err:
        result += f"--- erreurs ---\n{_clip(err, 4000)}\n"
    return result.strip()


@tool(
    "run_python",
    "Execute un script Python sur le PC (calculs complexes, traitement de fichiers, automatisation, graphiques "
    "enregistres en image...). Renvoie stdout/stderr. Les modules installes dans l'environnement de JARVIS sont "
    "disponibles.",
    {
        "code": {"type": "string"},
        "timeout": {"type": "integer", "description": "Delai max en secondes (defaut 60)."},
    },
    required=["code"],
    risk="danger",
    category="automatisation",
    confirm=lambda a: "Executer ce script Python ?\n" + (a.get("code") or "")[:600],
)
def run_python(code: str, timeout: int = 60) -> str:
    timeout = max(1, min(int(timeout or 60), 600))
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "jarvis_script.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW, cwd=str(Path.home()),
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Script interrompu apres {timeout}s.") from exc
    result = f"code retour: {proc.returncode}\n"
    if proc.stdout.strip():
        result += f"--- sortie ---\n{_clip(proc.stdout.strip())}\n"
    if proc.stderr.strip():
        result += f"--- erreurs ---\n{_clip(proc.stderr.strip(), 4000)}\n"
    return result.strip()


# ------------------------------------------------------------ Calculatrice securisee

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    name: getattr(math, name) for name in (
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "log", "log10", "log2", "exp", "floor",
        "ceil", "factorial", "radians", "degrees", "hypot", "gcd", "comb", "perm", "sinh", "cosh", "tanh",
    )
}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def safe_eval(expression: str) -> float | int:
    expr = expression.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", ".")
    expr = expr.replace("racine", "sqrt")
    tree = ast.parse(expr, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10000:
                raise ToolError("Exposant trop grand.")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        raise ToolError("Expression non autorisee.")

    return ev(tree)


@tool(
    "calculate",
    "Calculatrice exacte : expressions mathematiques (+ - * / ** % sqrt sin cos log factorial pi e...). "
    "A utiliser pour tout calcul numerique precis.",
    {"expression": {"type": "string", "description": "Ex: '(1250*1.2)/7', 'sqrt(2)*pi', '15% de 80' -> '0.15*80'."}},
    required=["expression"],
    category="outils",
)
def calculate(expression: str) -> str:
    try:
        value = safe_eval(expression)
    except ToolError:
        raise
    except ZeroDivisionError as exc:
        raise ToolError("Division par zero.") from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Expression invalide : {exc}") from exc
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            value = int(value)
        else:
            value = round(value, 10)
    return f"{expression} = {value}"
