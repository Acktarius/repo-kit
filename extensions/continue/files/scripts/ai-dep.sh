#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'USAGE'
Usage:
  ai-dep.sh [package ...]
  ai-dep.sh --file package.json [package ...]
  ai-dep.sh --limit 20
  ai-dep.sh --dev
  ai-dep.sh --all
  ai-dep.sh --write [PATH]
  ai-dep.sh help

Purpose:
  Inspect dependencies from package.json, account for root overrides, read
  .npmrc min-release-age, query npmx.dev, and emit a Markdown update brief.

Notes:
  - Uses npmx.dev as the external package metadata source.
  - Uses root package.json overrides only.
  - Vulns are read from the npmx version page (curl .../package/NAME/v/VERSION).
  - No temporary install is performed.

Options:
  --file PATH   package.json path, default: ./package.json
  --limit N     max dependencies to inspect, default: all selected
  --dev         include only devDependencies
  --prod        include only dependencies
  --all         include dependencies, devDependencies, optionalDependencies, peerDependencies
  --json        emit JSON instead of Markdown
  --write [PATH]
                also write output to PATH (default: deps-review.md); still prints to stdout
USAGE
}

pkg_file="package.json"
mode="prod"
limit=""
json_out=0
write_path=""
names=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    help|-h|--help)
      show_help
      exit 0
      ;;
    --file)
      shift
      pkg_file="${1:-}"
      [[ -n "$pkg_file" ]] || { echo "--file requires a path" >&2; exit 1; }
      shift
      ;;
    --limit)
      shift
      limit="${1:-}"
      [[ "$limit" =~ ^[0-9]+$ ]] || { echo "--limit requires an integer" >&2; exit 1; }
      shift
      ;;
    --dev)
      mode="dev"
      shift
      ;;
    --prod)
      mode="prod"
      shift
      ;;
    --all)
      mode="all"
      shift
      ;;
    --json)
      json_out=1
      shift
      ;;
    --write)
      shift
      if [[ $# -gt 0 && "$1" != -* ]]; then
        write_path="$1"
        shift
      else
        write_path="deps-review.md"
      fi
      ;;
    *)
      names+=("$1")
      shift
      ;;
  esac
done

[[ -f "$pkg_file" ]] || { echo "package.json not found: $pkg_file" >&2; exit 1; }

PKG_FILE="$pkg_file" MODE="$mode" LIMIT="$limit" JSON_OUT="$json_out" WRITE_PATH="$write_path" NAMES_CSV="$(IFS=,; echo "${names[*]-}")" python3 - <<'PY'
import json, os, re, sys, subprocess, textwrap, urllib.request, urllib.parse, datetime
from pathlib import Path

pkg_path = Path(os.environ['PKG_FILE'])
mode = os.environ['MODE']
limit = os.environ.get('LIMIT', '').strip()
json_out = os.environ.get('JSON_OUT') == '1'
write_path = os.environ.get('WRITE_PATH', '').strip()
names_csv = os.environ.get('NAMES_CSV', '').strip()
selected_names = [x for x in names_csv.split(',') if x]
lines: list[str] = []

def emit(s: str = ''):
    lines.append(s)

RED = '\033[31m'
RESET = '\033[0m'
use_color = (
    (not json_out)
    and sys.stdout.isatty()
    and os.environ.get('NO_COLOR') is None
)

def colorize_line(line: str) -> str:
    if not use_color:
        return line
    m = re.match(r'^(- npmx Vulns: )(\d+)(.*)$', line)
    if m and int(m.group(2)) > 0:
        return f'{RED}{line}{RESET}'
    m = re.match(r'^(npmx Vulns: )(\d+)( reported on npmx version page)$', line)
    if m and int(m.group(2)) > 0:
        return f'{RED}{line}{RESET}'
    return line

def read_json(path: Path):
    return json.loads(path.read_text())

def find_npmrc(start: Path):
    cur = start.resolve().parent
    for p in [cur, *cur.parents]:
        cand = p / '.npmrc'
        if cand.exists():
            return cand
    home = Path.home() / '.npmrc'
    return home if home.exists() else None

def parse_npmrc(path: Path | None):
    cfg = {}
    if not path:
        return cfg
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith(';'):
            continue
        if '=' in s:
            k, v = s.split('=', 1)
            cfg[k.strip()] = v.strip()
    return cfg

def normalize_age_minutes(cfg: dict):
    if 'min-release-age' in cfg:
        try:
            return int(cfg['min-release-age']) * 24 * 60
        except ValueError:
            return None
    if 'minimumReleaseAge' in cfg:
        try:
            return int(cfg['minimumReleaseAge'])
        except ValueError:
            return None
    return None

pkg = read_json(pkg_path)
overrides = pkg.get('overrides', {}) or {}
sections = []
if mode == 'prod':
    sections = ['dependencies']
elif mode == 'dev':
    sections = ['devDependencies']
else:
    sections = ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']

deps = []
for sec in sections:
    for name, spec in (pkg.get(sec, {}) or {}).items():
        deps.append({'name': name, 'spec': spec, 'section': sec})

if selected_names:
    wanted = set(selected_names)
    deps = [d for d in deps if d['name'] in wanted]

if limit:
    deps = deps[:int(limit)]

npmrc_path = find_npmrc(pkg_path)
npmrc_cfg = parse_npmrc(npmrc_path)
min_age_minutes = normalize_age_minutes(npmrc_cfg)
now = datetime.datetime.now(datetime.timezone.utc)

def fetch(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 ai-dep.sh'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8', errors='replace')

def fetch_registry_meta(name: str):
    url = 'https://registry.npmjs.org/' + urllib.parse.quote(name, safe='@/')
    try:
        return json.loads(fetch(url))
    except Exception:
        return None

def npmx_version_url(name: str, version: str):
    return (
        'https://npmx.dev/package/'
        + urllib.parse.quote(name, safe='@/')
        + '/v/'
        + urllib.parse.quote(version, safe='')
    )

def curl_npmx_version_page(name: str, version: str):
    url = npmx_version_url(name, version)
    try:
        html = subprocess.check_output(
            ['curl', '-fsSL', '-A', 'Mozilla/5.0 ai-dep.sh', '--max-time', '20', url],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return html, url
    except Exception:
        return None, url

def parse_npmx_vulns(html: str):
    # Version pages expose: <dt>Vulns</dt><dd>... N ...</dd>
    m = re.search(r'>Vulns</dt>\s*<dd[^>]*>(.*?)</dd>', html, re.I | re.S)
    if m:
        nums = re.findall(r'>\s*(\d+)\s*<', m.group(1))
        if nums:
            count = int(nums[-1])
            return {
                'has_vulnerability_signal': count > 0,
                'vuln_count': count,
                'severity_mentions': [],
            }
    # Fallback: curl | grep-style scan for "Vulns" near a digit
    m = re.search(r'Vulns[\s\S]{0,240}?(\d+)', html, re.I)
    if m:
        count = int(m.group(1))
        return {
            'has_vulnerability_signal': count > 0,
            'vuln_count': count,
            'severity_mentions': [],
        }
    return {'has_vulnerability_signal': None, 'vuln_count': None, 'severity_mentions': []}

def eligible_versions(meta, spec, min_age_minutes):
    versions = meta.get('versions', {}) if meta else {}
    times = meta.get('time', {}) if meta else {}
    try:
        semver = subprocess.check_output(['node', '-e', 'const semver=require("semver"); const spec=process.argv[1]; const arr=JSON.parse(process.argv[2]); const out=arr.filter(v=>semver.valid(v)&&semver.satisfies(v,spec,{includePrerelease:false})).sort(semver.rcompare); console.log(JSON.stringify(out));', spec, json.dumps(list(versions.keys()))], text=True)
        ordered = json.loads(semver)
    except Exception:
        ordered = sorted([v for v in versions.keys() if re.match(r'^\d+\.\d+\.\d+', v)], reverse=True)
    out = []
    for v in ordered:
        t = times.get(v)
        published = None
        age_minutes = None
        age_ok = None
        if t:
            try:
                published = datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))
                age_minutes = int((now - published).total_seconds() // 60)
                age_ok = (min_age_minutes is None) or (age_minutes >= min_age_minutes)
            except Exception:
                pass
        else:
            age_ok = min_age_minutes is None
        out.append({'version': v, 'published': published.isoformat() if published else None, 'age_minutes': age_minutes, 'age_ok': age_ok})
    return out

def flatten_override_hit(name: str, overrides_obj):
    if not overrides_obj:
        return None
    if name in overrides_obj:
        return overrides_obj[name]
    for k, v in overrides_obj.items():
        if isinstance(v, dict):
            if name in v:
                return {f'{k} -> {name}': v[name]}
    return None

results = []
for dep in deps:
    name = dep['name']
    spec = dep['spec']
    reg = fetch_registry_meta(name)
    versions = eligible_versions(reg, spec, min_age_minutes)
    chosen = None
    for v in versions:
        if v['age_ok']:
            chosen = v
            break
    latest = versions[0] if versions else None
    probe = chosen or latest
    if probe:
        html, npmx_url = curl_npmx_version_page(name, probe['version'])
        npmx_signals = parse_npmx_vulns(html) if html else {
            'has_vulnerability_signal': None,
            'vuln_count': None,
            'severity_mentions': [],
        }
    else:
        npmx_url = 'https://npmx.dev/package/' + urllib.parse.quote(name, safe='@/')
        npmx_signals = {
            'has_vulnerability_signal': None,
            'vuln_count': None,
            'severity_mentions': [],
        }
    override_hit = flatten_override_hit(name, overrides)
    results.append({
        'name': name,
        'section': dep['section'],
        'current_spec': spec,
        'override': override_hit,
        'npmx_url': npmx_url,
        'latest_matching': latest,
        'chosen': chosen,
        'min_release_age_minutes': min_age_minutes,
        'npmx_vulnerability_signal': npmx_signals['has_vulnerability_signal'],
        'npmx_vuln_count': npmx_signals['vuln_count'],
        'npmx_severity_mentions': npmx_signals['severity_mentions'],
    })

if json_out:
    emit(json.dumps({
        'package_json': str(pkg_path),
        'npmrc': str(npmrc_path) if npmrc_path else None,
        'min_release_age_minutes': min_age_minutes,
        'results': results,
    }, indent=2))
else:
    emit('# Dependency review context')
    emit(f'package.json: {pkg_path}')
    emit(f'.npmrc: {npmrc_path if npmrc_path else "not found"}')
    emit(f'min-release-age: {min_age_minutes if min_age_minutes is not None else "not set"} minutes')
    emit()

    for r in results:
        emit(f'## {r["name"]}')
        emit(f'- Section: {r["section"]}')
        emit(f'- Current spec: `{r["current_spec"]}`')
        if r['override'] is not None:
            emit(f'- Override: `{json.dumps(r["override"], ensure_ascii=False)}`')
        else:
            emit(f'- Override: none detected')
        emit(f'- npmx: {r["npmx_url"]}')
        if r['latest_matching']:
            lm = r['latest_matching']
            emit(f'- Latest matching version: `{lm["version"]}`' + (f' (published {lm["published"]})' if lm['published'] else ''))
        else:
            emit(f'- Latest matching version: not found')
        if r['chosen']:
            ch = r['chosen']
            emit(f'- Candidate by age gate: `{ch["version"]}`' + (f' (published {ch["published"]})' if ch['published'] else ''))
        else:
            emit(f'- Candidate by age gate: not found')
        vuln = r['npmx_vulnerability_signal']
        vuln_count = r['npmx_vuln_count']
        if vuln is True:
            emit(f'- npmx Vulns: {vuln_count}' + (f' ({", ".join(r["npmx_severity_mentions"])})' if r['npmx_severity_mentions'] else ''))
        elif vuln is False:
            emit(f'- npmx Vulns: 0')
        else:
            emit(f'- npmx Vulns: not clearly detectable from version page')
        emit()
        emit('Prompt to paste into Cursor / Perplexity Ask:')
        current = r['current_spec']
        candidate = r['chosen']['version'] if r['chosen'] else 'none found'
        override_text = json.dumps(r['override'], ensure_ascii=False) if r['override'] is not None else 'none'
        if vuln is True:
            vuln_text = f'{vuln_count} reported on npmx version page'
        elif vuln is False:
            vuln_text = '0 on npmx version page'
        else:
            vuln_text = 'unclear from npmx version page'
        emit(textwrap.dedent(f'''\
        Review whether it is safe to update `{r['name']}` in this project.
        Current spec: {current}
        Candidate version after applying min-release-age: {candidate}
        Root override affecting this package: {override_text}
        npmx Vulns: {vuln_text}
        npmx version page: {r['npmx_url']}

        Please check for:
        - breaking changes between current and candidate versions
        - maintainer or ecosystem concerns
        - migration notes
        - whether overrides make this update unsafe or misleading
        - whether the package should be updated now, pinned, or skipped
        ''').rstrip())
        emit('---')
        emit()

plain = '\n'.join(lines) + '\n'
sys.stdout.write('\n'.join(colorize_line(l) for l in lines) + '\n')
if write_path:
    Path(write_path).write_text(plain, encoding='utf-8')
    print(f'Wrote {write_path}', file=sys.stderr)
PY