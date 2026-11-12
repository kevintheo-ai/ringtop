// The scene, its stage: the buffers, the speed written in light, the render targets, the camera and the real Spark.
'use strict';
// The stage of the scene: builds the buffers, the render targets, the camera and the real Spark, and hands them to the parts that follow.
function sceneStage(shared) {  // seam
  const { COLOR, TEXEL, canvas, gl } = shared;  // seam
  // A vertex array, filled by the function given.
  const vao = fill => { const a = gl.createVertexArray(); gl.bindVertexArray(a); fill(); gl.bindVertexArray(null); return a; };
  // A vertex buffer with its data.
  const buffer = (data, usage = gl.STATIC_DRAW) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage); return b; };
  // Says where one vertex attribute lies in the bound buffer.
  const attr = (i, size, stride, offset, divisor = 0) => { gl.enableVertexAttribArray(i); gl.vertexAttribPointer(i, size, gl.FLOAT, false, stride, offset); gl.vertexAttribDivisor(i, divisor); };
  // Sets how the bound texture is sampled: smooth, and clamped at its edges.
  const textureFilter = (filter = gl.LINEAR) => { for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, filter], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v); };

  const quad = vao(() => { buffer(new Float32Array([-1, -1, 3, -1, -1, 3])); attr(0, 2, 0, 0); });
  const ice = vao(() => { buffer(new Float32Array([-70, -70, 70, -70, -70, 70, 70, 70])); attr(0, 2, 0, 0); });
  const beamMesh = vao(() => { buffer(new Float32Array([-1, 0, 1, 0, -1, 1, 1, 1])); attr(0, 2, 0, 0); });
  const STARS = 260, MAX = 4096, OWN_SPARKS = 240;  // OWN_SPARKS: sparks a second one Spark throws for its own tokens, at most
  const starVao = vao(() => {
    const d = new Float32Array(STARS * 4);
    for (let i = 0; i < STARS; i++) {
      const a = Math.random() * TAU, y = .12 + Math.random() * .86, r = Math.sqrt(1 - y * y);
      d.set([Math.cos(a) * r, y, Math.sin(a) * r, .8 + Math.random() * 1.6], i * 4);
    }
    buffer(d); attr(0, 4, 0, 0);
  });
  const fire = new Float32Array(MAX * 12);
  shared.fireBuf = undefined;
  const fireVao = vao(() => {
    buffer(new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1])); attr(0, 2, 0, 0);
    shared.fireBuf = buffer(fire.byteLength, gl.DYNAMIC_DRAW);
    attr(1, 4, 48, 0, 1); attr(2, 4, 48, 16, 1); attr(3, 4, 48, 32, 1);
  });
  shared.laneVao = undefined; shared.sparkVao = undefined; shared.laneVerts = 0; shared.sparkVerts = 0;

  /* the digits of the speed live in the world, so the ice can mirror them */
  const HOLO_H = .46, HOLO_Y = .66;
  const glyphs = (() => {
    const chars = '0123456789,', cell = 256, c = document.createElement('canvas');
    c.width = cell * chars.length; c.height = cell;
    const x = c.getContext('2d');
    x.font = `600 ${cell * .9}px ui-rounded, system-ui, -apple-system, sans-serif`;
    x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillStyle = '#fff';
    const adv = {};
    [...chars].forEach((ch, i) => { x.fillText(ch, (i + .5) * cell, cell * .54); adv[ch] = x.measureText(ch).width / cell; });
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.generateMipmap(gl.TEXTURE_2D);
    textureFilter(gl.LINEAR_MIPMAP_LINEAR);
    return { tex, chars, adv };
  })();
  const holoData = new Float32Array(16 * 6 * 4);
  let holoBuf;
  shared.holoVerts = 0; shared.holoText = '';  // seam
  const holoVao = vao(() => { holoBuf = buffer(holoData.byteLength, gl.DYNAMIC_DRAW); attr(0, 4, 0, 0); });
  function number(text) {  // Writes the speed as digits of light into the world; the same text is not written twice.
    if (text === shared.holoText) return;
    shared.holoText = text;
    const n = glyphs.chars.length, H = HOLO_H;
    let width = 0, o = 0;
    for (const ch of text) width += (glyphs.adv[ch] || .5) * H;
    let x = -width / 2;
    for (const ch of text.slice(0, 16)) {
      const i = glyphs.chars.indexOf(ch);
      if (i < 0) continue;
      const a = glyphs.adv[ch] * H, l = x + a / 2 - H / 2, r = l + H, u0 = i / n, u1 = (i + 1) / n;
      for (const [px, py, u, v] of [[l, -H / 2, u0, 0], [r, -H / 2, u1, 0], [r, H / 2, u1, 1], [l, -H / 2, u0, 0], [r, H / 2, u1, 1], [l, H / 2, u0, 1]]) { holoData.set([px, py, u, v], o); o += 4; }
      x += a;
    }
    shared.holoVerts = o / 4;
    gl.bindBuffer(gl.ARRAY_BUFFER, holoBuf);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, holoData, 0, o);
  }

  /* offscreen: HDR scene with MSAA, half-size sky and mirror, a glow pyramid */
  function target(w, h, depth) {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, COLOR, w, h, 0, gl.RGBA, TEXEL, null);
    textureFilter();
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    let rb = null;
    if (depth) {
      rb = gl.createRenderbuffer();
      gl.bindRenderbuffer(gl.RENDERBUFFER, rb);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, rb);
    }
    return { tex, fbo, rb, w, h };
  }
  function multisampled(w, h) {  // The target the scene is drawn into with up to four samples per pixel, so edges stay smooth.
    const counts = gl.getInternalformatParameter(gl.RENDERBUFFER, COLOR, gl.SAMPLES) || [];
    const samples = Math.min(4, counts.length ? counts[0] : 0);
    const color = gl.createRenderbuffer(), depth = gl.createRenderbuffer(), fbo = gl.createFramebuffer();
    gl.bindRenderbuffer(gl.RENDERBUFFER, color);
    gl.renderbufferStorageMultisample(gl.RENDERBUFFER, samples, COLOR, w, h);
    gl.bindRenderbuffer(gl.RENDERBUFFER, depth);
    gl.renderbufferStorageMultisample(gl.RENDERBUFFER, samples, gl.DEPTH_COMPONENT24, w, h);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.RENDERBUFFER, color);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, depth);
    return { fbo, color, depth, w, h };
  }
  shared.T = null;
  function allocate(W, H) {  // Makes every render target for a canvas size and frees the ones of the size before.
    if (shared.T) {
      for (const t of [shared.T.hdr, shared.T.sky, shared.T.mirror, ...shared.T.glow]) { gl.deleteTexture(t.tex); gl.deleteFramebuffer(t.fbo); if (t.rb) gl.deleteRenderbuffer(t.rb); }
      gl.deleteFramebuffer(shared.T.ms.fbo); gl.deleteRenderbuffer(shared.T.ms.color); gl.deleteRenderbuffer(shared.T.ms.depth);
    }
    const half = v => Math.max(2, v >> 1);
    const glow = [];
    for (let i = 1; i <= 6; i++) glow.push(target(Math.max(2, W >> i), Math.max(2, H >> i)));
    shared.T = { W, H, ms: multisampled(W, H), hdr: target(W, H), sky: target(half(W), half(H)), mirror: target(half(W), half(H), true), glow };
  }

  const state = { nodes: [], chips: [], lanes: new Map(), act: 0, actGoal: 0, beam: 0, beamGoal: 0, charge: 0, chargeGoal: 0, flash: 0, mode: 'idle', tok: 0, reveal: 0, sweep: 0, burst: 0, ready: false, born: 0, pointer: [0, 0], lean: [0, 0], waves: [], finished: null, seen: false, core: null, num: 0,
    rate: 0, rateGoal: 0, spec: new Float32Array(16), specGoal: new Float32Array(16), specN: 0 };
  const parts = { x: new Float32Array(MAX), y: new Float32Array(MAX), z: new Float32Array(MAX), vx: new Float32Array(MAX), vy: new Float32Array(MAX), vz: new Float32Array(MAX), life: new Float32Array(MAX), max: new Float32Array(MAX), kind: new Uint8Array(MAX),
    hero: new Uint8Array(MAX), hops: new Uint8Array(MAX), seed: new Float32Array(MAX), next: 0, emit: 0, motes: 0 };

  const EL = .27, FOV = 42 * Math.PI / 180, F = 1 / Math.tan(FOV / 2);
  const view = { W: 1, H: 1, cssW: 1, cssH: 1, dist: 6, shift: [0, 0], sh: [0, 0], shiftOpen: 0, openDist: 2, oneSide: false, nudge: 0, hole: null, zoom: 1, pan: [0, 0], vp: new Float32Array(16), eye: [0, 0, 0], right: [1, 0, 0], up: [0, 1, 0], fwd: [0, 0, -1], sc: 1 };
  shared.quality = 0; shared.slow = 0; shared.focusNode = null; shared.focusK = 0; shared.focusGoal = 0; shared.drift = 0; shared.driftGoal = 0;

  // The product of two 4 by 4 matrices.
  function multiply(a, b) { const o = new Float32Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3]; return o; }
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];  // The difference of two points.
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];  // The cross product of two vectors.
  const norm = a => { const l = Math.hypot(...a); return [a[0] / l, a[1] / l, a[2] / l]; };  // A vector at length one.
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];  // The dot product of two vectors.

  function resize() {  // Fits canvas and camera to the window: the ring sits in the hole the panels leave, and an open Spark fits between its labels.
    const dpr = Math.min(window.devicePixelRatio || 1, [2, 1.5, 1][shared.quality]);
    const cssW = innerWidth, cssH = innerHeight, W = Math.round(cssW * dpr), H = Math.round(cssH * dpr);
    if (!shared.T || shared.T.W !== W || shared.T.H !== H) { canvas.width = W; canvas.height = H; allocate(W, H); }
    view.W = W; view.H = H; view.cssW = cssW; view.cssH = cssH;
    const hole = $('#hole').getBoundingClientRect();
    const radius = Math.max(110, Math.min(hole.width * .375, hole.height * .7));
    view.dist = F * (cssH / 2) / radius;
    view.shift = [2 * (hole.left + hole.width / 2) / cssW - 1, 1 - 2 * (hole.top + hole.height * .63) / cssH];
    view.sc = F * H / 2;
    view.hole = hole;
    view.shiftOpen = 1 - 2 * (hole.top + hole.height * .5) / cssH;
    view.oneSide = hole.width < 520;  // a narrow column: every label stands at its left edge and the machine moves to the right of them
    const labels = view.oneSide ? 176 : 330;
    view.nudge = view.oneSide ? labels / cssW : 0;
    if (shared.model && state.nodes.length) {  // the open machine has to fit beside its labels: between two columns of them, or to the right of one
      const s = state.nodes[0].scale, tall = (shared.model.stackHi - shared.model.stackLo) * s * 1.2, wide = .32 * s;
      view.openDist = F * cssH / 2 * Math.max(tall / hole.height, wide / Math.max(120, hole.width - labels));
    }
  }

  // Places the camera for this moment: a slow drift around the ring, a flight to the picked Spark, and around it once it is open. Its picture then goes through the lens: drawn larger and shifted, with the camera where it is.
  function camera(t) {
    const motion = calm.matches ? 0 : 1, lens = shared.lensAt(t);
    state.lean[0] += (state.pointer[0] - state.lean[0]) * .05;
    state.lean[1] += (state.pointer[1] - state.lean[1]) * .05;
    const open = 1 - (calm.matches ? 1 : smooth(0, 3.4, t - state.born));
    const f = smooth(0, 1, shared.focusK), spot = shared.focusNode, o = spot && shared.model ? smooth(.12, .62, spot.open) : 0;
    let yaw = motion * (Math.sin(t * .11) * (.05 + .2 * shared.drift) + state.lean[0] * .08) + open * open * 1.05;  // on the tour it looks around a little more
    let el = EL + motion * (Math.sin(t * .17) * .01 - state.lean[1] * .03) + open * open * .75;
    let d = view.dist * (1 + open * open * 1.1);
    const aim = spot ? [spot.x * f, .06 + .03 * f, spot.z * f] : [0, .06, 0];
    if (spot) {
      yaw += (spot.yaw - yaw) * f; el += (.16 - el) * f; d += (view.dist * .28 - d) * f;
      if (o) {
        yaw += (-.62 + shared.orbit[0]) * o;  // from the left: the network card and the ports stay in view
        el += (.34 + shared.orbit[1] - el) * o;
        d += (view.openDist - d) * o;
        aim[1] += (spot.atY + shared.model.stackMid * spot.scale - aim[1]) * o;
        for (let k = 0; k < 3; k++) aim[k] += lens.aim[k] * o;  // a part brought to the middle: the camera looks at it and turns around it
      }
    }
    view.sh[0] = view.shift[0] + view.nudge * o;
    view.sh[1] = view.shift[1] + (view.shiftOpen - view.shift[1]) * o;
    const eye = [aim[0] + Math.sin(yaw) * Math.cos(el) * d, aim[1] + Math.sin(el) * d, aim[2] + Math.cos(yaw) * Math.cos(el) * d];
    view.eye = eye;
    const z = norm(sub(eye, aim)), x = norm(cross([0, 1, 0], z)), y = cross(z, x);
    view.right = x; view.up = y; view.fwd = [-z[0], -z[1], -z[2]];
    const v = new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot3(x, eye), -dot3(y, eye), -dot3(z, eye), 1]);
    const near = .1, far = 200, aspect = view.W / view.H;
    const p = new Float32Array([F / aspect, 0, 0, 0, 0, F, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0]);
    view.zoom = lens.z; view.pan = [lens.z * view.sh[0] + lens.q[0], lens.z * view.sh[1] + lens.q[1]];
    const s = new Float32Array([lens.z, 0, 0, 0, 0, lens.z, 0, 0, 0, 0, 1, 0, view.pan[0], view.pan[1], 0, 1]);
    view.vp = multiply(s, multiply(p, v));
  }
  function project(p) {  // Where a point of the world lies on the page, in CSS pixels.
    const m = view.vp, w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    return [(m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12]) / w * .5 * view.cssW + view.cssW / 2, view.cssH / 2 - (m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13]) / w * .5 * view.cssH];
  }

  /* ---- the real Spark: one glTF binary, read by hand. Metres, Y up, front +Z ---- */
  const SKIN = new Set(['shell', 'foam_front', 'foam_rear', 'grip_left', 'grip_right', 'io_plate']);
  const OUTER = new Set([...SKIN, 'bottom_pad', 'bottom_cover']);  // a closed Spark only ever shows these
  const GLOWS = {  // which measurement lights which part
    gb10_die_gpu: ['gpu', [.7, .5, 1.1]], gb10_die_cpu: ['cpu', [.2, .95, .75]], gb10_package: ['gpu', [.18, .14, .36]],
    cx7: ['net', [.3, .7, 1]], qsfp_cage: ['net', [.16, .4, .6]], ssd_m2: ['ssd', [.3, 1, .6]],
  };
  for (let i = 0; i < 8; i++) GLOWS['lpddr_' + i] = ['mem', [.5, .42, 1]];
  const OPEN_S = 2.6, CLOSE_S = 1.1, EX_AT = .33, EX_STEP = .07 / OPEN_S, EX_DUR = .75 / OPEN_S, LABELS_AT = .84;
  const easeOut = x => 1 - Math.pow(1 - clamp(x), 3);  // A move that starts fast and comes to rest, from 0 to 1.
  const frontOf = o => o <= .08 ? -1 : -.006 + .056 * clamp((o - .08) / .25);  // metres up the closed machine; past .05 the whole skin is x-ray
  const backOf = o => o <= .42 ? -1 : -.006 + .056 * clamp((o - .42) / .22);  // a second front turns it back into metal once the parts have left
  let loading = null;
  shared.model = null; shared.selected = null; shared.hovered = null; shared.orbit = [0, 0]; shared.throttled = false;  // seam

  // Reads the real Spark from one glTF binary: its parts with their place when taken apart, their materials and textures, in one vertex buffer.
  async function parseModel(buf) {
    const dv = new DataView(buf);
    if (dv.getUint32(0, true) !== 0x46546c67 || dv.getUint32(8, true) !== buf.byteLength) throw new Error('not a complete GLB');
    const size = dv.getUint32(12, true), json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, size))), bin = 28 + size;
    const TYPES = { 5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array };
    const read = (i, n) => {
      const a = json.accessors[i], v = json.bufferViews[a.bufferView], Type = TYPES[a.componentType], at = bin + (v.byteOffset || 0) + (a.byteOffset || 0);
      return new Type(buf.slice(at, at + a.count * n * Type.BYTES_PER_ELEMENT));
    };
    const images = await Promise.all((json.images || []).map(im => {
      const v = json.bufferViews[im.bufferView], at = bin + (v.byteOffset || 0);
      return createImageBitmap(new Blob([new Uint8Array(buf, at, v.byteLength)], { type: im.mimeType }), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
    }));
    const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
    const white = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, white);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255, 255]));
    const made = new Map();
    const tex = (info, srgb) => {
      if (!info) return null;
      const source = json.textures[info.index].source, key = source + (srgb ? 's' : 'l');
      if (!made.has(key)) {
        const t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texImage2D(gl.TEXTURE_2D, 0, srgb ? gl.SRGB8_ALPHA8 : gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, images[source]);
        gl.generateMipmap(gl.TEXTURE_2D);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
        if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
        made.set(key, t);
      }
      return made.get(key);
    };
    const baked = json.asset.extras && json.asset.extras.lightmap;
    let light = null;
    if (baked != null) {  // the soft shadows of the open machine, rendered once in Cycles
      light = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, light);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.SRGB8_ALPHA8, gl.RGBA, gl.UNSIGNED_BYTE, images[baked]);
      gl.generateMipmap(gl.TEXTURE_2D);
      textureFilter(gl.LINEAR_MIPMAP_LINEAR);
      if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
    }
    const mats = json.materials.map(m => {
      const b = m.pbrMetallicRoughness || {};
      return { color: (b.baseColorFactor || [1, 1, 1]).slice(0, 3), metal: b.metallicFactor ?? 1, rough: b.roughnessFactor ?? 1, base: tex(b.baseColorTexture, true), mr: tex(b.metallicRoughnessTexture), norm: tex(m.normalTexture), emis: tex(m.emissiveTexture) };
    });
    let vertices = 0, indices = 0;
    for (const m of json.meshes) for (const q of m.primitives) { vertices += json.accessors[q.attributes.POSITION].count; indices += json.accessors[q.indices].count; }
    const vb = new Float32Array(vertices * 10), ib = new Uint32Array(indices);
    let vAt = 0, iAt = 0, o = 0;
    const parts = json.nodes.filter(n => n.mesh != null).map((n, index) => {
      const x = n.extras || {}, lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity], prims = [];
      for (const q of json.meshes[n.mesh].primitives) {
        const a = json.accessors[q.attributes.POSITION], pos = read(q.attributes.POSITION, 3), nor = read(q.attributes.NORMAL, 3), uv = read(q.attributes.TEXCOORD_0, 2), uv2 = q.attributes.TEXCOORD_1 == null ? null : read(q.attributes.TEXCOORD_1, 2), ids = read(q.indices, 1);
        for (let v = 0; v < a.count; v++) { vb[o++] = pos[v * 3]; vb[o++] = pos[v * 3 + 1]; vb[o++] = pos[v * 3 + 2]; vb[o++] = nor[v * 3]; vb[o++] = nor[v * 3 + 1]; vb[o++] = nor[v * 3 + 2]; vb[o++] = uv[v * 2]; vb[o++] = uv[v * 2 + 1]; vb[o++] = uv2 ? uv2[v * 2] : 0; vb[o++] = uv2 ? uv2[v * 2 + 1] : 0; }
        for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], a.min[k]); hi[k] = Math.max(hi[k], a.max[k]); }
        for (let k = 0; k < ids.length; k++) ib[iAt + k] = ids[k] + vAt;
        prims.push({ first: iAt * 4, count: ids.length, mat: mats[q.material] });
        iAt += ids.length; vAt += a.count;
      }
      return { index, name: n.name, label: x.label || n.name, T: n.translation || [0, 0, 0], X: x.explode || [0, 0, 0], order: x.order || 0, lo, hi, prims, skin: SKIN.has(n.name), outer: OUTER.has(n.name), rotor: n.name.endsWith('_rotor'), glow: GLOWS[n.name] || null, hero: n.name.startsWith('gb10') };
    });
    let model_vao, guideBuf;
    const guides = new Float32Array(parts.length * 8);
    model_vao = vao(() => {
      buffer(vb); attr(0, 3, 40, 0); attr(1, 3, 40, 12); attr(2, 2, 40, 24); attr(3, 2, 40, 32);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, ib, gl.STATIC_DRAW);
    });
    const guideVao = vao(() => { guideBuf = buffer(guides.byteLength, gl.DYNAMIC_DRAW); attr(0, 4, 0, 0); });
    const span = (f, g) => parts.reduce((a, q) => g(a, f(q)), f(parts[0]));
    const shell = parts.find(q => q.name === 'shell');
    const stackLo = span(q => q.T[1] + q.X[1] + q.lo[1], Math.min), stackHi = span(q => q.T[1] + q.X[1] + q.hi[1], Math.max);
    return {
      vao: model_vao, parts, outer: parts.filter(q => q.outer), index: new Map(parts.map(q => [q.name, q.index])), white, light: light || white, foam: mats.find(m => m.emis)?.emis || white,
      guideVao, guideBuf, guides, width: shell.hi[0] - shell.lo[0], ground: -span(q => q.T[1] + q.lo[1], Math.min), stackLo, stackHi, stackMid: (stackLo + stackHi) / 2,
    };
  }
  async function load() {  // Fetches the model of the Spark once; without it the plain box stays.
    if (!loading) loading = (async () => {
      try {
        const res = await fetch('assets/spark.glb');
        if (res.ok) shared.model = await parseModel(await res.arrayBuffer());
      } catch (e) { console.warn('No 3D model, the plain box stays:', e); }
    })();
    return loading;
  }

  function pose(p) {  // Where each part of a Spark stands for how far it is open, and the box around it.
    if (p.open <= 0 && p.posed) return;  // a closed machine stays where it was put once
    p.posed = p.open <= 0;
    for (const q of shared.model.parts) {
      const e = easeOut((p.open - EX_AT - q.order * EX_STEP) / EX_DUR), i = q.index;
      for (let k = 0; k < 3; k++) {
        const v = q.T[k] + q.X[k] * e;
        p.pose[i * 3 + k] = v; p.box[i * 6 + k] = v + q.lo[k]; p.box[i * 6 + 3 + k] = v + q.hi[k];
      }
    }
  }
  // The middle of one part of a Spark where it stands right now, as a point of its model.
  const midOf = (p, q) => [0, 1, 2].map(k => p.pose[q.index * 3 + k] + (q.lo[k] + q.hi[k]) / 2);
  // A point of the model of one Spark as a point of the world.
  function toWorld(p, q) { const x = q[0] * p.scale, z = q[2] * p.scale, c = Math.cos(p.yaw), s = Math.sin(p.yaw); return [c * x + s * z + p.x, q[1] * p.scale + p.atY, -s * x + c * z + p.z]; }
  // A point of the world as a point of the model of one Spark.
  function toModel(p, w) { const x = (w[0] - p.x) / p.scale, z = (w[2] - p.z) / p.scale, c = Math.cos(p.yaw), s = Math.sin(p.yaw); return [c * x - s * z, (w[1] - p.atY) / p.scale, s * x + c * z]; }
  function enter(box, at, a, d) {  // how far along a+d*t the ray enters this box, Infinity if it misses
    let near = -Infinity, far = Infinity;
    for (let k = 0; k < 3; k++) {
      if (Math.abs(d[k]) < 1e-9) { if (a[k] < box[at + k] || a[k] > box[at + 3 + k]) return Infinity; continue; }
      const u = (box[at + k] - a[k]) / d[k], v = (box[at + 3 + k] - a[k]) / d[k];
      near = Math.max(near, Math.min(u, v)); far = Math.min(far, Math.max(u, v));
    }
    return near <= far && far >= 0 ? Math.max(near, 0) : Infinity;
  }
  function partAt(px, py) {  // The part of the open Spark under the pointer: the nearest one the ray through it meets.
    const p = shared.focusNode;
    if (!p || !shared.model || p.open < .5) return null;
    const nx = (px / view.cssW * 2 - 1 - view.pan[0]) / view.zoom, ny = (1 - py / view.cssH * 2 - view.pan[1]) / view.zoom, ax = view.W / view.H / F, ay = 1 / F;
    const dir = [0, 1, 2].map(k => view.fwd[k] + view.right[k] * nx * ax + view.up[k] * ny * ay);
    const a = toModel(p, view.eye), b = toModel(p, view.eye.map((v, k) => v + dir[k])), d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let best = null, near = Infinity;
    for (const q of shared.model.parts) {
      if (q.skin) continue;
      const t = enter(p.box, q.index * 6, a, d);
      if (t < near) { near = t; best = q.name; }
    }
    return best;
  }

  // How far the picked Spark is open, from 0 to 1; 0 without a model.
  function opened() { return shared.focusNode && shared.model ? smooth(0, .4, shared.focusNode.open) : 0; }

  Object.assign(shared, { CLOSE_S, EX_AT, F, HOLO_H, HOLO_Y, LABELS_AT, MAX, OPEN_S, OWN_SPARKS, STARS, attr, backOf, beamMesh, buffer, camera, enter, fire, fireVao, frontOf, glyphs, holoVao, ice, load, midOf, norm, number, opened, partAt, parts, pose, project, quad, resize, starVao, state, sub, toModel, toWorld, vao, view });  // seam
}  // seam
