const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');

const start = html.indexOf('var META = {');
const end = html.indexOf('var EXPENSE_CATS');
const metaBlock = html.slice(start, end);
const meta = {};
for (const line of metaBlock.split('\n')) {
  const m = line.match(/^\s{2}(\w+):\s*\{\s*title:'([^']+)'\s*,\s*fields:\{([^}]*)\}/);
  if (!m) continue;
  const fields = {};
  for (const p of m[3].matchAll(/(\w+):'([^']+)'/g)) fields[p[1]] = p[2];
  meta[m[1]] = { title: m[2], fields };
}
for (const k of Object.keys(meta)) {
  console.log(k.padEnd(9), meta[k].title.padEnd(9), Object.values(meta[k].fields).join(', '));
}
fs.writeFileSync(process.argv[3] || 'meta.json', JSON.stringify(meta, null, 1));
