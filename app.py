"""Optional Streamlit interface; the checker and CLI need no third-party packages."""
import io
import hashlib
import json
import zipfile
import streamlit as st
from checker import ROOT, analyze, html_report, issues_csv, load_directory

st.set_page_config(page_title='Property Migration Checker', page_icon='🏠', layout='wide')
st.caption('HOPE AKPAN · DATA ENGINEERING DEMONSTRATION')
st.title('Check property data before it moves')
st.write('Find records that need attention. Check whether a target export matches the source.')
st.info('Synthetic examples. Configurable demo rules. No files are changed. Results support review, not go-live approval.')
rules = json.loads((ROOT / 'rules.json').read_text())
mode = st.radio('Choose a workflow', ['Messy sample', 'Corrected sample', 'Reconciliation sample', 'Upload CSV files'], horizontal=True)
source, target = {}, None
if mode == 'Upload CSV files':
    st.caption('Upload the three files below using the columns shown in the rules. Files are processed by the local Streamlit process.')
    for name, spec in rules['tables'].items():
        uploaded = st.file_uploader(f'{name}.csv', type=['csv'], key='source_' + name)
        st.caption('Columns: ' + ', '.join(spec['columns']))
        if uploaded:
            try:
                source[name] = uploaded.getvalue().decode('utf-8-sig')
            except UnicodeDecodeError:
                st.error(f'{name}: save the file as UTF-8 CSV.')
                st.stop()
    compare = st.checkbox('Also compare target exports')
    if compare:
        target = {}
        with st.expander('Target files', expanded=True):
            for name in rules['tables']:
                uploaded = st.file_uploader(f'Target {name}.csv', type=['csv'], key='target_' + name)
                if uploaded:
                    try:
                        target[name] = uploaded.getvalue().decode('utf-8-sig')
                    except UnicodeDecodeError:
                        st.error(f'Target {name}: save the file as UTF-8 CSV.')
                        st.stop()
    signature = hashlib.sha256(json.dumps({'source': source, 'target': target}, sort_keys=True).encode()).hexdigest()
    if st.button('Run checks', type='primary'):
        st.session_state['review_signature'] = signature
    if st.session_state.get('review_signature') != signature:
        st.stop()
else:
    source = load_directory(ROOT / ('sample_data/dirty' if mode == 'Messy sample' else 'sample_data/corrected'), rules)
    if mode == 'Reconciliation sample':
        target = load_directory(ROOT / 'sample_data/target', rules)

report = analyze(source, rules, target)
st.subheader(report['verdict'])
a, b, c = st.columns(3)
a.metric('Blocking findings', report['blockers'])
b.metric('Review findings', report['review_findings'])
c.metric('Source records checked', sum(report['rows']['source'].values()))
st.caption('Finding counts can overlap on one record. Missing or invalid files are shown as blockers.')
if report['issues']:
    severity = st.selectbox('Show findings', ['All', 'BLOCKER', 'REVIEW'])
    findings = [i for i in report['issues'] if severity == 'All' or i['severity'] == severity]
    st.dataframe(findings, width='stretch', hide_index=True)
else:
    st.success('No issues found under the defined rules. Business owner review is still required.')
if report['reconciliation']:
    st.subheader('Source-to-target comparison')
    st.dataframe(report['reconciliation'], width='stretch', hide_index=True)
with st.expander('Rules and execution details'):
    st.json(rules)
    st.dataframe(report['checks'], width='stretch', hide_index=True)
st.subheader('Take the review pack with you')
bundle = io.BytesIO()
with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('report.html', html_report(report))
    archive.writestr('issues.csv', '\ufeff' + issues_csv(report))
    archive.writestr('report.json', json.dumps(report, indent=2))
    archive.writestr('rules.json', json.dumps(rules, indent=2))
st.download_button('Download review pack', bundle.getvalue(), 'property-data-review.zip', 'application/zip')
