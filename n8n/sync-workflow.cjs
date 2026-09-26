const fs = require('node:fs');
const path = require('node:path');
const target = path.join(__dirname, 'workflows/mom-routing.json');
const workflow = JSON.parse(fs.readFileSync(target));
const schema = JSON.parse(fs.readFileSync(path.join(__dirname, '../schemas/meeting-delivery-v2.schema.json')));
const code = `const schema = ${JSON.stringify(schema)};\n` + fs.readFileSync(path.join(__dirname,'prepare-mom.js'),'utf8');
const node = workflow.nodes.find(n => n.name === 'Validate payload');
if (process.argv.includes('--check')) {
  if (node.parameters.jsCode !== code) throw Error('Run node n8n/sync-workflow.cjs');
} else {
  node.parameters.jsCode = code;
  fs.writeFileSync(target, JSON.stringify(workflow,null,2)+'\n');
}
