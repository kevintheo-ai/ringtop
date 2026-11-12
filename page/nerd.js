// Nerd mode: everything the engine says, for the people building it, put together from its two parts.
'use strict';
/* ---- nerd mode: everything the engine says, for the people building it ---- */
const Nerd = (() => {
  const shared = {};  // seam
  nerdLive(shared);  // seam
  return nerdDeep(shared);  // seam
})();

