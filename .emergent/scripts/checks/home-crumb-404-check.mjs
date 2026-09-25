await page.waitForLoadState('networkidle');
await shot('dashboard-route');
const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 600));
console.log('BODYTEXT:', bodyText);
const notFound = await page.getByText(/not found|404|page (does|doesn|could) ?n.t/i).count();
console.log('NOTFOUND_MATCHES:', notFound);