// The scene, drawn: every pass of a frame, what the canvas listens to, and what Scene offers the page.
'use strict';
// The drawing of the scene: every pass of a frame, what the canvas listens to, and what Scene offers the page.
function sceneDraw(shared) {  // seam
  const { EX_AT, F, HOLO_H, HOLO_Y, LABELS_AT, STARS, backOf, beamMesh, beamP, brightP, build, camera, canvas, copyP, data, downP, drawCallouts, fillCallouts, finalP, fireP, fireVao, frontOf, gl, glyphs, guideP, holoP, holoVao, ice, iceP, laneP, load, modelP, number, opened, partAt, project, quad, resize, skyP, sparkP, starP, starVao, state, step, upP, view, wave, writeFire, xrayP, zoomBy, zoomMove, zoomOn, zoomOut, zoomPick, zoomTurned, zoomed } = shared;  // seam
  // Makes one render target the place the next pass draws into.
  function bind(t) { gl.bindFramebuffer(gl.FRAMEBUFFER, t.fbo); gl.viewport(0, 0, t.w, t.h); }
  // Puts a texture on a unit and tells the program where to find it.
  function sampler(unit, tex, loc) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(loc, unit); }

  function drawSky(flip, t) {  // The sky with its aurora, upright or mirrored for the ice; it dims while a Spark is open.
    gl.useProgram(skyP.p);
    gl.uniform3fv(skyP.u.camR, view.right);
    gl.uniform3fv(skyP.u.camU, view.up);
    gl.uniform3fv(skyP.u.camF, view.fwd);
    gl.uniform2f(skyP.u.tanH, view.W / view.H / F / view.zoom, 1 / F / view.zoom);  // the sky goes through the same lens as everything that stands in the world
    gl.uniform2fv(skyP.u.shift, view.pan);
    gl.uniform1f(skyP.u.flip, flip);
    gl.uniform1f(skyP.u.t, calm.matches ? 40 : t);
    gl.uniform1f(skyP.u.act, state.act * (1 - .8 * opened()));
    gl.uniform1f(skyP.u.studioDim, opened());
    gl.uniform3fv(skyP.u.glowDir, view.fwd);
    gl.bindVertexArray(quad);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function drawStars(flip, t, scale) {  // The stars, as points of light added on top of the sky.
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    gl.useProgram(starP.p);
    gl.uniformMatrix4fv(starP.u.vp, false, view.vp);
    gl.uniform1f(starP.u.flip, flip);
    gl.uniform1f(starP.u.sc, scale);
    gl.uniform1f(starP.u.t, t);
    gl.bindVertexArray(starVao);
    gl.drawArrays(gl.POINTS, 0, STARS);
    gl.disable(gl.BLEND);
  }
  const laneData = new Float32Array(32 * 4);
  function drawLanes(flip) {  // The lanes between the Sparks: light that runs along each link as fast and as bright as its traffic.
    gl.useProgram(laneP.p);
    gl.uniformMatrix4fv(laneP.u.vp, false, view.vp);
    gl.uniform1f(laneP.u.flip, flip);
    gl.uniform1f(laneP.u.reveal, state.reveal);
    gl.uniform1f(laneP.u.sweep, state.sweep);
    gl.uniform1f(laneP.u.burst, state.burst);
    gl.uniform1f(laneP.u.quiet, 1 - .72 * opened());
    state.lanes.forEach(l => laneData.set([l.phase, l.energy, l.second, 0], l.index * 4));
    gl.uniform4fv(laneP.u.lanes, laneData);
    gl.bindVertexArray(shared.laneVao);
    gl.drawArrays(gl.TRIANGLES, 0, shared.laneVerts);
  }
  function drawSparks(flip, t) {  // Every Spark as a plain box while the real model is not loaded, and with it every Spark of a machine the model does not show.
    gl.useProgram(sparkP.p);
    gl.uniformMatrix4fv(sparkP.u.vp, false, view.vp);
    gl.uniform3fv(sparkP.u.eye, view.eye);
    gl.uniform1f(sparkP.u.flip, flip);
    gl.uniform1f(sparkP.u.t, t);
    gl.uniform1f(sparkP.u.act, state.act);
    gl.uniform1f(sparkP.u.beam, state.beam);
    gl.bindVertexArray(shared.sparkVao);
    for (const p of state.nodes) {
      if (shared.model && !p.boxed) continue;
      gl.uniform3f(sparkP.u.at, p.x, p.atY, p.z);
      gl.uniform1f(sparkP.u.yaw, p.yaw);
      gl.uniform1f(sparkP.u.heat, p.heat);
      gl.uniform1f(sparkP.u.live, p.live);
      gl.uniform1f(sparkP.u.hot, p.hot);
      gl.uniform1f(sparkP.u.power, p.load);
      gl.uniform3fv(sparkP.u.tone, p.tone);
      gl.drawArrays(gl.TRIANGLES, 0, shared.sparkVerts);
    }
  }
  function bindMaterial(P, m) {  // Hands the program the colour and the textures of one material.
    gl.uniform3fv(P.u.color, m.color);
    gl.uniform2f(P.u.mr, m.metal, m.rough);
    gl.uniform4i(P.u.has, m.base ? 1 : 0, m.mr ? 1 : 0, m.norm ? 1 : 0, m.emis ? 1 : 0);
    const texs = [m.base, m.mr, m.norm, m.emis];  // white when unused: never the frame being drawn into
    for (let u = 0; u < 4; u++) { gl.activeTexture(gl.TEXTURE0 + u); gl.bindTexture(gl.TEXTURE_2D, texs[u] || shared.model.white); }
  }
  function modelFrame(P, flip, t) {  // What every pass over the real Spark sets first: camera, eye, mirror side and time.
    gl.useProgram(P.p);
    gl.uniformMatrix4fv(P.u.vp, false, view.vp);
    gl.uniform3fv(P.u.eye, view.eye);
    gl.uniform1f(P.u.flip, flip);
    gl.uniform1f(P.u.t, t);
    gl.bindVertexArray(shared.model.vao);
  }
  function placeModel(P, p, q) {  // Tells the program where one part of a Spark stands right now.
    gl.uniform3f(P.u.part, p.pose[q.index * 3], p.pose[q.index * 3 + 1], p.pose[q.index * 3 + 2]);
    gl.uniform1f(P.u.home, q.T[1]);
  }
  // The real Sparks, part by part: closed on the ring, taken apart when one is open, each part lit by its own measurement.
  function drawModel(flip, t) {
    const P = modelP;
    modelFrame(P, flip, t);
    for (const [name, unit] of [['tBase', 0], ['tMR', 1], ['tNorm', 2], ['tEmit', 3]]) gl.uniform1i(P.u[name], unit);
    sampler(4, shared.model.light, P.u.tLight);
    gl.uniform1f(P.u.act, state.act);
    gl.uniform1f(P.u.beam, state.beam);
    const spot = shared.focusNode ? smooth(0, .3, shared.focusNode.open) : 0;
    let bound = null;
    for (const p of state.nodes) {
      if (p.boxed) continue;  // a plain box (drawSparks)
      const front = frontOf(p.open), back = backOf(p.open), mine = p === shared.focusNode && shared.focusGoal, hero = mine ? smooth(LABELS_AT, 1, p.open) : 0, nodeDim = p === shared.focusNode ? 1 : 1 - .82 * spot;
      gl.uniform3f(P.u.at, p.x, p.atY, p.z);
      gl.uniform1f(P.u.yaw, p.yaw);
      gl.uniform1f(P.u.scale, p.scale);
      gl.uniform1f(P.u.heat, p.heat);
      gl.uniform1f(P.u.live, p.live);
      gl.uniform1f(P.u.power, p.load);
      gl.uniform3fv(P.u.tone, p.tone);
      gl.uniform1f(P.u.inspect, smooth(.2, .7, p.open));
      for (const q of p.open > 0 ? shared.model.parts : shared.model.outer) {
        if (q.skin && front >= .05 && back <= -.5) continue;  // all of it is x-ray right now
        placeModel(P, p, q);
        gl.uniform1f(P.u.scan, q.skin ? front : -1);
        gl.uniform1f(P.u.back, q.skin ? back : -1);
        gl.uniform1f(P.u.spin, q.rotor ? p.spin * (q.name.includes('left') ? 1 : -1) : 0);
        gl.uniform1f(P.u.hot, p.hot + (mine && (shared.selected === q.name || shared.hovered === q.name) ? (shared.selected === q.name ? 1 : .55) : 0));
        gl.uniform1f(P.u.dim, nodeDim * (hero && !q.hero ? 1 - .32 * hero : 1));
        const e = q.glow && p.open > .05 ? p[q.glow[0]] * p.open * p.open * .9 : 0;
        gl.uniform3f(P.u.emit, q.glow ? q.glow[1][0] * e : 0, q.glow ? q.glow[1][1] * e : 0, q.glow ? q.glow[1][2] * e : 0);
        for (const r of q.prims) {
          if (r.mat !== bound) { bindMaterial(P, r.mat); bound = r.mat; }
          gl.drawElements(gl.TRIANGLES, r.count, gl.UNSIGNED_INT, r.first);
        }
      }
    }
    gl.activeTexture(gl.TEXTURE0);
  }
  function drawXray(flip, t) {  // The skin of an opening Spark as lines of light, between the two scan fronts that run up the machine.
    if (!state.nodes.some(p => frontOf(p.open) > -.5 && backOf(p.open) < .05)) return;
    const P = xrayP;
    modelFrame(P, flip, t);
    sampler(0, shared.model.foam, P.u.tEmit);
    const spot = shared.focusNode ? smooth(0, .3, shared.focusNode.open) : 0;
    for (const p of state.nodes) {
      const front = frontOf(p.open), back = backOf(p.open);
      if (front < -.5 || back >= .05) continue;
      gl.uniform3f(P.u.at, p.x, p.atY, p.z);
      gl.uniform1f(P.u.yaw, p.yaw);
      gl.uniform1f(P.u.scale, p.scale);
      gl.uniform1f(P.u.scan, front);
      gl.uniform1f(P.u.back, back);
      gl.uniform1f(P.u.spin, 0);
      gl.uniform1f(P.u.dim, p === shared.focusNode ? 1 : 1 - .82 * spot);
      for (const q of shared.model.parts) {
        if (!q.skin) continue;
        placeModel(P, p, q);
        gl.uniform1i(P.u.foam, q.name.startsWith('foam') ? 1 : 0);
        for (const r of q.prims) gl.drawElements(gl.TRIANGLES, r.count, gl.UNSIGNED_INT, r.first);
      }
    }
  }
  function drawGuides(flip, t) {  // where each part came from
    const p = shared.focusNode;
    if (!p || p.open <= EX_AT) return;
    let o = 0;
    for (const q of shared.model.parts) {
      if (!q.X[0] && !q.X[1] && !q.X[2]) continue;
      const i = q.index * 3, far = [p.pose[i], p.pose[i + 1], p.pose[i + 2]];
      shared.model.guides.set([q.T[0], q.T[1], q.T[2], 0, far[0], far[1], far[2], Math.hypot(far[0] - q.T[0], far[1] - q.T[1], far[2] - q.T[2])], o);
      o += 8;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, shared.model.guideBuf);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, shared.model.guides, 0, o);
    gl.useProgram(guideP.p);
    gl.uniformMatrix4fv(guideP.u.vp, false, view.vp);
    gl.uniform3f(guideP.u.at, p.x, p.atY, p.z);
    gl.uniform1f(guideP.u.yaw, p.yaw);
    gl.uniform1f(guideP.u.scale, p.scale);
    gl.uniform1f(guideP.u.flip, flip);
    gl.uniform1f(guideP.u.t, t);
    gl.uniform1f(guideP.u.fade, smooth(EX_AT, .62, p.open) * (flip < 0 ? .25 : .5));
    gl.bindVertexArray(shared.model.guideVao);
    gl.drawArrays(gl.LINES, 0, o / 4);
  }
  // The beam over the core, as strong as the engine writes, with one hoop per draft position; quiet while a Spark is up close.
  function drawBeam(flip, t) {
    const quiet = 1 - shared.focusK;  // up close the machine is the subject
    if (state.beam * quiet < .004 && state.flash * quiet <= 0) return;
    gl.useProgram(beamP.p);
    gl.uniformMatrix4fv(beamP.u.vp, false, view.vp);
    gl.uniform3fv(beamP.u.right, view.right);
    gl.uniform1f(beamP.u.flip, flip);
    gl.uniform1f(beamP.u.t, t);
    gl.uniform1f(beamP.u.beam, state.beam * quiet);
    gl.uniform1f(beamP.u.flash, state.flash * quiet);
    gl.uniform1f(beamP.u.num, state.num);
    gl.uniform1f(beamP.u.rate, state.rate);
    gl.uniform1f(beamP.u.tilt, Math.max(.08, -view.fwd[1]));  // how round a ring around the beam looks from here
    gl.uniform1fv(beamP.u.spec, state.spec);
    gl.uniform1i(beamP.u.specN, state.specN);
    gl.bindVertexArray(beamMesh);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
  function drawHolo(flip, t) {  // The speed as digits of light above the core; in the ice only their glow.
    if (!shared.holoVerts || state.num < .01) return;
    gl.useProgram(holoP.p);
    gl.uniformMatrix4fv(holoP.u.vp, false, view.vp);
    gl.uniform3fv(holoP.u.right, view.right);
    gl.uniform3f(holoP.u.org, 0, HOLO_Y, 0);
    gl.uniform1f(holoP.u.flip, flip);
    gl.uniform1f(holoP.u.t, t);
    gl.uniform1f(holoP.u.fade, state.num * (flip < 0 ? .07 : 1) * (1 - shared.focusK) * (shared.throttled ? 0 : 1));  // in the ice only a glow of the digits: its waves smear them
    sampler(0, glyphs.tex, holoP.u.tex);
    gl.bindVertexArray(holoVao);
    gl.blendFunc(gl.ZERO, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform1f(holoP.u.light, 0);
    gl.drawArrays(gl.TRIANGLES, 0, shared.holoVerts);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.uniform1f(holoP.u.light, 1);
    gl.drawArrays(gl.TRIANGLES, 0, shared.holoVerts);
  }
  function drawFire(flip, alive, res) {  // Every living spark as a streak with a hot head, in one instanced call.
    if (!alive) return;
    gl.useProgram(fireP.p);
    gl.uniformMatrix4fv(fireP.u.vp, false, view.vp);
    gl.uniform2f(fireP.u.res, res.w, res.h);
    gl.uniform1f(fireP.u.flip, flip);
    gl.uniform1f(fireP.u.sc, res.h / view.H * view.sc * view.zoom);
    gl.bindVertexArray(fireVao);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, alive);
  }
  // Everything that stands on the ice, for one side of the mirror: Sparks, x-ray and guides, lanes, beam, sparks and digits.
  function stage(flip, t, alive, res) {
    gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST); gl.depthMask(true);
    gl.clear(gl.DEPTH_BUFFER_BIT);
    if (shared.model) drawModel(flip, t);
    if (!shared.model || state.nodes.some(p => p.boxed)) drawSparks(flip, t);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE); gl.depthMask(false);
    if (shared.model) { drawXray(flip, t); drawGuides(flip, t); }
    drawLanes(flip);
    drawBeam(flip, t);
    drawFire(flip, alive, res);
    drawHolo(flip, t);
    gl.depthMask(true); gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST);
  }
  const glowData = new Float32Array(8 * 4), toneData = new Float32Array(8 * 3), waveData = new Float32Array(6 * 4);
  function drawIce(t) {  // The ice: it mirrors what was drawn upside down, glows under each Spark and carries the waves.
    gl.useProgram(iceP.p);
    gl.uniformMatrix4fv(iceP.u.vp, false, view.vp);
    gl.uniform3fv(iceP.u.eye, view.eye);
    gl.uniform2f(iceP.u.res, view.W, view.H);
    gl.uniform1f(iceP.u.t, t);
    gl.uniform1f(iceP.u.act, state.act);
    gl.uniform1f(iceP.u.beam, state.beam * (1 - .9 * opened()));
    gl.uniform1f(iceP.u.charge, state.charge * (1 - .9 * opened()));
    gl.uniform1f(iceP.u.reveal, clamp(state.reveal));
    gl.uniform1f(iceP.u.studioDim, opened());
    gl.uniform1i(iceP.u.nodes, Math.min(8, state.nodes.length));
    state.nodes.slice(0, 8).forEach((p, i) => { glowData.set([p.x, p.z, p.glow * .55 + p.open * .35, 0], i * 4); toneData.set(p.tone, i * 3); });
    gl.uniform4fv(iceP.u.glow, glowData);
    gl.uniform3fv(iceP.u.tone, toneData);
    const now = performance.now() / 1000;
    waveData.fill(0);
    state.waves.forEach((w, i) => { const age = now - w.born; if (age < 3.2) waveData.set([w.x, w.z, age, w.s * (1 - age / 3.2)], i * 4); });
    gl.uniform4fv(iceP.u.waves, waveData);
    sampler(0, shared.T.mirror.tex, iceP.u.refl);
    gl.bindVertexArray(ice);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  // The picture on the screen, from the scene and its glow. While the open Spark is zoomed, what lies outside the hole goes dark, softly at the edge: the scene fills the whole window, and a zoomed machine would run on behind the head and the foot of the page.
  function drawFinal(t) {
    const r = view.W / view.cssW, b = view.hole;
    bind({ fbo: null, w: view.W, h: view.H });  // the screen itself
    gl.useProgram(finalP.p);
    sampler(0, shared.T.hdr.tex, finalP.u.scene);
    sampler(1, shared.T.glow[0].tex, finalP.u.glow);
    gl.uniform1f(finalP.u.t, t % 10); gl.uniform1f(finalP.u.grain, .022);
    gl.uniform4f(finalP.u.pane, b.left * r, (view.cssH - b.bottom) * r, b.right * r, (view.cssH - b.top) * r);
    gl.uniform2f(finalP.u.veil, smooth(1, 1.5, view.zoom), 18 * r);  // all of it: what little light is left over, the screen brightens into a ghost of the machine
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.activeTexture(gl.TEXTURE0);
  }

  // One frame: the world moves on, then sky, mirror image, the scene itself, the glow and the final picture are drawn, and the tags, chips and labels of the page are placed over it.
  function frame(now, dt) {
    if (!state.ready) return;
    const t = now / 1000;
    if (t - state.born > 8 && !shared.throttled) { shared.slow = dt > .03 ? shared.slow + 1 : Math.max(0, shared.slow - 1); if (shared.slow > 120 && shared.quality < 2) { shared.quality++; shared.slow = 0; document.documentElement.dataset.quality = shared.quality; resize(); } }
    step(dt, t);
    camera(t);
    const alive = writeFire(t);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.CULL_FACE);

    bind(shared.T.sky);
    drawSky(1, t);

    bind(shared.T.mirror);
    gl.depthMask(true); gl.clear(gl.DEPTH_BUFFER_BIT);
    drawSky(-1, t);
    drawStars(-1, t, shared.T.mirror.h / view.cssH);
    stage(-1, t, alive, shared.T.mirror);

    gl.bindFramebuffer(gl.FRAMEBUFFER, shared.T.ms.fbo);
    gl.viewport(0, 0, view.W, view.H);
    gl.useProgram(copyP.p);
    sampler(0, shared.T.sky.tex, copyP.u.tex);
    gl.bindVertexArray(quad);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    drawStars(1, t, view.H / view.cssH);
    drawIce(t);
    stage(1, t, alive, view.W ? { w: view.W, h: view.H } : shared.T.ms);

    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, shared.T.ms.fbo);
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, shared.T.hdr.fbo);
    gl.blitFramebuffer(0, 0, view.W, view.H, 0, 0, view.W, view.H, gl.COLOR_BUFFER_BIT, gl.NEAREST);
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);

    gl.bindVertexArray(quad);
    gl.useProgram(brightP.p);
    bind(shared.T.glow[0]);
    sampler(0, shared.T.hdr.tex, brightP.u.tex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.useProgram(downP.p);
    for (let i = 1; i < shared.T.glow.length; i++) {
      bind(shared.T.glow[i]);
      sampler(0, shared.T.glow[i - 1].tex, downP.u.tex);
      gl.uniform2f(downP.u.px, .5 / shared.T.glow[i - 1].w, .5 / shared.T.glow[i - 1].h);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    gl.useProgram(upP.p);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    for (let i = shared.T.glow.length - 2; i >= 0; i--) {
      bind(shared.T.glow[i]);
      sampler(0, shared.T.glow[i + 1].tex, upP.u.tex);
      gl.uniform2f(upP.u.px, .5 / shared.T.glow[i + 1].w, .5 / shared.T.glow[i + 1].h);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    gl.disable(gl.BLEND);

    drawFinal(t);

    const age = t - state.born;
    for (const p of state.nodes) {
      const [x, y] = project([p.x, p.side * .34 + .05, p.z]);
      if (!p.tagW) p.tagW = p.tag.offsetWidth;
      const outward = p.x < 0 ? -p.tagW + 26 : -26, down = p.z > 0;  // on the outside of the ring: the middle belongs to the speed
      const hole = view.hole, tagX = hole ? Math.max(hole.left + 2, Math.min(hole.right - p.tagW - 2, x + outward)) : x + outward;
      p.tag.style.transform = `translate3d(${tagX.toFixed(1)}px,${(down ? y + 58 : y - 46).toFixed(1)}px,0)`;
      p.tag.style.opacity = ((calm.matches ? 1 : smooth(2.2 + p.order * .1, 2.8 + p.order * .1, age)) * (1 - shared.focusK)).toFixed(2);
      p.tag.style.pointerEvents = shared.focusK > .5 ? 'none' : '';
    }
    const reveal = (calm.matches ? 1 : smooth(3, 3.8, age)) * (1 - shared.focusK);
    const [cx, cy] = project([0, HOLO_Y, 0]), [, top] = project([0, HOLO_Y + HOLO_H * .5, 0]), [, foot] = project([0, HOLO_Y - HOLO_H * .5, 0]);
    const lift = shared.holoText ? cy - top + 6 : 14, drop = shared.holoText ? foot - cy + 8 : 16;
    const core = state.core, words = core.sub.textContent;
    if (words !== core.words) { core.words = words; core.subW = words ? core.sub.offsetWidth : 0; }
    for (const c of state.chips) {
      let [x, y] = project(c.world);
      if (!c.w) c.w = c.el.offsetWidth;
      if (core.subW && Math.abs(x - cx) < (c.w + core.subW) / 2 + 4 && y + 9 > cy + drop - 3 && y - 9 < cy + drop + 23) y = cy + drop + 33;  // the far link gives way to the line under the speed
      c.el.style.transform = `translate3d(${(x - c.w / 2).toFixed(1)}px,${(y - 9).toFixed(1)}px,0)`;
      c.el.style.opacity = reveal.toFixed(2);
    }
    state.core.pill.style.transform = `translate3d(${cx.toFixed(1)}px,${(cy - lift - 26).toFixed(1)}px,0) translateX(-50%)`;
    state.core.sub.style.transform = `translate3d(${cx.toFixed(1)}px,${(cy + drop).toFixed(1)}px,0) translateX(-50%)`;
    const shown = ((calm.matches ? 1 : smooth(2.6, 3.2, age)) * (1 - shared.focusK)).toFixed(2);
    state.core.pill.style.opacity = shown; state.core.sub.style.opacity = shown;
    const [hx, hy] = project([0, 1.215, 0]);                    // beside the hoops on the beam
    core.hoops.style.transform = `translate3d(${(hx + 22).toFixed(1)}px,${(hy - 9).toFixed(1)}px,0)`;
    core.hoops.style.opacity = (+shown * clamp(state.beam * 3)).toFixed(2);  // an empty sign shows nothing; "0 → 0 %" is a reading and stays
    drawCallouts();
  }

  canvas.addEventListener('webglcontextlost', e => e.preventDefault());
  canvas.addEventListener('webglcontextrestored', () => location.reload());
  addEventListener('resize', resize);
  addEventListener('pointermove', e => { state.pointer = [e.clientX / innerWidth * 2 - 1, e.clientY / innerHeight * 2 - 1]; }, { passive: true });
  document.body.classList.add('gl');
  return {
    ok: true, build, data, frame, number, load,
    focus(name) {
      const p = state.nodes.find(x => x.name === name);
      for (const q of state.nodes) q.openGoal = q === p && shared.model && !q.boxed ? 1 : 0;  // a plain box does not open
      shared.selected = null; shared.hovered = null; shared.orbit = [0, 0];
      zoomOut();  // a Spark opens with the view every Spark opens with
      if (p) { shared.focusNode = p; shared.focusGoal = 1; fillCallouts(); } else shared.focusGoal = 0;
    },
    opened: () => !!(shared.model && shared.focusNode && shared.focusGoal && shared.focusNode.open >= .5),
    part: partAt,
    label: name => { const i = shared.model && shared.model.index.get(name); return i === undefined || i === false || i == null ? name : shared.model.parts[i].label; },
    select(name) { shared.selected = name; zoomPick(name); },
    hover(name) { shared.hovered = name; },
    orbit(dx, dy) { zoomTurned(); shared.orbit = [shared.orbit[0] - dx * .008, clamp(shared.orbit[1] + dy * .005, -.3, .6)]; },
    zoom: zoomBy, move: zoomMove, centre: zoomOn, home: zoomOut, zoomed,
    throttle(on) { shared.throttled = on; shared.slow = 0; },
    drift(on) { shared.driftGoal = on ? 1 : 0; },
    pick(px, py) {
      let best = null, near = Infinity;
      for (const p of state.nodes) {
        const wide = p.open > .3, y = wide ? p.atY + shared.model.stackMid * p.scale : p.side * .17, r = wide ? .5 : p.side * .75;
        const c = project([p.x, y, p.z]), edge = project([p.x + view.right[0] * r, y, p.z + view.right[2] * r]);
        const dist = Math.hypot(px - c[0], py - c[1]);
        if (dist < Math.hypot(edge[0] - c[0], edge[1] - c[1]) && dist < near) { near = dist; best = p.name; }
      }
      return best;
    },
    lap() { state.burst = 1; state.sweep = 0; wave(0, 0, .8); },
    hot(name, on) { const p = state.nodes.find(x => x.name === name); if (p) { p.hotGoal = on ? 1 : 0; p.tag.classList.toggle('hot', on); } },
  };
}  // seam
