const fs = require('fs');
const { execSync } = require('child_process');

const SD = 'E:/workbuddy/resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library';
const mapping = fs.readFileSync('E:/gongxiangwenjianjia/xxx/clone_work/mapping.tsv', 'utf8')
  .trim().split('\n').map(l => l.split('\t'));
const meta = JSON.parse(fs.readFileSync('meta.json', 'utf8'));

let bad = 0;
for (const [key, dbid] of mapping) {
  let out;
  try {
    out = execSync(`python "${SD}/database/get_database_schema.py" --database-id ${dbid}`, { encoding: 'utf8' });
  } catch (e) { console.log(key, 'SCHEMA FETCH FAIL'); bad++; continue; }
  const schema = JSON.parse(out);
  const cloud = new Set(schema.properties.map(p => p.name));
  const page = Object.values(meta[key].fields);
  const missing = page.filter(f => !cloud.has(f));
  const unused = [...cloud].filter(f => !page.includes(f));
  const status = missing.length ? 'MISMATCH' : 'OK';
  if (missing.length) bad++;
  console.log(`
[${status}] ${key} (${schema.title})`);
  if (missing.length) console.log('   page 引用但云端缺失:', missing.join(', '));
  if (unused.length) console.log('   云端有但页面未用:', unused.join(', '));
}
console.log(bad === 0 ? '\nALL FIELDS MATCH' : `\n${bad} table(s) mismatch`);
