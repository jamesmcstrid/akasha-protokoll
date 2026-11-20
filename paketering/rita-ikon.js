// Tar fram paketering/ikon-1024.png ur paketering/ikon.svg med Playwright och Chromium.
// Anvandning: node paketering/rita-ikon.js paketering/ikon.svg paketering/ikon-1024.png
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [svgFil, ut] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
  await p.setContent(`<html><body style="margin:0;background:transparent">${fs.readFileSync(svgFil, 'utf8')}</body></html>`);
  await p.locator('svg').evaluate((s) => { s.setAttribute('width', '1024'); s.setAttribute('height', '1024'); });
  // omitBackground ger genomskinlig bakgrund utanfor ikonens form
  await p.screenshot({ path: ut, omitBackground: true, clip: { x: 0, y: 0, width: 1024, height: 1024 } });
  await b.close();
})();
