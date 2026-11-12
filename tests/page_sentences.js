// Which functions of the page say what they are for, and how long each one is. Prints one JSON object:
//   named: every function a reader meets first, as { file, name, line, said }. said: a comment stands on its head line
//          or alone on the line above it. The marker of a seam between two parts and the banner of a section are none.
//   sizes: every function with a name, as { file, name, line, statements }, counted the way a linter counts them:
//          every statement of its body and of the blocks in it, without the bodies of the functions inside it.
//   node --expose-internals page_sentences.js FILE.js [FILE.js ...]
// A reader meets first: the functions at the top of a script, and at the top of every block that stands for a module:
// a part (a function at the top that takes `shared`) and a block that runs at once to fill a const (Tour, Time, History).
// Uses the parser node ships (acorn), nothing is installed.
'use strict';
const acorn = require('internal/deps/acorn/acorn/dist/acorn'), fs = require('node:fs'), path = require('node:path');

const isFunction = n => !!n && (n.type === 'ArrowFunctionExpression' || n.type === 'FunctionExpression');
// the body of a block that runs at once: `(() => { ... })()`, or null
const atOnce = n => n && n.type === 'CallExpression' && isFunction(n.callee) && n.callee.body.type === 'BlockStatement' ? n.callee.body.body : null;

function statements(body) {  // how many statements a list of statements holds, the blocks in it counted too
  let count = 0;
  const each = list => { for (const s of list) one(s); };
  function one(s) {
    if (!s || s.type === 'EmptyStatement') return;
    if (s.type === 'BlockStatement') return each(s.body);
    if (s.type === 'LabeledStatement') return one(s.body);
    count++;
    if (s.type === 'IfStatement') { one(s.consequent); one(s.alternate); }
    else if (s.type === 'TryStatement') { one(s.block); if (s.handler) one(s.handler.body); one(s.finalizer); }
    else if (s.type === 'SwitchStatement') for (const c of s.cases) each(c.consequent);
    else if (s.body && !s.type.startsWith('Function') && s.type !== 'ClassDeclaration') one(s.body);  // the loops
  }
  each(body);
  return count;
}

function read(file) {
  const text = fs.readFileSync(file, 'utf8'), lines = text.split('\n'), comments = [], named = [], sizes = [];
  const tree = acorn.parse(text, { ecmaVersion: 'latest', sourceType: 'script', locations: true, onComment: comments });
  const alone = c => lines[c.loc.start.line - 1].slice(0, c.loc.start.column).trim() === '';  // nothing but the comment begins its line
  const sentence = c => !/^\s*seam\s*$/.test(c.value) && !/^\s*-{3,}.*-{3,}\s*$/.test(c.value);  // nor is the banner of a section
  const said = node => comments.some(c => sentence(c) && (
    (c.loc.start.line === node.loc.start.line && c.start > node.start) || (c.loc.end.line === node.loc.start.line - 1 && alone(c))));
  const name = path.basename(file);
  const note = (id, node) => named.push({ file: name, name: id, line: node.loc.start.line, said: said(node) });
  function module(list) {  // the statements of a script, a part, or a block that runs at once
    for (const s of list) {
      if (s.type === 'TryStatement') { module(s.block.body); if (s.handler) module(s.handler.body.body); continue; }
      if (s.type === 'FunctionDeclaration') {
        note(s.id.name, s);
        if (s.params[0] && s.params[0].name === 'shared') module(s.body.body);  // a part of a bigger block
      } else if (s.type === 'VariableDeclaration') {
        for (const d of s.declarations) {
          const one = s.declarations.length === 1 ? s : d;  // a line of several names: each on the line it begins
          if (isFunction(d.init) && d.id.type === 'Identifier') note(d.id.name, one);
          else if (atOnce(d.init)) module(atOnce(d.init));
        }
      }
    }
  }
  module(tree.body);
  (function walk(node, label) {  // every function with a name, wherever it stands
    if (!node || typeof node.type !== 'string') return;
    if (node.type === 'FunctionDeclaration' || isFunction(node)) {
      const id = node.id ? node.id.name : label;
      if (id && node.body.type === 'BlockStatement') sizes.push({ file: name, name: id, line: node.loc.start.line, statements: statements(node.body.body) });
    }
    for (const key of Object.keys(node)) {
      if (key === 'type' || key === 'loc' || key === 'start' || key === 'end') continue;
      const value = node[key];
      const tag = node.type === 'VariableDeclarator' && key === 'init' && node.id.type === 'Identifier' ? node.id.name
        : node.type === 'Property' && key === 'value' && node.key.type === 'Identifier' ? node.key.name : null;
      if (Array.isArray(value)) for (const v of value) walk(v, null); else if (value && typeof value.type === 'string') walk(value, tag);
    }
  })(tree, null);
  return { named, sizes };
}

const all = process.argv.slice(2).map(read);
console.log(JSON.stringify({ named: all.flatMap(a => a.named), sizes: all.flatMap(a => a.sizes) }));
