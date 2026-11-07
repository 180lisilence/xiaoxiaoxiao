import json, io, os, sys

BASE = r"E:/gongxiangwenjianjia/xxx/clone_work"
src = os.path.join(BASE, 'build', 'xiaoxiaoxiao.html')
dst = os.path.join(BASE, 'build', 'final.html')

mapping = dict(l.split('\t') for l in open(os.path.join(BASE, 'mapping.tsv'), encoding='utf-8').read().strip().split('\n'))

html = open(src, encoding='utf-8').read()
count = 0
for key, dbid in mapping.items():
    token = '__DB_%s__' % key.upper()
    n = html.count(token)
    if n == 0:
        print('WARN token not found:', token)
    html = html.replace(token, dbid)
    count += n

# 校验没有残留占位符
import re
left = re.findall(r'__DB_[A-Z]+__', html)
if left:
    print('ERROR 残留占位符:', set(left))
    sys.exit(1)

open(dst, 'w', encoding='utf-8').write(html)
print(f'OK 替换 {count} 处 databaseId 占位符 -> {dst}')
print('大小', os.path.getsize(dst), 'bytes')
