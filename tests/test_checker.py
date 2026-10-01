import copy
import json
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checker import ROOT, analyze, html_report, issues_csv, load_directory, read_csv


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads((ROOT / 'rules.json').read_text())
        self.clean = load_directory(ROOT / 'sample_data/corrected', self.rules)

    def rules_found(self, report):
        return {i['rule'] for i in report['issues']}

    def test_corrected_data_has_no_findings(self):
        report = analyze(self.clean, self.rules)
        self.assertEqual(report['issues'], [])
        self.assertEqual(sum(report['rows']['source'].values()), 13)

    def test_dirty_data_finds_known_realistic_failures(self):
        report = analyze(load_directory(ROOT / 'sample_data/dirty', self.rules), self.rules)
        self.assertEqual(self.rules_found(report), {'whitespace','required','duplicate_key','date_order','invalid_date','invalid_number','invalid_status','missing_reference','ambiguous_reference'})
        self.assertEqual(report['blockers'], 12)
        self.assertEqual(report['review_findings'], 1)
        duplicate_rows = [i['row'] for i in report['issues'] if i['rule'] == 'duplicate_key']
        self.assertEqual(duplicate_rows, [3,5])

    def test_equal_row_counts_do_not_conceal_loss_or_changed_rent(self):
        target = load_directory(ROOT / 'sample_data/target', self.rules)
        report = analyze(self.clean, self.rules, target)
        self.assertEqual(report['rows']['source'], report['rows']['target'])
        self.assertTrue({'missing_target_record','unexpected_target_record','changed_value'} <= self.rules_found(report))
        self.assertEqual([i['value'] for i in report['issues'] if i['rule'] == 'changed_value'], ['1200 -> 1250'])
        self.assertEqual(report['blockers'], 4)  # Includes target tenancy referring to lost P-005.

    def test_identical_exports_match(self):
        report = analyze(self.clean, self.rules, self.clean)
        self.assertFalse(report['issues'])
        self.assertTrue(all(r['status'] == 'EXACT MATCH' for r in report['reconciliation']))

    def test_missing_parent_never_passes_relationships(self):
        source = dict(self.clean)
        del source['properties']
        report = analyze(source, self.rules)
        self.assertIn('reference_not_checked', self.rules_found(report))
        self.assertEqual(len([c for c in report['checks'] if c['status'] == 'SKIPPED']), 2)
        self.assertGreater(report['blockers'], 0)

    def test_missing_column_never_runs_partial_checks(self):
        source = dict(self.clean, properties='property_id,address\nP-001,Example\n')
        report = analyze(source, self.rules)
        self.assertIn('missing_columns', self.rules_found(report))
        self.assertNotIn('properties', report['rows']['source'])

    def test_duplicate_target_keys_prevent_dict_overwrite(self):
        target = dict(self.clean)
        target['properties'] += 'P-001,Other Address,DEMO-99\n'
        report = analyze(self.clean, self.rules, target)
        self.assertIn('comparison_ambiguous', self.rules_found(report))
        self.assertEqual(report['reconciliation'][0]['status'], 'NOT COMPARED')

    def test_invalid_identical_data_never_gets_clean_verdict(self):
        source = dict(self.clean)
        source['tenancies'] = source['tenancies'].replace('1200', 'NaN')
        report = analyze(source, self.rules, source)
        self.assertEqual(report['verdict'], 'BLOCKERS FOUND')
        self.assertTrue(all(r['status'] == 'EXACT MATCH' for r in report['reconciliation']))

    def test_blank_numeric_value_only_has_required_issue(self):
        source = dict(self.clean)
        source['tenancies'] = source['tenancies'].replace('1200', '')
        report = analyze(source, self.rules)
        self.assertEqual(len(report['issues']), 1)
        self.assertEqual(report['issues'][0]['rule'], 'required')

    def test_trimmed_duplicates_and_whitespace_are_visible(self):
        source = dict(self.clean)
        source['properties'] += ' P-001 ,Other Address,DEMO-99\n'
        report = analyze(source, self.rules)
        self.assertEqual(len([i for i in report['issues'] if i['rule'] == 'duplicate_key']), 2)
        self.assertIn('whitespace', self.rules_found(report))

    def test_strict_csv_structure_and_multiline_line_numbers(self):
        for text in ['', 'id,id\na,b\n', 'id,value\na,b,c\n', 'id,value\na\n', 'id,value\n\n']:
            with self.assertRaises(ValueError):
                read_csv(text)
        parsed = read_csv('id,value\na,"hello\nworld"\nb,plain\n')
        self.assertEqual([r['line'] for r in parsed['records']], [2,4])
        self.assertEqual(read_csv('\ufeffid\na\n')['headers'], ['id'])

    def test_html_escapes_source_and_csv_neutralises_formulas(self):
        source = dict(self.clean)
        source['properties'] = source['properties'].replace('P-001', '=1+1').replace('DEMO-01', '<script>alert(1)</script> ')
        report = analyze(source, self.rules)
        self.assertIn('&lt;script&gt;', html_report(report))
        self.assertNotIn('<script>alert(1)</script>', html_report(report))
        self.assertIn("'=1+1", issues_csv(report))

    def test_input_is_unchanged(self):
        original = copy.deepcopy(self.clean)
        analyze(self.clean, self.rules, self.clean)
        self.assertEqual(self.clean, original)

    def test_missing_target_file_is_blocked_and_not_compared(self):
        target = dict(self.clean)
        del target['maintenance']
        report = analyze(self.clean, self.rules, target)
        self.assertEqual(report['reconciliation'][2]['status'], 'NOT COMPARED')
        self.assertIn('missing_file', self.rules_found(report))


if __name__ == '__main__':
    unittest.main()
