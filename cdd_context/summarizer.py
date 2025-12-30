"""
Summarizer: Generates concise summaries of source files.

Contract: summarizer v1.0.0
"""

import ast
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Constants from spec
MAX_BYTES_PER_FILE_FOR_LLM = 200_000
MAX_SUMMARY_CHARS = 500
BINARY_DETECTION_BYTES = 8192

# Current prompt version
SUMMARIZATION_PROMPT = """Analyze this source file and provide a JSON response with:
- summary: 2-5 sentence description (max 500 chars)
- role: one of entrypoint|config|library|test|docs|asset|unknown
- public_symbols: list of exported/public function/class names
- import_deps: list of imported modules
- provides: what this file exports/provides
- consumes: what external things this file uses

File path: {path}
Content:
{content}

Respond with only valid JSON, no markdown fences or other text."""

PROMPT_HASH = hashlib.sha256(SUMMARIZATION_PROMPT.encode()).hexdigest()[:16]
BACKEND_ID = "claude:haiku"
TOOL_VERSION = "0.3.0"

# Tier A patterns - cause file exclusion
TIER_A_PATTERNS = [
    rb"-----BEGIN [\w\s]* PRIVATE KEY-----",
    rb"-----BEGIN RSA PRIVATE KEY-----",
    rb"-----BEGIN EC PRIVATE KEY-----",
    rb"-----BEGIN OPENSSH PRIVATE KEY-----",
    rb"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    rb"-----BEGIN ENCRYPTED PRIVATE KEY-----",
]

# Tier B - variable names that suggest secrets
TIER_B_VARIABLE_PATTERN = re.compile(
    r'\b(token|secret|password|passwd|auth|bearer|credential|'
    r'api[_-]?key|private[_-]?key|secret[_-]?key|access[_-]?token)\b',
    re.IGNORECASE
)


@dataclass
class SummaryResult:
    """Output from summarize_file()."""
    summary: str = ""
    role: str = "unknown"
    public_symbols: list[str] = field(default_factory=list)
    public_symbols_count: int = 0
    import_deps: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    entrypoints: list[dict] = field(default_factory=list)
    entrypoints_count: int = 0
    excluded: bool = False
    exclusion_reason: Optional[str] = None
    redaction_count: int = 0
    is_binary: bool = False
    decode_lossy: bool = False
    
    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "role": self.role,
            "public_symbols": self.public_symbols,
            "public_symbols_count": len(self.public_symbols),
            "import_deps": self.import_deps,
            "provides": self.provides,
            "consumes": self.consumes,
            "entrypoints": self.entrypoints,
            "entrypoints_count": len(self.entrypoints),
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "redaction_count": self.redaction_count,
            "is_binary": self.is_binary,
            "decode_lossy": self.decode_lossy,
        }


def _is_binary(content: bytes) -> bool:
    """Check if content is binary (contains NUL in first N bytes)."""
    check_bytes = content[:BINARY_DETECTION_BYTES]
    return b"\x00" in check_bytes


def _has_tier_a_secret(content: bytes) -> bool:
    """Check for Tier A secrets (private key blocks)."""
    for pattern in TIER_A_PATTERNS:
        if re.search(pattern, content):
            return True
    return False


def _redact_tier_b_secrets(text: str) -> tuple[str, int]:
    """
    Redact Tier B secrets (suspicious variable assignments).
    Returns (redacted_text, redaction_count).
    """
    count = 0
    lines = text.split('\n')
    result_lines = []
    
    for line in lines:
        # Check for suspicious variable names
        if TIER_B_VARIABLE_PATTERN.search(line):
            # Look for string literal assignments
            # Patterns: VAR = "...", VAR: "...", VAR => "..."
            redacted = re.sub(
                r'(["\'])(?:(?!\1).)*\1',
                '"[REDACTED]"',
                line
            )
            if redacted != line:
                count += 1
                line = redacted
        result_lines.append(line)
    
    return '\n'.join(result_lines), count


def _classify_role(path: str, content: str) -> str:
    """Classify file role based on path and content."""
    filename = Path(path).name.lower()
    
    # Test files
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return "test"
    if "/tests/" in path or "/test/" in path:
        return "test"
    
    # Config files
    config_patterns = [
        "config.", "settings.", ".yaml", ".yml", ".toml", ".json", ".ini",
        "dockerfile", "makefile", ".env", "pyproject.toml", "package.json",
        "cargo.toml", "go.mod"
    ]
    for pattern in config_patterns:
        if pattern in filename:
            return "config"
    
    # Documentation
    doc_patterns = [".md", ".rst", ".txt", "readme", "changelog", "license"]
    for pattern in doc_patterns:
        if pattern in filename:
            return "docs"
    
    # Entrypoint detection
    if "if __name__" in content:
        return "entrypoint"
    if filename in ["main.py", "app.py", "index.py", "__main__.py"]:
        return "entrypoint"
    if filename in ["main.js", "index.js", "app.js"]:
        return "entrypoint"
    
    # Default to library
    if filename.endswith((".py", ".js", ".ts", ".go", ".rs", ".scala", ".sc")):
        return "library"
    
    return "unknown"


def _extract_python_info(content: str) -> dict:
    """Extract info from Python file using AST."""
    result = {
        "public_symbols": [],
        "import_deps": [],
        "docstring": None,
        "entrypoints": [],
    }
    
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return result
    
    # Module docstring
    if (tree.body and isinstance(tree.body[0], ast.Expr) and
            isinstance(tree.body[0].value, ast.Constant) and
            isinstance(tree.body[0].value.value, str)):
        result["docstring"] = tree.body[0].value.value[:200]
    
    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["import_deps"].append(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["import_deps"].append(node.module.split('.')[0])
        
        # Public functions/classes (not starting with _)
        elif isinstance(node, ast.FunctionDef):
            if not node.name.startswith('_'):
                result["public_symbols"].append(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            if not node.name.startswith('_'):
                result["public_symbols"].append(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith('_'):
                result["public_symbols"].append(node.name)
    
    # Check for if __name__ == "__main__"
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            try:
                if (isinstance(node.test, ast.Compare) and
                        isinstance(node.test.left, ast.Name) and
                        node.test.left.id == "__name__"):
                    # Find line number
                    result["entrypoints"].append({
                        "path": "",  # Will be filled in
                        "lineno": node.lineno,
                        "evidence": 'if __name__ == "__main__"',
                        "confidence": 0.95,
                    })
            except AttributeError:
                pass
    
    # Dedupe
    result["import_deps"] = sorted(set(result["import_deps"]))
    
    return result


def _heuristic_summary(path: str, content: str) -> SummaryResult:
    """Generate summary using heuristics (no LLM)."""
    result = SummaryResult()
    result.role = _classify_role(path, content)
    
    filename = Path(path).name
    ext = Path(path).suffix.lower()
    
    # Python-specific extraction
    if ext == ".py":
        info = _extract_python_info(content)
        result.public_symbols = info["public_symbols"]
        result.import_deps = info["import_deps"]
        result.entrypoints = info["entrypoints"]
        for ep in result.entrypoints:
            ep["path"] = path
        
        # Build summary from docstring or structure
        if info["docstring"]:
            result.summary = info["docstring"][:MAX_SUMMARY_CHARS]
        else:
            parts = []
            if result.public_symbols:
                parts.append(f"Defines: {', '.join(result.public_symbols[:5])}")
            if result.import_deps:
                parts.append(f"Imports: {', '.join(result.import_deps[:5])}")
            result.summary = ". ".join(parts) if parts else f"Python file: {filename}"
    
    # JavaScript/TypeScript
    elif ext in [".js", ".ts", ".jsx", ".tsx"]:
        # Simple regex-based extraction
        exports = re.findall(r'export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)', content)
        imports = re.findall(r'import\s+.*?from\s+["\']([^"\']+)["\']', content)
        result.public_symbols = exports[:10]
        result.import_deps = [i.split('/')[0] for i in imports]
        result.summary = f"JavaScript/TypeScript file with {len(exports)} exports"
    
    # YAML/JSON config
    elif ext in [".yaml", ".yml", ".json"]:
        result.summary = f"Configuration file: {filename}"
    
    # Markdown docs
    elif ext == ".md":
        # Extract first heading
        heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if heading:
            result.summary = f"Documentation: {heading.group(1)}"
        else:
            result.summary = f"Markdown documentation: {filename}"
    
    # Generic fallback
    else:
        lines = len(content.splitlines())
        result.summary = f"{filename}: {lines} lines"
    
    # Ensure summary length limit
    if len(result.summary) > MAX_SUMMARY_CHARS:
        result.summary = result.summary[:MAX_SUMMARY_CHARS - 3] + "..."
    
    return result


def summarize_file(
    path: str,
    use_llm: bool = True,
    api_key: Optional[str] = None,
) -> dict:
    """
    Summarize a source file.
    
    Args:
        path: Path to source file
        use_llm: Whether to use LLM (False for heuristic fallback)
        api_key: Anthropic API key (uses env var if not provided)
    
    Returns:
        Summary dict matching output_schema
    """
    path_obj = Path(path)
    
    if not path_obj.exists():
        result = SummaryResult()
        result.excluded = True
        result.exclusion_reason = "file_not_found"
        result.summary = f"File not found: {path}"
        return result.to_dict()
    
    # Read raw bytes for binary/secret detection
    try:
        raw_content = path_obj.read_bytes()
    except Exception as e:
        result = SummaryResult()
        result.excluded = True
        result.exclusion_reason = "read_error"
        result.summary = f"Could not read file: {e}"
        return result.to_dict()
    
    result = SummaryResult()
    
    # Check binary (R001)
    if _is_binary(raw_content):
        result.is_binary = True
        result.excluded = True
        result.exclusion_reason = "binary_file"
        result.summary = f"Binary file: {path_obj.name}"
        return result.to_dict()
    
    # Check file size (R001)
    if len(raw_content) > MAX_BYTES_PER_FILE_FOR_LLM:
        result.excluded = True
        result.exclusion_reason = "file_too_large"
        # Still try heuristic summary
        try:
            text = raw_content.decode("utf-8", errors="replace")
            result.decode_lossy = True
            heuristic = _heuristic_summary(path, text)
            result.summary = heuristic.summary
            result.role = heuristic.role
            result.public_symbols = heuristic.public_symbols
            result.import_deps = heuristic.import_deps
        except Exception:
            result.summary = f"Large file: {path_obj.name} ({len(raw_content)} bytes)"
        return result.to_dict()
    
    # Check for Tier A secrets (R006)
    if _has_tier_a_secret(raw_content):
        result.excluded = True
        result.exclusion_reason = "private_key_block"
        result.summary = f"File excluded: contains private key"
        return result.to_dict()
    
    # Decode text
    try:
        text = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_content.decode("utf-8", errors="replace")
        result.decode_lossy = True
    
    # Tier B redaction (R006)
    redacted_text, redaction_count = _redact_tier_b_secrets(text)
    result.redaction_count = redaction_count
    
    # Generate summary
    if use_llm and api_key:
        # TODO: Implement LLM call
        # For now, fall back to heuristic
        pass
    
    # Heuristic fallback (R003)
    heuristic = _heuristic_summary(path, text)
    result.summary = heuristic.summary
    result.role = heuristic.role
    result.public_symbols = heuristic.public_symbols
    result.import_deps = heuristic.import_deps
    result.entrypoints = heuristic.entrypoints
    result.provides = heuristic.provides
    result.consumes = heuristic.consumes
    
    return result.to_dict()


def get_prompt_hash() -> str:
    """Get hash of current summarization prompt."""
    return PROMPT_HASH


def get_backend_id() -> str:
    """Get current backend identifier."""
    return BACKEND_ID


def get_tool_version() -> str:
    """Get current tool version."""
    return TOOL_VERSION
