// The names the scripts of the page use without declaring them: what they expect of the browser. The scripts are joined
// in the order given and read as one, the way the page runs them in one world. Prints the names as one JSON list.
//   node --expose-internals page_names.js FILE.js [FILE.js ...]
// A name that one script expects from another and that nobody declares is in the list, whichever line uses it and
// whether or not any check ever runs that line. Uses the parser node ships (acorn), nothing is installed.
'use strict';
const acorn = require('internal/deps/acorn/acorn/dist/acorn'), fs = require('node:fs');

function bound(p, out = []) {  // the names a pattern declares
  if (!p) return out;
  if (p.type === 'Identifier') out.push(p.name);
  else if (p.type === 'ObjectPattern') for (const q of p.properties) bound(q.type === 'RestElement' ? q.argument : q.value, out);
  else if (p.type === 'ArrayPattern') for (const q of p.elements) bound(q, out);
  else if (p.type === 'AssignmentPattern' || p.type === 'RestElement') bound(p.left || p.argument, out);
  return out;
}
function declared(statements) {  // what a block declares itself: let, const, var, class, function
  const names = new Set();
  for (const s of statements) {
    if (s.type === 'VariableDeclaration') for (const d of s.declarations) bound(d.id).forEach(n => names.add(n));
    else if (s.type === 'FunctionDeclaration' || s.type === 'ClassDeclaration') names.add(s.id.name);
  }
  return names;
}
function free(tree) {  // every name that no scope around its use declares
  const names = new Set();
  const pattern = (p, scopes) => {  // a pattern declares names; only its defaults and computed keys are uses
    if (!p || p.type === 'Identifier') return;
    if (p.type === 'ObjectPattern') for (const q of p.properties) { if (q.type === 'RestElement') pattern(q.argument, scopes); else { if (q.computed) walk(q.key, scopes); pattern(q.value, scopes); } }
    else if (p.type === 'ArrayPattern') for (const q of p.elements) pattern(q, scopes);
    else if (p.type === 'AssignmentPattern') { pattern(p.left, scopes); walk(p.right, scopes); }
    else if (p.type === 'RestElement') pattern(p.argument, scopes);
    else walk(p, scopes);
  };
  const block = (statements, scopes) => { const inner = [...scopes, declared(statements)]; for (const s of statements) walk(s, inner); };
  function walk(node, scopes) {
    if (!node || typeof node.type !== 'string') return;
    switch (node.type) {
      case 'Identifier': if (!scopes.some(s => s.has(node.name))) names.add(node.name); return;
      case 'FunctionDeclaration': case 'FunctionExpression': case 'ArrowFunctionExpression': {
        const own = new Set(node.params.flatMap(p => bound(p)));
        if (node.type === 'FunctionExpression' && node.id) own.add(node.id.name);
        if (node.type !== 'ArrowFunctionExpression') own.add('arguments');
        const inner = [...scopes, own];
        for (const p of node.params) pattern(p, inner);
        if (node.body.type === 'BlockStatement') block(node.body.body, inner); else walk(node.body, inner);
        return;
      }
      case 'Program': case 'BlockStatement': case 'StaticBlock': block(node.body, scopes); return;
      case 'SwitchStatement': {  // the cases of a switch are one block
        walk(node.discriminant, scopes);
        const inner = [...scopes, declared(node.cases.flatMap(c => c.consequent))];
        for (const c of node.cases) { walk(c.test, inner); for (const s of c.consequent) walk(s, inner); }
        return;
      }
      case 'ForStatement': case 'ForInStatement': case 'ForOfStatement': {
        const first = node.type === 'ForStatement' ? node.init : node.left;
        const inner = first && first.type === 'VariableDeclaration' ? [...scopes, new Set(first.declarations.flatMap(d => bound(d.id)))] : scopes;
        for (const key of ['init', 'test', 'update', 'left', 'right', 'body']) walk(node[key], inner);
        return;
      }
      case 'CatchClause': { const inner = [...scopes, new Set(bound(node.param))]; pattern(node.param, inner); walk(node.body, inner); return; }
      case 'VariableDeclarator': pattern(node.id, scopes); walk(node.init, scopes); return;
      case 'MemberExpression': walk(node.object, scopes); if (node.computed) walk(node.property, scopes); return;
      case 'Property': if (node.computed) walk(node.key, scopes); walk(node.value, scopes); return;
      case 'MethodDefinition': case 'PropertyDefinition': if (node.computed) walk(node.key, scopes); walk(node.value, scopes); return;
      case 'ClassDeclaration': case 'ClassExpression': walk(node.superClass, scopes); walk(node.body, scopes); return;
      case 'LabeledStatement': walk(node.body, scopes); return;
      case 'BreakStatement': case 'ContinueStatement': case 'MetaProperty': return;
      default:
        for (const key of Object.keys(node)) {
          if (key === 'type' || key === 'loc' || key === 'start' || key === 'end') continue;
          const value = node[key];
          if (Array.isArray(value)) for (const v of value) walk(v, scopes); else if (value && typeof value.type === 'string') walk(value, scopes);
        }
    }
  }
  walk(tree, []);
  return names;
}
const joined = process.argv.slice(2).map(file => fs.readFileSync(file, 'utf8')).join('\n');
console.log(JSON.stringify([...free(acorn.parse(joined, { ecmaVersion: 'latest', sourceType: 'script' }))].sort()));
