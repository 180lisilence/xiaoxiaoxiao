import json, subprocess, sys, os

SD = r"E:/workbuddy/resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library"
BASE = r"E:/gongxiangwenjianjia/xxx/clone_work"

mapping = [l.split('\t') for l in open(os.path.join(BASE, 'mapping.tsv'), encoding='utf-8').read().strip().split('\n')]
meta = json.load(open(os.path.join(BASE, 'build', 'meta.json'), encoding='utf-8'))

bad = 0
for key, dbid in mapping:
    try:
        out = subprocess.check_output([sys.executable, os.path.join(SD, 'database', 'get_database_schema.py'),
                                       '--database-id', dbid], cwd=SD, encoding='utf-8')
        schema = json.loads(out)
    except Exception as e:
        print(f'{key} SCHEMA FETCH FAIL: {e}')
        bad += 1
        continue
    cloud = [p['name'] for p in schema['properties']]
    page = list(meta[key]['fields'].values())
    missing = [f for f in page if f not in cloud]
    unused = [f for f in cloud if f not in page]
    status = 'MISMATCH' if missing else 'OK'
    if missing:
        bad += 1
    print(f"[{status}] {key:9s} {schema['title']}")
    if missing:
        print('    页面引用但云端缺失:', ', '.join(missing))
    if unused:
        print('    云端有但页面未用:', ', '.join(unused))

print('\nALL FIELDS MATCH' if bad == 0 else f'\n{bad} table(s) mismatch')
