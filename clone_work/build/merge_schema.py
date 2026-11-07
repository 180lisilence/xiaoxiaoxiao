import json, subprocess, sys, os

SD = r"E:/workbuddy/resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library"
BASE = r"E:/gongxiangwenjianjia/xxx/clone_work"

mapping = [l.split('\t') for l in open(os.path.join(BASE, 'mapping.tsv'), encoding='utf-8').read().strip().split('\n')]

merged = {}
props = []
for key, dbid in mapping:
    out = subprocess.check_output([sys.executable, os.path.join(SD, 'database', 'get_database_schema.py'),
                                   '--database-id', dbid], cwd=SD, encoding='utf-8')
    schema = json.loads(out)
    for p in schema['properties']:
        if p['name'] not in merged:
            merged[p['name']] = p
            props.append(p)

out_path = os.path.join(BASE, 'build', 'merged_schema.json')
json.dump({'properties': props}, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('merged fields:', len(props))
print(', '.join(p['name'] + ':' + p['type'] for p in props))
