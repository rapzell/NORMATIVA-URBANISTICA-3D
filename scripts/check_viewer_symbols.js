// Comprueba que símbolos clave del visor estén definidos en el JS inline de index.html
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'examples', 'threejs-viewer', 'index.html'), 'utf8');
const re = /<script([^>]*)>([\s\S]*?)<\/script>/gi;
let m, code = '';
while ((m = re.exec(html))) {
  const attrs = m[1] || '';
  if (/src=/.test(attrs) || /importmap|application\/json/.test(attrs)) continue;
  code += m[2] + '\n';
}
const syms = process.argv.slice(2).length ? process.argv.slice(2) : [
  'ensurePrefetchDebug','getLeadPercent','recordCenters','orderBuildingsLayers',
  'adjust3DVisibility','applyTerrainSafeBase','showToast','ensureMap',
  'subdivideBBoxGrid','tileCacheTrimLRU','prefetchPredictive','startBuildingsWarmup',
  'seedBuildingsTest','buildZoneInput','consultarNormativa','applyFromRespuesta',
  'buildingsUpdateDebounced','enableBuildings','disableBuildings','log'
];
let missing = 0;
for (const s of syms) {
  const def = new RegExp('(function\\s+' + s + '\\b|(const|let|var)\\s+' + s + '\\b|' + s + '\\s*=)').test(code);
  const uses = (code.match(new RegExp('\\b' + s + '\\b', 'g')) || []).length;
  if (!def && uses > 0) { missing++; console.log('UNDEFINED:', s, 'uses=' + uses); }
  else console.log('ok:', s, 'uses=' + uses);
}
console.log(missing ? ('MISSING SYMBOLS: ' + missing) : 'All symbols defined.');
