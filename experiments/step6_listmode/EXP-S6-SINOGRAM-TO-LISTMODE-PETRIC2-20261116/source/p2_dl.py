"""Download PETRIC2 test datasets (needed files only) into D:/PET_DATA/petric2/<dataset>/ with curl (resumable)."""
import json, sys, os, subprocess, urllib.request
B = 'https://petric.tomography.stfc.ac.uk/2/data'
UA = {'User-Agent': 'Mozilla/5.0 (research script)'}
listing, root, sets = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
keep = ('prompts', 'additive_term', 'mult_factors', 'OSEM_image', 'kappa', 'penalisation_factor', 'PETRIC/VOI_', 'PETRIC/reference_image')
def token():
    r = urllib.request.Request(B + '/api/login', data=b'{}', headers={**UA, 'Content-Type': 'application/json'}, method='POST')
    return urllib.request.urlopen(r, timeout=60).read().decode()
files = [f for f in json.load(open(listing, encoding='utf-8'))
         if f['path'].split('/')[0] in sets and any(k in f['path'] for k in keep) and not f['path'].endswith('.png')]
files.sort(key=lambda f: (sets.index(f['path'].split('/')[0]), f['size']))
for f in files:
    dst = os.path.join(root, *f['path'].split('/'))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) == f['size']:
        continue
    for attempt in range(20):
        tok = token()
        subprocess.run(['curl', '-sS', '-L', '-C', '-', '--retry', '5', '--connect-timeout', '30', '-A', UA['User-Agent'],
                        '-H', 'X-Auth: ' + tok, '-o', dst, B + '/api/raw/' + urllib.request.quote(f['path'])])
        if os.path.exists(dst) and os.path.getsize(dst) == f['size']:
            break
    ok = os.path.exists(dst) and os.path.getsize(dst) == f['size']
    print(('OK  ' if ok else 'FAIL'), f"{f['size']/1e6:9.1f} MB", f['path'], flush=True)
print('done', flush=True)
