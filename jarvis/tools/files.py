"""Outils fichiers : lister, lire, ecrire, chercher, copier, deplacer, supprimer."""

from __future__ import annotations

import fnmatch
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from ..osutils import home_folders, resolve_path
from . import ToolError, tool

TEXT_EXT = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css", ".xml", ".yml", ".yaml", ".ini",
    ".cfg", ".log", ".bat", ".ps1", ".sh", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php", ".rb",
    ".sql", ".toml", ".env", ".srt", ".tex", ".rtf", ".kt", ".swift", ".vue", ".jsx", ".tsx",
}

PROTECTED = [
    Path(p).resolve() for p in (
        os.environ.get("SystemRoot", "C:/Windows"), "C:/Program Files", "C:/Program Files (x86)",
        "/System", "/usr", "/bin", "/sbin", "/etc", "/boot", "/lib", "/var/lib",
    )
]


def _check_writable(p: Path) -> None:
    for prot in PROTECTED:
        try:
            if p == prot or p.is_relative_to(prot):
                raise ToolError(f"Par securite, JARVIS ne modifie pas les fichiers systeme ({prot}).")
        except ValueError:
            continue
    if p == Path(p.anchor) or p == Path.home():
        raise ToolError("Operation refusee sur un dossier racine.")


def _human(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"


@tool(
    "list_directory",
    "Liste le contenu d'un dossier (nom, type, taille, date). Raccourcis acceptes : bureau, documents, "
    "telechargements, images, musique, videos, ~.",
    {
        "path": {"type": "string", "description": "Dossier, ex: 'telechargements' ou 'C:/Projets'."},
        "pattern": {"type": "string", "description": "Filtre glob optionnel, ex: '*.pdf'."},
        "sort_by": {"type": "string", "enum": ["name", "date", "size"]},
        "limit": {"type": "integer", "description": "Max d'elements (defaut 60)."},
    },
    required=["path"],
    category="fichiers",
)
def list_directory(path: str, pattern: str = "*", sort_by: str = "name", limit: int = 60) -> dict:
    p = resolve_path(path)
    if not p.is_dir():
        raise ToolError(f"Dossier introuvable : {p}")
    entries = []
    for child in p.iterdir():
        if not fnmatch.fnmatch(child.name.lower(), (pattern or "*").lower()):
            continue
        try:
            st = child.stat()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "type": "dossier" if child.is_dir() else "fichier",
            "size": _human(st.st_size) if child.is_file() else "",
            "_size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "_mtime": st.st_mtime,
        })
    key = {"date": "_mtime", "size": "_size"}.get(sort_by, "name")
    entries.sort(key=lambda e: e[key] if key != "name" else e["name"].lower(), reverse=key != "name")
    total = len(entries)
    for e in entries:
        e.pop("_size")
        e.pop("_mtime")
    return {"path": str(p), "total": total, "entries": entries[: max(1, min(limit, 500))]}


@tool(
    "read_file",
    "Lit le contenu texte d'un fichier (txt, md, code, csv, json...) ou d'un PDF / DOCX.",
    {
        "path": {"type": "string"},
        "max_chars": {"type": "integer", "description": "Nombre max de caracteres (defaut 20000)."},
    },
    required=["path"],
    category="fichiers",
)
def read_file(path: str, max_chars: int = 20000) -> str:
    p = resolve_path(path)
    if not p.is_file():
        raise ToolError(f"Fichier introuvable : {p}")
    max_chars = max(500, min(max_chars, 200_000))
    ext = p.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError as exc:
            raise ToolError("Module pypdf non installe pour lire les PDF.") from exc
        reader = PdfReader(str(p))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:200])
    elif ext == ".docx":
        import re
        import zipfile

        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<w:p[ >].*?</w:p>", lambda m: re.sub(r"<[^>]+>", "", m.group(0)) + "\n", xml, flags=re.S)
        text = re.sub(r"<[^>]+>", "", text)
    else:
        if ext not in TEXT_EXT and p.stat().st_size > 2_000_000:
            raise ToolError("Fichier binaire ou trop volumineux.")
        text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...[tronque, {len(text)} caracteres au total]"
    return text


def _write_risk(args: dict) -> str:
    try:
        return "danger" if resolve_path(args.get("path", "")).exists() and args.get("mode", "overwrite") == "overwrite" else "action"
    except (OSError, ValueError):
        return "danger"


@tool(
    "write_file",
    "Cree ou modifie un fichier texte (note, script, document markdown, CSV...). Mode 'overwrite' remplace "
    "le contenu, 'append' ajoute a la fin. Les dossiers parents sont crees si besoin.",
    {
        "path": {"type": "string", "description": "Chemin, ex: 'bureau/liste_courses.txt'."},
        "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["overwrite", "append"]},
    },
    required=["path", "content"],
    risk=_write_risk,
    category="fichiers",
    confirm=lambda a: f"Ecraser le fichier existant « {a.get('path')} » ?",
)
def write_file(path: str, content: str, mode: str = "overwrite") -> str:
    p = resolve_path(path)
    _check_writable(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
    else:
        p.write_text(content, encoding="utf-8")
    return f"Fichier enregistre : {p} ({_human(p.stat().st_size)})"


@tool(
    "search_files",
    "Recherche des fichiers par nom (et optionnellement par contenu texte) dans les dossiers personnels "
    "(bureau, documents, telechargements...) ou dans un dossier donne.",
    {
        "query": {"type": "string", "description": "Texte contenu dans le nom du fichier (ou motif glob)."},
        "root": {"type": "string", "description": "Dossier de depart (defaut : dossiers personnels)."},
        "extensions": {"type": "array", "items": {"type": "string"}, "description": "Ex: ['.pdf', '.docx']."},
        "content_search": {"type": "boolean", "description": "Chercher aussi dans le contenu des fichiers texte."},
        "max_results": {"type": "integer"},
    },
    required=["query"],
    category="fichiers",
)
def search_files(query: str, root: str = "", extensions: list | None = None, content_search: bool = False,
                 max_results: int = 30) -> dict:
    roots = [resolve_path(root)] if root else [
        Path(home_folders()[k]) for k in ("bureau", "documents", "telechargements", "images", "musique", "videos")
    ]
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in (extensions or [])}
    q = query.lower()
    is_glob = any(c in q for c in "*?[")
    results: list[dict] = []
    deadline = time.time() + 25
    skip_dirs = {"node_modules", ".git", "__pycache__", "appdata", "$recycle.bin", ".cache", "venv", ".venv", "library"}
    for base in roots:
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_dirs and not d.startswith(".")]
            for fn in filenames:
                low = fn.lower()
                if exts and Path(low).suffix not in exts:
                    continue
                match = fnmatch.fnmatch(low, q) if is_glob else q in low
                full = Path(dirpath) / fn
                if not match and content_search and Path(low).suffix in TEXT_EXT:
                    try:
                        if full.stat().st_size < 2_000_000:
                            match = q in full.read_text(encoding="utf-8", errors="ignore").lower()
                    except OSError:
                        pass
                if match:
                    try:
                        st = full.stat()
                        results.append({"path": str(full), "size": _human(st.st_size),
                                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
                    except OSError:
                        continue
                    if len(results) >= max_results:
                        return {"results": results, "truncated": True}
            if time.time() > deadline:
                return {"results": results, "truncated": True, "note": "recherche interrompue (delai)"}
    return {"results": results, "truncated": False}


@tool(
    "file_operation",
    "Operations sur fichiers/dossiers : copier, deplacer, renommer, creer un dossier, supprimer (vers la corbeille "
    "quand c'est possible).",
    {
        "action": {"type": "string", "enum": ["copy", "move", "rename", "mkdir", "delete"]},
        "path": {"type": "string", "description": "Fichier/dossier source (ou dossier a creer)."},
        "destination": {"type": "string", "description": "Destination (copy/move) ou nouveau nom (rename)."},
    },
    required=["action", "path"],
    risk=lambda a: "danger" if a.get("action") in ("delete", "move") else "action",
    category="fichiers",
    confirm=lambda a: {
        "delete": f"Supprimer « {a.get('path')} » ?",
        "move": f"Deplacer « {a.get('path')} » vers « {a.get('destination')} » ?",
    }.get(a.get("action"), f"{a.get('action')} « {a.get('path')} » ?"),
)
def file_operation(action: str, path: str, destination: str = "") -> str:
    src = resolve_path(path)
    if action == "mkdir":
        _check_writable(src)
        src.mkdir(parents=True, exist_ok=True)
        return f"Dossier cree : {src}"
    if not src.exists():
        raise ToolError(f"Introuvable : {src}")
    _check_writable(src)
    if action == "delete":
        try:
            from send2trash import send2trash  # type: ignore

            send2trash(str(src))
            return f"{src.name} envoye a la corbeille."
        except ImportError:
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
            return f"{src.name} supprime definitivement."
    if not destination:
        raise ToolError("Parametre 'destination' requis.")
    if action == "rename":
        dst = src.with_name(destination)
    else:
        dst = resolve_path(destination)
        if dst.is_dir():
            dst = dst / src.name
    _check_writable(dst)
    if dst.exists():
        raise ToolError(f"La destination existe deja : {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if action == "copy":
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
        return f"Copie : {dst}"
    shutil.move(str(src), str(dst))
    return f"{'Renomme' if action == 'rename' else 'Deplace'} : {dst}"
