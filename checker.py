"""Local, read-only CSV checks and exact source/target reconciliation. Python 3.10+."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
ISSUE_COLUMNS = ['severity', 'side', 'table', 'row', 'record_id', 'field', 'rule', 'value', 'impact', 'action']


def read_csv(text):
    reader = csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError('The file is empty; a header row is required.')
    if not headers or any(not h or h != h.strip() for h in headers):
        raise ValueError('Headers must be non-empty and have no surrounding whitespace.')
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate column headers make field mapping ambiguous.')
    records = []
    while True:
        line = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            break
        if len(values) != len(headers):
            raise ValueError(f'CSV line {line} has {len(values)} fields; expected {len(headers)}.')
        records.append({'line': line, 'values': dict(zip(headers, values))})
    return {'headers': headers, 'records': records}


def load_directory(directory, rules):
    return {name: (Path(directory) / f'{name}.csv').read_text(encoding='utf-8-sig')
            for name in rules['tables'] if (Path(directory) / f'{name}.csv').exists()}


def analyze(source, rules=None, target=None):
    rules = rules or json.loads((ROOT / 'rules.json').read_text())
    tables = rules['tables']
    issues, parsed, manifests, checks = [], {}, [], []

    def issue(side, table, row, field, rule, value, impact, action, severity='BLOCKER'):
        values = row['values'] if row else {}
        issues.append(dict(zip(ISSUE_COLUMNS, [severity, side, table, row['line'] if row else '',
            values.get(tables[table]['key'], ''), field, rule, value, impact, action])))

    for side, inputs in [('source', source)] + ([('target', target)] if target is not None else []):
        parsed[side] = {}
        for name, spec in tables.items():
            if name not in inputs:
                issue(side, name, None, '', 'missing_file', '', 'This data domain was not checked.', f'Provide {name}.csv.')
                continue
            text = inputs[name]
            manifests.append({'side': side, 'table': name, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()})
            try:
                table = read_csv(text)
            except (ValueError, csv.Error) as exc:
                issue(side, name, None, '', 'invalid_csv', str(exc), 'The file cannot be interpreted reliably.', 'Fix the CSV structure and rerun.')
                continue
            missing = set(spec['columns']) - set(table['headers'])
            if missing:
                issue(side, name, None, ', '.join(sorted(missing)), 'missing_columns', '',
                      'Required checks cannot run for this table.', 'Supply the expected columns or agree a new mapping.')
                continue
            parsed[side][name] = table
            key = spec['key']
            counts = Counter(r['values'][key].strip() for r in table['records'] if r['values'][key].strip())
            for row in table['records']:
                values = row['values']
                for field in spec['columns']:
                    value = values[field]
                    if value != value.strip():
                        issue(side, name, row, field, 'whitespace', value, 'Exact matching may fail in a destination system.',
                              'Review and trim whitespace in an approved working copy.', 'REVIEW')
                for field in spec['required']:
                    if not values[field].strip():
                        issue(side, name, row, field, 'required', values[field], 'A required value is missing.', 'Ask the source owner to supply the value.')
                if values[key].strip() and counts[values[key].strip()] > 1:
                    issue(side, name, row, key, 'duplicate_key', values[key], 'The identifier does not identify one record.',
                          'Ask the data owner which record is authoritative; do not drop rows automatically.')
                dates = {}
                for field in spec.get('dates', []):
                    value = values[field].strip()
                    if not value:
                        continue
                    try:
                        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                            raise ValueError()
                        dates[field] = date.fromisoformat(value)
                    except ValueError:
                        issue(side, name, row, field, 'invalid_date', values[field], 'The date cannot be loaded under the agreed format.', 'Confirm the date; use YYYY-MM-DD.')
                order = spec.get('date_order')
                if order and all(f in dates for f in order) and dates[order[1]] < dates[order[0]]:
                    issue(side, name, row, order[1], 'date_order', values[order[1]], 'The tenancy ends before it starts.', 'Confirm both dates with the source owner.')
                for field in spec.get('nonnegative_numbers', []):
                    value = values[field].strip()
                    if not value:
                        continue
                    try:
                        number = Decimal(value)
                        if not number.is_finite() or number < 0:
                            raise InvalidOperation()
                    except InvalidOperation:
                        issue(side, name, row, field, 'invalid_number', values[field], 'The amount is not a finite, non-negative number.', 'Confirm the amount; use a number without currency symbols or separators.')
                for field, allowed in spec.get('enums', {}).items():
                    if values[field].strip() and values[field] not in allowed:
                        issue(side, name, row, field, 'invalid_status', values[field], 'The status is outside the agreed target vocabulary.',
                              'Agree a mapping to: ' + ', '.join(allowed) + '.')
            checks.append({'side': side, 'table': name, 'check': 'table_validation', 'status': 'EXECUTED', 'rows': len(table['records'])})

        # Referential checks occur after all tables have been read, independent of order.
        for name, table in parsed[side].items():
            spec = tables[name]
            for field, parent in spec.get('references', {}).items():
                if parent not in parsed[side]:
                    issue(side, name, None, field, 'reference_not_checked', '', 'Relationship checks were skipped because the parent file is unavailable or invalid.', f'Fix {parent}.csv and rerun.')
                    checks.append({'side': side, 'table': name, 'check': field + '_reference', 'status': 'SKIPPED'})
                    continue
                parent_key = tables[parent]['key']
                counts = Counter(r['values'][parent_key].strip() for r in parsed[side][parent]['records'] if r['values'][parent_key].strip())
                for row in table['records']:
                    value = row['values'][field].strip()
                    if not value:
                        continue
                    if value not in counts:
                        issue(side, name, row, field, 'missing_reference', row['values'][field], 'The record points to a property absent from the property register.', 'Confirm the ID or supply the missing property record.')
                    elif counts[value] > 1:
                        issue(side, name, row, field, 'ambiguous_reference', row['values'][field], 'The linked property has multiple candidate records.', 'Resolve the duplicate property ID before linking this record.')
                checks.append({'side': side, 'table': name, 'check': field + '_reference', 'status': 'EXECUTED'})

    reconciliation = []
    if target is not None:
        for name, spec in tables.items():
            src, dst = parsed['source'].get(name), parsed['target'].get(name)
            result = {'table': name, 'source_rows': len(src['records']) if src else None,
                      'target_rows': len(dst['records']) if dst else None, 'status': 'NOT COMPARED'}
            if src is None or dst is None:
                reconciliation.append(result)
                continue
            key = spec['key']
            # Never let dict construction conceal duplicates or missing identifiers.
            def comparable(table):
                keys = [r['values'][key] for r in table['records']]
                return all(k and k == k.strip() for k in keys) and len(keys) == len(set(keys))
            if not comparable(src) or not comparable(dst):
                issue('reconciliation', name, None, key, 'comparison_ambiguous', '', 'Reliable record comparison requires unique, non-blank, trimmed identifiers on both sides.', 'Resolve identifiers and rerun reconciliation.')
                reconciliation.append(result)
                continue
            left = {r['values'][key]: r for r in src['records']}
            right = {r['values'][key]: r for r in dst['records']}
            lost, extra = sorted(left.keys() - right.keys()), sorted(right.keys() - left.keys())
            changed = 0
            for rid in lost:
                issue('reconciliation', name, left[rid], key, 'missing_target_record', rid, 'A source record is absent from the target export.', 'Investigate the import rejection or omission.')
            for rid in extra:
                issue('reconciliation', name, right[rid], key, 'unexpected_target_record', rid, 'A target record was not in this source batch.', 'Confirm the target export scope or investigate the extra record.')
            for rid in sorted(left.keys() & right.keys()):
                for field in spec['columns']:
                    a, b = left[rid]['values'][field], right[rid]['values'][field]
                    if a != b:
                        changed += 1
                        issue('reconciliation', name, right[rid], field, 'changed_value', f'{a} -> {b}', 'The target value differs from the source.', 'Confirm an approved transformation or correct the mismatch.')
            result.update(missing_records=len(lost), unexpected_records=len(extra), changed_fields=changed,
                          status='MISMATCH' if lost or extra or changed else 'EXACT MATCH')
            reconciliation.append(result)

    issues.sort(key=lambda x: (x['severity'] != 'BLOCKER', x['side'], x['table'], str(x['row']), x['rule']))
    blockers = sum(i['severity'] == 'BLOCKER' for i in issues)
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'rule_version': rules.get('version', 'unversioned'),
            'verdict': 'BLOCKERS FOUND' if blockers else ('REVIEW REQUIRED' if issues else 'NO ISSUES FOUND IN DEFINED CHECKS'),
            'blockers': blockers, 'review_findings': len(issues) - blockers, 'issues': issues,
            'rows': {side: {name: len(t['records']) for name, t in data.items()} for side, data in parsed.items()},
            'checks': checks, 'reconciliation': reconciliation, 'input_manifest': manifests}


def issues_csv(report):
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=ISSUE_COLUMNS)
    writer.writeheader()
    for finding in report['issues']:
        # Neutralise spreadsheet formula interpretation in human-review exports.
        writer.writerow({k: "'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for k, v in finding.items()})
    return buf.getvalue()


def html_report(report):
    esc = lambda value: html.escape(str(value))
    def table(rows, fields):
        if not rows:
            return '<p>No findings in this section.</p>'
        return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+esc(f.replace('_', ' '))+'</th>' for f in fields) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+esc(row.get(f, ''))+'</td>' for f in fields)+'</tr>' for row in rows) + '</tbody></table></div>'
    affected = len({(i['side'], i['table'], i['row']) for i in report['issues'] if i['row'] != ''})
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Property data review</title>
<style>body{margin:0;background:#f4f6f8;color:#182534;font:15px/1.6 system-ui,sans-serif}main{max-width:1150px;margin:auto;padding:40px 24px}header{border-top:5px solid #14816c;padding-top:20px}h1{font-size:36px;line-height:1.2;margin:8px 0}h2{margin-top:34px}.label{color:#17715f;font-size:12px;letter-spacing:2px;font-weight:700}.cards{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.card{background:white;border:1px solid #dde4ea;border-radius:12px;padding:20px;flex:1;min-width:140px}.number{font-size:32px;font-weight:750}small{color:#5e6976}.scroll{overflow:auto;background:white;border:1px solid #dde4ea;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e5e9ed}th{background:#eaf1f0;white-space:nowrap;text-transform:capitalize}td{min-width:80px;overflow-wrap:anywhere}details{margin-top:24px}button{background:#176d5c;color:white;border:0;border-radius:6px;padding:10px 16px;cursor:pointer}@media print{button{display:none}main{padding:0}.scroll{overflow:visible}table{font-size:9px}th,td{padding:5px}}</style><main>
<header><div class="label">HOPE AKPAN / DATA ENGINEERING DEMONSTRATION</div><h1>Property data review</h1><p>Record-level checks before migration, with optional source-to-target reconciliation.</p></header>
''' + '<p><strong>'+esc(report['verdict'])+'</strong></p><div class="cards">' + ''.join('<div class="card"><div class="number">'+esc(n)+'</div>'+label+'</div>' for n, label in [(report['blockers'], 'Blocking findings'), (report['review_findings'], 'Review findings'), (affected, 'Affected record rows')]) + '</div>' + '''<p>Findings can overlap on one record. The rules are demonstration assumptions, not a client-approved migration specification. Passing these checks does not establish factual accuracy, legal compliance or go-live approval. Source files are never changed.</p><button onclick="window.print()">Print / save as PDF</button>''' + '<h2>Files checked</h2>' + table([{'side': side, 'table': name, 'records': count} for side, values in report['rows'].items() for name, count in values.items()], ['side', 'table', 'records']) + '<h2>What needs attention</h2>' + table(report['issues'], ISSUE_COLUMNS) + '<h2>Source-to-target reconciliation</h2>' + (table(report['reconciliation'], ['table', 'status', 'source_rows', 'target_rows', 'missing_records', 'unexpected_records', 'changed_fields']) if report['reconciliation'] else '<p>No target export supplied. No post-migration comparison was performed.</p>') + '<details><summary>Check execution and input fingerprints</summary>' + table(report['checks'], ['side', 'table', 'check', 'status', 'rows']) + table(report['input_manifest'], ['side', 'table', 'sha256']) + '</details><p><small>Generated '+esc(report['generated_at'])+' · Rule version '+esc(report['rule_version'])+' · Rows refer to the starting physical line in the relevant CSV file. SHA-256 fingerprints cover the decoded UTF-8 content, after file-level BOM removal by the loader.</small></p></main></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'sample_data/dirty')
    parser.add_argument('--target', type=Path)
    parser.add_argument('--rules', type=Path, default=ROOT / 'rules.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    report = analyze(load_directory(args.source, rules), rules,
                     load_directory(args.target, rules) if args.target is not None else None)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (args.out / 'issues.csv').write_text(issues_csv(report), encoding='utf-8-sig')
    (args.out / 'report.html').write_text(html_report(report), encoding='utf-8')
    print(f"{report['verdict']}: {report['blockers']} blockers; {report['review_findings']} review findings. Reports: {args.out}")
    return 2 if report['blockers'] else (1 if report['review_findings'] else 0)


if __name__ == '__main__':
    raise SystemExit(main())
