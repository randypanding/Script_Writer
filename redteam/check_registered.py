import json
d = json.load(open('/tmp/Site_Watch/content/points_export.json', encoding='utf-8'))
targets = ['cyber.gov.au', 'afp.gov.au', 'austrac.gov.au', 'asd.gov.au', 'asd.gov.au', 'mic', 'mpi.govt.nz', 'nzsis', 'gcsb', 'nzdf', 'police.govt.nz']
for s in d['sites']:
    u = s.get('url', '')
    if any(t in u for t in ['cyber.gov.au', 'afp.gov.au', 'austrac.gov.au', 'asd.gov.au', 'nzsis', 'gcsb', 'nzdf.mil.nz', 'police.govt.nz']):
        print('###', s['site_name'], '|', u)
        for p in s.get('points', []):
            print('   ', p['source_type'], '|', p['url'], '|', p.get('enabled'))