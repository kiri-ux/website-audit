/**
 * The Global Privacy Control property, set before the page's own scripts run.
 *
 * A separate file because a MAIN-world content script registered at
 * `document_start` must be a file — `registerContentScripts` takes `js`
 * paths, not a function. That timing is the whole point: a CMP reads
 * `navigator.globalPrivacyControl` while it initialises, so a property
 * defined a moment later is a property the site never saw, and the pass would
 * report "ignored GPC" about a site that was never sent it.
 *
 * Registered only for the length of the GPC pass and unregistered after, so
 * it cannot leak into a later capture and quietly change what that one
 * measured.
 */
try {
  Object.defineProperty(navigator, "globalPrivacyControl", {
    get: () => true,
    configurable: true,
  });
} catch (e) {
  // A page that has already defined the property wins. The capture reports
  // what it managed to set rather than what it intended to.
}
