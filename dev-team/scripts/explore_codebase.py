#!/usr/bin/env python3
"""
Codebase Explorer — Dev Team Helper Script

Generates a structured overview of a codebase: directory tree, file type
distribution, entry points, key config files, and a summary suitable for
populating .dev-team/context.md.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

# Files/dirs to always skip
SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.next', '.nuxt', 'dist', 'build',
    '.cache', 'venv', '.venv', 'env', '.env', 'coverage', '.nyc_output',
    'target', '.gradle', '.idea', '.vscode', 'vendor', 'bower_components',
    '.terraform', '.serverless', 'tmp', 'temp', 'logs',
}

SKIP_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib', '.exe', '.bin',
    '.jpg', '.jpeg', '.png', '.gif', '.ico', '.svg', '.woff', '.woff2',
    '.ttf', '.eot', '.mp4', '.mp3', '.zip', '.tar', '.gz', '.lock',
}

# Known entry point patterns
ENTRY_POINTS = {
    'main.py', 'app.py', 'server.py', 'run.py', 'manage.py', 'wsgi.py', 'asgi.py',
    'index.ts', 'index.js', 'main.ts', 'server.ts', 'app.ts',
    'main.go', 'cmd/main.go',
    'Main.java', 'Application.java',
    'main.rs', 'lib.rs',
}

# Known config file patterns
CONFIG_FILES = {
    'package.json', 'pyproject.toml', 'setup.py', 'setup.cfg', 'Cargo.toml',
    'go.mod', 'pom.xml', 'build.gradle', 'Gemfile', 'composer.json',
    '.env.example', '.env.sample', 'config.yaml', 'config.yml', 'config.json',
    'docker-compose.yml', 'docker-compose.yaml', 'Dockerfile',
    'Makefile', 'justfile', 'Taskfile.yaml',
    'tsconfig.json', '.eslintrc.js', '.eslintrc.json', '.prettierrc',
    'jest.config.js', 'jest.config.ts', 'vitest.config.ts', 'pytest.ini',
    '.github/workflows', 'Procfile', 'fly.toml', 'vercel.json',
}

# Language detection by extension
LANG_MAP = {
    '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript (React)',
    '.js': 'JavaScript', '.jsx': 'JavaScript (React)', '.mjs': 'JavaScript (ESM)',
    '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.kt': 'Kotlin',
    '.rb': 'Ruby', '.php': 'PHP', '.cs': 'C#', '.cpp': 'C++', '.c': 'C',
    '.swift': 'Swift', '.dart': 'Dart', '.scala': 'Scala', '.ex': 'Elixir',
    '.sh': 'Shell', '.bash': 'Bash', '.zsh': 'Zsh',
    '.sql': 'SQL', '.prisma': 'Prisma', '.graphql': 'GraphQL', '.gql': 'GraphQL',
    '.yaml': 'YAML', '.yml': 'YAML', '.json': 'JSON', '.toml': 'TOML',
    '.md': 'Markdown', '.rst': 'reStructuredText',
    '.html': 'HTML', '.css': 'CSS', '.scss': 'SCSS', '.sass': 'Sass',
    '.tf': 'Terraform', '.hcl': 'HCL',
}


def build_tree(root: Path, max_depth: int = 4) -> dict:
    """Build a tree structure of the codebase."""
    tree = {'name': root.name, 'type': 'dir', 'children': []}

    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return tree

    for entry in entries:
        if entry.name in SKIP_DIRS or entry.name.startswith('.'):
            # Still include some dotfiles that are important
            if entry.name not in {'.github', '.env.example', '.env.sample', '.eslintrc.js'}:
                continue

        if entry.is_dir():
            if max_depth > 0:
                subtree = build_tree(entry, max_depth - 1)
                tree['children'].append(subtree)
        elif entry.is_file():
            if entry.suffix.lower() not in SKIP_EXTENSIONS:
                tree['children'].append({
                    'name': entry.name,
                    'type': 'file',
                    'size': entry.stat().st_size,
                })

    return tree


def tree_to_string(node: dict, prefix: str = '', is_last: bool = True) -> str:
    """Convert tree dict to a pretty-printed string."""
    connector = '└── ' if is_last else '├── '
    lines = [prefix + connector + node['name']]

    if node['type'] == 'dir' and node.get('children'):
        extension = '    ' if is_last else '│   '
        for i, child in enumerate(node['children']):
            is_child_last = (i == len(node['children']) - 1)
            lines.append(tree_to_string(child, prefix + extension, is_child_last))

    return '\n'.join(lines)


def analyze_file_types(root: Path) -> dict:
    """Count files by language/type."""
    counts = defaultdict(int)
    total = 0

    for path in root.rglob('*'):
        if path.is_file():
            # Skip excluded dirs
            parts = path.parts
            if any(part in SKIP_DIRS or (part.startswith('.') and part not in {'.github'})
                   for part in parts):
                continue

            suffix = path.suffix.lower()
            if suffix in SKIP_EXTENSIONS:
                continue

            lang = LANG_MAP.get(suffix, f'Other ({suffix})' if suffix else 'No extension')
            counts[lang] += 1
            total += 1

    return {'by_language': dict(sorted(counts.items(), key=lambda x: -x[1])), 'total': total}


def find_key_files(root: Path) -> dict:
    """Find important files: entry points, configs, READMEs, etc."""
    found = {
        'entry_points': [],
        'configs': [],
        'readmes': [],
        'ci_cd': [],
        'tests': [],
        'env_examples': [],
    }

    for path in root.rglob('*'):
        if path.is_file():
            parts = path.parts
            if any(part in SKIP_DIRS for part in parts):
                continue

            rel = path.relative_to(root)
            name = path.name.lower()

            if path.name in ENTRY_POINTS:
                found['entry_points'].append(str(rel))
            if name in {f.lower() for f in CONFIG_FILES}:
                found['configs'].append(str(rel))
            if name.startswith('readme'):
                found['readmes'].append(str(rel))
            if '.github/workflows' in str(rel) or name in {'jenkinsfile', '.circleci'}:
                found['ci_cd'].append(str(rel))
            if any(x in name for x in ['test_', '_test', '.test.', '.spec.']):
                found['tests'].append(str(rel))
            if '.env.example' in name or '.env.sample' in name:
                found['env_examples'].append(str(rel))

    # Deduplicate and sort
    for key in found:
        found[key] = sorted(set(found[key]))[:20]

    return found


def detect_framework(root: Path) -> str:
    """Attempt to detect the primary framework."""
    pkg_json = root / 'package.json'
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            if 'next' in deps:
                return 'Next.js'
            if 'react' in deps and 'react-dom' in deps:
                return 'React'
            if 'vue' in deps:
                return 'Vue.js'
            if '@angular/core' in deps:
                return 'Angular'
            if 'express' in deps:
                return 'Express.js'
            if 'fastify' in deps:
                return 'Fastify'
            if 'nestjs' in deps or '@nestjs/core' in deps:
                return 'NestJS'
        except Exception:
            pass

    pyproject = root / 'pyproject.toml'
    if pyproject.exists():
        content = pyproject.read_text()
        if 'fastapi' in content.lower():
            return 'FastAPI'
        if 'django' in content.lower():
            return 'Django'
        if 'flask' in content.lower():
            return 'Flask'

    setup_py = root / 'setup.py'
    if setup_py.exists():
        content = setup_py.read_text()
        if 'django' in content.lower():
            return 'Django'
        if 'flask' in content.lower():
            return 'Flask'

    go_mod = root / 'go.mod'
    if go_mod.exists():
        content = go_mod.read_text()
        if 'github.com/gin-gonic/gin' in content:
            return 'Go + Gin'
        if 'github.com/gofiber/fiber' in content:
            return 'Go + Fiber'
        if 'google.golang.org/grpc' in content:
            return 'Go + gRPC'
        return 'Go'

    if (root / 'Cargo.toml').exists():
        content = (root / 'Cargo.toml').read_text()
        if 'actix' in content:
            return 'Rust + Actix'
        if 'axum' in content:
            return 'Rust + Axum'
        return 'Rust'

    return 'Unknown'


def generate_report(root: Path, output_file: str | None = None) -> str:
    """Generate the full codebase exploration report."""
    root = root.resolve()
    print(f"[EXPLORE] Scanning {root}...", file=sys.stderr)

    tree = build_tree(root)
    file_types = analyze_file_types(root)
    key_files = find_key_files(root)
    framework = detect_framework(root)

    # Determine primary language
    lang_counts = file_types['by_language']
    primary_lang = next(iter(lang_counts), 'Unknown') if lang_counts else 'Unknown'

    report_lines = [
        f"# Codebase Overview: {root.name}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## Summary",
        f"",
        f"| Property | Value |",
        f"|----------|-------|",
        f"| Project Root | `{root}` |",
        f"| Primary Language | {primary_lang} |",
        f"| Framework | {framework} |",
        f"| Total Source Files | {file_types['total']} |",
        f"",
        f"## File Type Distribution",
        f"",
    ]

    for lang, count in list(lang_counts.items())[:15]:
        bar = '█' * min(count, 40)
        report_lines.append(f"  {lang:<30} {count:>5}  {bar}")

    report_lines += [
        f"",
        f"## Directory Structure",
        f"",
        f"```",
        f"{root.name}/",
    ]

    if tree.get('children'):
        for i, child in enumerate(tree['children']):
            is_last = (i == len(tree['children']) - 1)
            report_lines.append(tree_to_string(child, '', is_last))

    report_lines += [
        f"```",
        f"",
        f"## Key Files",
        f"",
    ]

    if key_files['entry_points']:
        report_lines.append("**Entry Points:**")
        for f in key_files['entry_points']:
            report_lines.append(f"  - `{f}`")
        report_lines.append("")

    if key_files['configs']:
        report_lines.append("**Configuration Files:**")
        for f in key_files['configs']:
            report_lines.append(f"  - `{f}`")
        report_lines.append("")

    if key_files['ci_cd']:
        report_lines.append("**CI/CD:**")
        for f in key_files['ci_cd']:
            report_lines.append(f"  - `{f}`")
        report_lines.append("")

    if key_files['readmes']:
        report_lines.append("**Documentation:**")
        for f in key_files['readmes']:
            report_lines.append(f"  - `{f}`")
        report_lines.append("")

    if key_files['env_examples']:
        report_lines.append("**Environment Config:**")
        for f in key_files['env_examples']:
            report_lines.append(f"  - `{f}`")
        report_lines.append("")

    if key_files['tests']:
        report_lines.append(f"**Test Files:** {len(key_files['tests'])} found")
        for f in key_files['tests'][:10]:
            report_lines.append(f"  - `{f}`")
        if len(key_files['tests']) > 10:
            report_lines.append(f"  - ... and {len(key_files['tests']) - 10} more")
        report_lines.append("")

    report_lines += [
        f"## Research Notes",
        f"",
        f"_(Add findings from the research agent here)_",
        f"",
        f"## Patterns Identified",
        f"",
        f"_(Updated by research-agent after pattern analysis)_",
        f"",
        f"## Architectural Decisions",
        f"",
        f"_(Updated by architect-agent)_",
    ]

    report = '\n'.join(report_lines)

    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(report)
        print(f"[EXPLORE] Report written to {output_file}", file=sys.stderr)
    else:
        print(report)

    return report


def main():
    parser = argparse.ArgumentParser(
        description='Explore a codebase and generate a structured overview'
    )
    parser.add_argument('--root', default='.', help='Root directory to explore (default: .)')
    parser.add_argument('--output', help='Output file path (default: stdout)')
    parser.add_argument('--json', action='store_true', help='Output as JSON instead of Markdown')
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        result = {
            'root': str(root.resolve()),
            'framework': detect_framework(root),
            'file_types': analyze_file_types(root),
            'key_files': find_key_files(root),
        }
        print(json.dumps(result, indent=2))
    else:
        generate_report(root, args.output)


if __name__ == '__main__':
    main()
