#!/usr/bin/env python3
"""
Pattern Analyzer — Dev Team Helper Script

Analyzes a codebase to discover and document coding patterns:
  - Naming conventions (files, functions, classes, variables)
  - File organization patterns
  - Import/dependency patterns
  - Error handling patterns
  - Test patterns
  - Common idioms

Outputs a JSON pattern library suitable for .dev-team/patterns.json
"""

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.next', 'dist', 'build',
    'venv', '.venv', 'env', 'coverage', 'vendor', '.terraform',
}

SKIP_EXTENSIONS = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.bin'}


# ─── Python Analysis ──────────────────────────────────────────────────────────

def analyze_python_file(path: Path) -> dict:
    """Extract patterns from a Python file using AST analysis."""
    try:
        source = path.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(source)
    except Exception:
        return {}

    patterns = {
        'functions': [],
        'classes': [],
        'imports': [],
        'decorators': [],
        'error_handling': [],
        'docstring_style': None,
    }

    for node in ast.walk(tree):
        # Functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            patterns['functions'].append({
                'name': node.name,
                'is_async': isinstance(node, ast.AsyncFunctionDef),
                'has_return_annotation': node.returns is not None,
                'has_docstring': (
                    isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, ast.Constant) and
                    isinstance(node.body[0].value.value, str)
                ) if node.body else False,
                'decorators': [
                    ast.unparse(d) if hasattr(ast, 'unparse') else d.id
                    for d in node.decorator_list
                    if isinstance(d, ast.Name)
                ],
            })

        # Classes
        elif isinstance(node, ast.ClassDef):
            patterns['classes'].append({
                'name': node.name,
                'bases': [
                    ast.unparse(b) if hasattr(ast, 'unparse') else ''
                    for b in node.bases
                ],
            })

        # Imports
        elif isinstance(node, ast.Import):
            for alias in node.names:
                patterns['imports'].append({'type': 'import', 'module': alias.name})

        elif isinstance(node, ast.ImportFrom):
            patterns['imports'].append({
                'type': 'from',
                'module': node.module or '',
                'level': node.level,  # relative import level
            })

        # Try/except patterns
        elif isinstance(node, ast.Try):
            handler_types = []
            for handler in node.handlers:
                if handler.type:
                    handler_types.append(
                        ast.unparse(handler.type) if hasattr(ast, 'unparse') else 'Exception'
                    )
            patterns['error_handling'].append({'handler_types': handler_types})

    # Detect docstring style
    docstrings = re.findall(r'"""[\s\S]*?"""', source)
    if docstrings:
        sample = docstrings[0] if docstrings else ''
        if 'Args:' in sample or 'Returns:' in sample:
            patterns['docstring_style'] = 'google'
        elif ':param ' in sample or ':type ' in sample:
            patterns['docstring_style'] = 'sphinx'
        elif 'Parameters\n' in sample or '----------' in sample:
            patterns['docstring_style'] = 'numpy'
        else:
            patterns['docstring_style'] = 'plain'

    return patterns


# ─── TypeScript/JavaScript Analysis ───────────────────────────────────────────

def analyze_ts_js_file(path: Path) -> dict:
    """Extract patterns from TypeScript/JavaScript using regex analysis."""
    try:
        source = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return {}

    patterns = {
        'functions': [],
        'classes': [],
        'imports': [],
        'exports': [],
        'error_handling': [],
    }

    # Function patterns
    func_patterns = [
        r'(?:export\s+)?(?:async\s+)?function\s+(\w+)',
        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(',
        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?(?:\w+|\([^)]*\))\s*=>',
    ]
    for pattern in func_patterns:
        for match in re.finditer(pattern, source):
            patterns['functions'].append({'name': match.group(1)})

    # Class patterns
    for match in re.finditer(r'(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?', source):
        patterns['classes'].append({
            'name': match.group(1),
            'extends': match.group(2),
        })

    # Import patterns
    for match in re.finditer(r"import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", source):
        imported = match.group(1).strip()
        module = match.group(2)
        patterns['imports'].append({
            'imported': imported,
            'from': module,
            'is_relative': module.startswith('.'),
            'is_type': 'type' in imported,
        })

    # Export patterns
    for match in re.finditer(r'export\s+(?:default\s+)?(?:const|class|function|type|interface)\s+(\w+)', source):
        patterns['exports'].append({'name': match.group(1)})

    # Try/catch patterns
    patterns['error_handling'] = [
        {'pattern': 'try/catch'}
        for _ in re.finditer(r'try\s*\{', source)
    ]

    return patterns


# ─── Naming Convention Detection ──────────────────────────────────────────────

def detect_naming_convention(names: list[str]) -> str:
    """Detect the predominant naming convention from a list of names."""
    if not names:
        return 'unknown'

    scores = Counter()
    for name in names:
        if not name or len(name) < 2:
            continue
        if re.match(r'^[a-z][a-zA-Z0-9]*$', name) and re.search(r'[A-Z]', name):
            scores['camelCase'] += 1
        elif re.match(r'^[A-Z][a-zA-Z0-9]*$', name):
            scores['PascalCase'] += 1
        elif re.match(r'^[a-z][a-z0-9_]*$', name) and '_' in name:
            scores['snake_case'] += 1
        elif re.match(r'^[A-Z][A-Z0-9_]*$', name) and '_' in name:
            scores['SCREAMING_SNAKE_CASE'] += 1
        elif re.match(r'^[a-z][a-z0-9-]*$', name) and '-' in name:
            scores['kebab-case'] += 1

    return scores.most_common(1)[0][0] if scores else 'mixed'


# ─── File Pattern Analysis ─────────────────────────────────────────────────────

def analyze_file_naming(files: list[Path]) -> dict:
    """Analyze file naming patterns."""
    names = [f.stem for f in files if f.suffix in {'.ts', '.tsx', '.js', '.jsx', '.py'}]

    # Detect test file naming
    test_files = [f for f in files if any(x in f.name for x in ['test', 'spec'])]
    test_pattern = None
    if test_files:
        sample = test_files[0].name
        if '.test.' in sample:
            test_pattern = '<name>.test.<ext>'
        elif '.spec.' in sample:
            test_pattern = '<name>.spec.<ext>'
        elif sample.startswith('test_'):
            test_pattern = 'test_<name>.<ext>'
        elif sample.endswith('_test.py'):
            test_pattern = '<name>_test.py'

    # Detect component/module file placement
    has_index = any(f.name.startswith('index.') for f in files)

    return {
        'naming_convention': detect_naming_convention(names),
        'test_file_pattern': test_pattern,
        'uses_index_files': has_index,
        'file_count': len(files),
    }


# ─── Main Analysis ─────────────────────────────────────────────────────────────

def collect_all_files(root: Path) -> list[Path]:
    """Collect all relevant source files."""
    files = []
    for path in root.rglob('*'):
        if path.is_file():
            parts = path.parts
            if any(part in SKIP_DIRS for part in parts):
                continue
            if path.suffix.lower() in SKIP_EXTENSIONS:
                continue
            files.append(path)
    return files


def aggregate_python_patterns(root: Path, py_files: list[Path]) -> dict:
    """Aggregate Python patterns across all files."""
    all_func_names = []
    all_class_names = []
    all_imports = []
    docstring_styles = Counter()
    has_type_hints = 0
    uses_async = 0
    error_patterns = []

    for path in py_files[:50]:  # Analyze up to 50 files
        result = analyze_python_file(path)
        for f in result.get('functions', []):
            all_func_names.append(f['name'])
            if f.get('has_return_annotation'):
                has_type_hints += 1
            if f.get('is_async'):
                uses_async += 1
        for c in result.get('classes', []):
            all_class_names.append(c['name'])
        all_imports.extend(result.get('imports', []))
        if result.get('docstring_style'):
            docstring_styles[result['docstring_style']] += 1
        error_patterns.extend(result.get('error_handling', []))

    # Top external imports
    external_imports = Counter(
        imp['module'].split('.')[0]
        for imp in all_imports
        if imp['type'] == 'import' or (imp['type'] == 'from' and imp.get('level', 0) == 0)
    )

    return {
        'function_naming': detect_naming_convention(all_func_names),
        'class_naming': detect_naming_convention(all_class_names),
        'docstring_style': docstring_styles.most_common(1)[0][0] if docstring_styles else 'none',
        'uses_type_hints': has_type_hints > len(py_files) * 0.3,
        'uses_async': uses_async > 0,
        'top_dependencies': [dep for dep, _ in external_imports.most_common(10)],
        'uses_relative_imports': any(
            imp.get('level', 0) > 0 for imp in all_imports
        ),
        'error_handling_count': len(error_patterns),
    }


def aggregate_ts_patterns(root: Path, ts_files: list[Path]) -> dict:
    """Aggregate TypeScript/JavaScript patterns."""
    all_func_names = []
    all_class_names = []
    all_imports = []
    relative_import_count = 0
    total_imports = 0

    for path in ts_files[:50]:
        result = analyze_ts_js_file(path)
        for f in result.get('functions', []):
            all_func_names.append(f['name'])
        for c in result.get('classes', []):
            all_class_names.append(c['name'])
        for imp in result.get('imports', []):
            all_imports.append(imp)
            total_imports += 1
            if imp.get('is_relative'):
                relative_import_count += 1

    # Top external imports
    external_mods = Counter(
        imp['from'].split('/')[0].lstrip('@').split('/')[0]
        if not imp['from'].startswith('.')
        else None
        for imp in all_imports
    )
    del external_mods[None]

    return {
        'function_naming': detect_naming_convention(all_func_names),
        'class_naming': detect_naming_convention(all_class_names),
        'prefers_relative_imports': relative_import_count > total_imports * 0.5 if total_imports > 0 else None,
        'top_dependencies': [dep for dep, _ in external_mods.most_common(10)],
    }


def detect_test_patterns(files: list[Path]) -> dict:
    """Analyze testing patterns."""
    test_files = [
        f for f in files
        if any(x in f.name.lower() for x in ['.test.', '.spec.', 'test_', '_test.'])
    ]

    if not test_files:
        return {'has_tests': False}

    # Determine if colocated or in separate directory
    test_dirs = Counter(f.parent.name for f in test_files)
    most_common_dir = test_dirs.most_common(1)[0][0] if test_dirs else ''
    colocated = most_common_dir not in {'tests', 'test', '__tests__', 'spec'}

    # Detect framework from test file content
    framework = 'unknown'
    for test_file in test_files[:5]:
        try:
            content = test_file.read_text(encoding='utf-8', errors='replace')
            if 'import pytest' in content or 'def test_' in content:
                framework = 'pytest'
                break
            elif 'describe(' in content and ('it(' in content or 'test(' in content):
                if '@testing-library' in content or 'render(' in content:
                    framework = 'jest + testing-library'
                else:
                    framework = 'jest' if 'jest' in content.lower() else 'vitest/jest'
                break
            elif 'func Test' in content and 'testing.T' in content:
                framework = 'go test'
                break
            elif 'RSpec' in content or 'describe "' in content:
                framework = 'RSpec'
                break
        except Exception:
            pass

    return {
        'has_tests': True,
        'test_file_count': len(test_files),
        'framework': framework,
        'colocated': colocated,
        'common_location': most_common_dir,
    }


def run_analysis(root: Path) -> dict:
    """Run full pattern analysis on the codebase."""
    print("[ANALYZE] Collecting files...", file=sys.stderr)
    files = collect_all_files(root)

    # Group by type
    py_files = [f for f in files if f.suffix == '.py']
    ts_files = [f for f in files if f.suffix in {'.ts', '.tsx'}]
    js_files = [f for f in files if f.suffix in {'.js', '.jsx', '.mjs'}]
    go_files = [f for f in files if f.suffix == '.go']

    result = {
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'root': str(root.resolve()),
        'file_naming': analyze_file_naming(files),
        'testing': detect_test_patterns(files),
        'languages': {},
    }

    if py_files:
        print(f"[ANALYZE] Analyzing {len(py_files)} Python files...", file=sys.stderr)
        result['languages']['python'] = aggregate_python_patterns(root, py_files)

    if ts_files or js_files:
        all_ts = ts_files + js_files
        print(f"[ANALYZE] Analyzing {len(all_ts)} TypeScript/JavaScript files...", file=sys.stderr)
        result['languages']['typescript'] = aggregate_ts_patterns(root, all_ts)

    if go_files:
        result['languages']['go'] = {
            'file_count': len(go_files),
            'note': 'Go pattern analysis uses file naming; see explore output for details',
        }

    # Generate human-readable summary
    result['summary'] = generate_summary(result)

    return result


def generate_summary(analysis: dict) -> list[str]:
    """Generate a human-readable list of key patterns."""
    patterns = []

    file_naming = analysis.get('file_naming', {})
    if file_naming.get('naming_convention'):
        patterns.append(f"File naming: {file_naming['naming_convention']}")
    if file_naming.get('test_file_pattern'):
        patterns.append(f"Test files: {file_naming['test_file_pattern']}")
    if file_naming.get('uses_index_files'):
        patterns.append("Uses index files for module public APIs")

    testing = analysis.get('testing', {})
    if testing.get('has_tests'):
        loc = "colocated with source" if testing.get('colocated') else f"in {testing.get('common_location', 'tests/')} directory"
        patterns.append(f"Testing: {testing.get('framework', 'unknown')} — tests {loc}")
    else:
        patterns.append("No test files detected")

    for lang, lang_data in analysis.get('languages', {}).items():
        if 'function_naming' in lang_data:
            patterns.append(f"{lang.capitalize()} functions: {lang_data['function_naming']}")
        if 'class_naming' in lang_data:
            patterns.append(f"{lang.capitalize()} classes: {lang_data['class_naming']}")
        if lang_data.get('uses_type_hints'):
            patterns.append(f"{lang.capitalize()}: uses type hints/annotations")
        if lang_data.get('uses_async'):
            patterns.append(f"{lang.capitalize()}: uses async/await")
        if 'docstring_style' in lang_data and lang_data['docstring_style'] != 'none':
            patterns.append(f"{lang.capitalize()} docs: {lang_data['docstring_style']} style docstrings")
        if lang_data.get('top_dependencies'):
            top = ', '.join(lang_data['top_dependencies'][:5])
            patterns.append(f"{lang.capitalize()} key deps: {top}")

    return patterns


def main():
    parser = argparse.ArgumentParser(
        description='Analyze codebase patterns and output a pattern library'
    )
    parser.add_argument('--root', default='.', help='Root directory to analyze (default: .)')
    parser.add_argument('--output', help='Output JSON file (default: stdout)')
    parser.add_argument('--summary', action='store_true', help='Print only the summary')
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    analysis = run_analysis(root)

    if args.summary:
        for pattern in analysis.get('summary', []):
            print(f"  • {pattern}")
        return

    output = json.dumps(analysis, indent=2)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output)
        print(f"[ANALYZE] Pattern library written to {args.output}", file=sys.stderr)

        # Print summary to stderr for immediate feedback
        print("\n[ANALYZE] Key patterns found:", file=sys.stderr)
        for pattern in analysis.get('summary', []):
            print(f"  • {pattern}", file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    main()
