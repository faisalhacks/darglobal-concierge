// Responsive sweep for the Playwright MCP `browser_run_code` tool (pass this file as `filename`).
// For every width x language x colour scheme x state it asserts: documentElement.scrollWidth <= innerWidth, no element
// of header/status/rail/chat/composer/footer extends past the viewport unless clipped by an in-viewport scroll container,
// no shell container is scrolled sideways, and <html dir> matches the language. States are measured by resizing the SAME
// page up and then down (live reflow, no reload).
// Targets: 7950 = real app (backend LLM_MODE=mock); 8787 = frontend/mock/server.mjs (cards, compare, calc fixtures).
async (page0) => {
  // Own browser context: the MCP page can be shared with other agents that navigate it.
  const ctx = await page0.context().browser().newContext({ viewport: { width: 1325, height: 900 } });
  const page = await ctx.newPage();
  const W = [320, 360, 390, 414, 600, 768, 820, 900, 1024, 1180, 1280, 1310, 1325, 1366, 1440, 1600, 1903, 1920, 2560];
  const PLANS = [
    // the real backend rate-limits per IP, so it gets one Oman question per language; the fixtures carry the rest
    { base: 'http://127.0.0.1:7950', schemes: ['dark'], asks: [['oman', 'What projects do you have in Oman?']] },
    { base: 'http://127.0.0.1:8787', schemes: ['dark', 'light'], asks: [
      ['oman', 'What projects do you have in Oman?'],
      ['toggled', 'What projects do you have in Oman?', true],
      ['cards', 'Riyadh apartments under 1,000,000'],
      ['compare', 'Compare Les Vagues and W Residences'],
      ['calc', 'What is a 20% down payment on 2,000,000?'],
      ['longAR', 'ما هي المشاريع المتوفرة في عمان؟ أريد تفاصيل كاملة عن الأسعار والمساحات والمواقع وتواريخ التسليم وخطط الدفع والمرافق المتاحة لكل مشروع في مسقط وما حولها، مع روابط المصادر الأصلية لكل معلومة https://darglobal.co.uk/projects/a-very-long-path-without-any-break-points-at-all-for-testing'],
    ] },
  ];
  const H = 900;
  const measure = () => page.evaluate(() => {
    const iw = window.innerWidth;
    const bad = [];
    // Top-level regions must sit inside [0, innerWidth] outright (no clipping allowance).
    for (const sel of ['.site-header', '.site-header__bar', '.brand', '.site-nav', '.status-line', '.home', '.rail', '.rail__headline', '.rail-photo', '.chat', '.composer', '.site-footer']) {
      const e = document.querySelector(sel); if (!e) continue;
      const r = e.getBoundingClientRect();
      if (r.width && (r.left < -0.5 || r.right > iw + 0.5)) bad.push('TOP' + sel + '[' + Math.round(r.left) + ',' + Math.round(r.right) + ']');
    }
    for (const sel of ['.site-header', '.status-line', '.rail', '.chat', '.composer', '.site-footer']) {
      const root = document.querySelector(sel);
      if (!root) continue;
      for (const el of [root, ...root.querySelectorAll('*')]) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        if (r.right <= iw + 0.5 && r.left >= -0.5) continue;
        if (el.closest('.sr-only')) continue;
        let p = el.parentElement, ok = false;
        while (p && p !== document.documentElement) {
          if (getComputedStyle(p).overflowX !== 'visible') { const pr = p.getBoundingClientRect(); if (pr.right <= iw + 0.5 && pr.left >= -0.5) { ok = true; break; } }
          p = p.parentElement;
        }
        if (!ok) bad.push(sel + '>' + (typeof el.className === 'string' ? el.className.split(' ')[0] : el.tagName) + '[' + Math.round(r.left) + ',' + Math.round(r.right) + ']');
      }
    }
    const scrolled = ['html', 'body', '.app-root', '.app-shell', '.home', '.site-header', '.rail', '.chat', '.chat__scroll'].some((s) => { const e = document.querySelector(s); return e && e.scrollLeft !== 0; });
    return { iw, sw: document.documentElement.scrollWidth, bad: [...new Set(bad)].slice(0, 4), scrolled, dir: document.documentElement.dir, lang: document.documentElement.lang };
  });
  const rows = [];
  const sweep = async (tag, lang, scheme, state) => {
    for (const w of [...W, ...[...W].reverse()]) {
      await page.setViewportSize({ width: w, height: H });
      await page.waitForTimeout(60);
      const m = await measure();
      const pass = m.sw <= m.iw && !m.bad.length && !m.scrolled && m.lang === lang && m.dir === (lang === 'ar' ? 'rtl' : 'ltr');
      rows.push({ tag, lang, scheme, state, w, pass, why: pass ? '' : `sw=${m.sw} iw=${m.iw} ${m.scrolled ? 'SCROLLED ' : ''}${m.lang}/${m.dir} ${m.bad.join(' ')}` });
    }
  };
  for (const plan of PLANS) for (const scheme of plan.schemes) for (const lang of ['en', 'ar']) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const [state, q, toggle] of [['empty', null], ...plan.asks]) {
      // 'toggled': start in the OTHER language, answer, then switch with the header toggle mid-conversation.
      const startLang = toggle ? (lang === 'ar' ? 'en' : 'ar') : lang;
      await page.setViewportSize({ width: 1325, height: H });
      await page.evaluate(() => { try { sessionStorage.clear(); } catch {} }).catch(() => {}); // forget a previous toggle
      await page.goto(plan.base + '/?lang=' + startLang);
      await page.waitForSelector('.app-root[data-ready]');
      await page.waitForTimeout(300);
      if (q) {
        await page.fill('textarea', q);
        await page.keyboard.press('Enter');
        await page.waitForSelector('.turn__actions', { timeout: 40000 });
        await page.waitForTimeout(500);
        // open every citation popover and the trace, the widest transient content
        for (const b of await page.$$('.cite__chip')) await b.click().catch(() => {});
        for (const s of await page.$$('.trace summary')) await s.click().catch(() => {});
        if (toggle) { await page.click('.lang-toggle'); await page.waitForTimeout(400); }
      }
      await sweep(plan.base.slice(-4), lang, scheme, state);
    }
  }
  const groups = {};
  for (const r of rows) {
    const k = `${r.tag} ${r.scheme.padEnd(5)} ${r.lang} ${r.state.padEnd(7)}`;
    groups[k] = groups[k] || { n: 0, fail: [] };
    groups[k].n++;
    if (!r.pass) groups[k].fail.push(`${r.w}: ${r.why}`);
  }
  const table = Object.entries(groups).map(([k, g]) => `${k} | ${g.n - g.fail.length}/${g.n} ${g.fail.length ? 'FAIL ' + g.fail.slice(0, 3).join(' ; ') : 'PASS'}`);
  await ctx.close();
  return { checks: rows.length, failed: rows.filter((r) => !r.pass).length, table: table.join('\n') };
}
