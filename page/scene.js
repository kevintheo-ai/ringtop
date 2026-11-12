// The scene: a ring on black ice under the aurora, drawn with WebGL and put together from its parts. Every light in it is a measurement.
'use strict';
/* ---- the scene: a ring on black ice under the aurora. Every light in it is a measurement ---- */
const Scene = (() => { try {
  const canvas = $('#scene');
  const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, powerPreference: 'high-performance' });
  const none = () => {};  // Does nothing: what every entry of the fallback offers.
  if (!gl) return { ok: false, build: none, data: none, frame: none, lap: none, hot: none, number: none, focus: none, pick: none, load: none, opened: () => false, part: none, select: none, hover: none, orbit: none, throttle: none, drift: none, zoom: none, move: none, centre: none, home: none, zoomed: () => false, label: n => n };
  const shared = { canvas, gl };  // seam
  scenePrograms(shared);  // seam
  sceneStage(shared);  // seam
  sceneLabels(shared);  // seam
  sceneLens(shared);  // seam
  sceneWorld(shared);  // seam
  return sceneDraw(shared);  // seam
} catch (problem) {  // no scene, the page still works: the speed falls back to plain text
  console.error(problem);
  const none = () => {};  // Does nothing: what every entry of the fallback offers.
  return { ok: false, build: none, data: none, frame: none, lap: none, hot: none, number: none, focus: none, pick: none, load: none, opened: () => false, part: none, select: none, hover: none, orbit: none, throttle: none, drift: none, zoom: none, move: none, centre: none, home: none, zoomed: () => false, label: n => n };
} })();

