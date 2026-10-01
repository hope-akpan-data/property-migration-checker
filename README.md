Property Migration Checker

A Python tool that checks property, tenancy and maintenance CSV files before migration. It also compares source files with target exports to find records or values that changed during the move.
For example, two exports can contain the same number of rows while one property is missing or a rent amount has changed. This checker finds those differences and produces a list of records to review.

What it checks
- Missing required values and duplicate IDs.
- Tenancies and maintenance requests linked to missing or duplicate properties.
- Invalid dates, tenancy end dates before start dates, and invalid rent amounts.
- Inconsistent maintenance statuses, extra whitespace and malformed CSV files.
- Missing, unexpected or changed records in a target export.

Each finding includes the record ID, CSV row, affected field, problem and suggested action. Reports are available as HTML, CSV and JSON. The tool flags issues without changing the input files.

Built with
Python, Streamlit, JSON, HTML and CSS. The checking engine uses Python's standard library, including csv, datetime, decimal and unittest. Streamlit provides the upload interface and report downloads.

Run it
Requires Python 3.10 or newer. From the project folder:
python -m pip install -r requirements.txt
python -m streamlit run app.py

Choose a sample workflow or upload your own CSV files. The default columns are defined in rules.json; your files should match them.

You can also run checks from the terminal:
python checker.py
To compare source and target files:
python checker.py --source sample_data/corrected --target sample_data/target --out reports/reconciliation

Sample data and tests
The project includes fictional messy, corrected and target datasets. The messy sample produces 12 blocking findings and 1 review finding. The target example shows why matching row counts isn't enough to verify a migration.

Run the 14 automated tests:
python -m unittest discover -s tests -v

The checker can support migration preparation, trial-import testing and data review. Its rules are configurable, but a clean result only means the data passed those checks. It doesn't confirm factual accuracy or approve a system for go-live.