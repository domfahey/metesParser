async (page) => {
  // Invoke through playwright-cli run-code --filename after loading the synthetic 20x20 picker.
  // This checks actual browser mouse coordinates; it does not call the application's mapping helper.
  const equal = (actual, expected, label) => {
    if (Math.abs(Number(actual) - expected) > 1e-9) throw new Error(`${label}: ${actual} != ${expected}`);
  };
  const resetScroll = async (left, top, documentY = 0) => page.evaluate(({left, top, documentY}) => {
    window.scrollTo(0, documentY);
    const viewport = document.getElementById('viewport');
    viewport.scrollLeft = left;
    viewport.scrollTop = top;
  }, {left, top, documentY});
  const point = async (u, v) => {
    const bounds = await page.locator('#scan').boundingBox();
    const viewport = await page.locator('#viewport').boundingBox();
    const x = bounds.x + (u + 0.5) * bounds.width / 20;
    const y = bounds.y + (v + 0.5) * bounds.height / 20;
    if (x < viewport.x || x > viewport.x + viewport.width || y < viewport.y || y > viewport.y + viewport.height)
      throw new Error('Test point must be visible through the scrolled viewport');
    await page.mouse.click(x, y);
    return {bounds, viewport, client: [x, y]};
  };
  await page.setViewportSize({width: 1200, height: 900});
  await page.getByRole('radio', {name: 'Select fit-b', exact: true}).check();
  await resetScroll(0, 0);
  const first = await point(10, 0);
  equal(await page.getByRole('spinbutton', {name: 'Pixel u 2', exact: true}).inputValue(), 10, 'first native u');
  equal(await page.getByRole('spinbutton', {name: 'Pixel v 2', exact: true}).inputValue(), 0, 'first native v');
  equal(await page.getByRole('spinbutton', {name: 'Scene X 2', exact: true}).inputValue(), 120, 'unchanged scene X');
  equal(await page.getByRole('spinbutton', {name: 'Scene Y 2', exact: true}).inputValue(), 200, 'unchanged scene Y');
  await page.setViewportSize({width: 760, height: 900});
  await page.getByRole('slider', {name: 'Zoom', exact: true}).focus();
  await page.keyboard.press('Home');
  const small = (await page.locator('#scan').boundingBox()).width;
  await page.keyboard.press('End');
  equal((await page.locator('#scan').boundingBox()).width, 1000, 'zoomed CSS width');
  if (small >= 1000) throw new Error('Actual zoom control did not change image size');
  await page.getByRole('radio', {name: 'Select check-d', exact: true}).check();
  await resetScroll(200, 200, 150);
  const second = await point(10, 10);
  equal(await page.getByRole('spinbutton', {name: 'Pixel u 4', exact: true}).inputValue(), 10, 'resized/scrolled native u');
  equal(await page.getByRole('spinbutton', {name: 'Pixel v 4', exact: true}).inputValue(), 10, 'resized/scrolled native v');
  equal(await page.getByRole('spinbutton', {name: 'Scene X 4', exact: true}).inputValue(), 125, 'unchanged checkpoint X');
  equal(await page.getByRole('spinbutton', {name: 'Scene Y 4', exact: true}).inputValue(), 180, 'unchanged checkpoint Y');
  await page.getByRole('checkbox', {name: 'Snap clicks to nearest native pixel center', exact: true}).uncheck();
  await page.getByRole('radio', {name: 'Select fit-a', exact: true}).check();
  await resetScroll(0, 0);
  await point(7.25, 4.75);
  const subpixel = [Number(await page.getByRole('spinbutton', {name: 'Pixel u 1', exact: true}).inputValue()), Number(await page.getByRole('spinbutton', {name: 'Pixel v 1', exact: true}).inputValue())];
  if (Math.abs(subpixel[0] - 7.25) > 0.02 || Math.abs(subpixel[1] - 4.75) > 0.02) throw new Error('Subpixel clicks lost native coordinate precision');
  await page.getByRole('checkbox', {name: 'Snap clicks to nearest native pixel center', exact: true}).check();
  await resetScroll(0, 0);
  await point(0, 0);
  equal(await page.getByRole('spinbutton', {name: 'Pixel u 1', exact: true}).inputValue(), 0, 'restored fit native u');
  equal(await page.getByRole('spinbutton', {name: 'Pixel v 1', exact: true}).inputValue(), 0, 'restored fit native v');
  await page.getByRole('button', {name: 'Add control', exact: true}).click();
  await page.getByRole('textbox', {name: 'Control name 5', exact: true}).fill('blank-control');
  await page.getByRole('combobox', {name: 'Role 5', exact: true}).selectOption('fit');
  await page.getByRole('button', {name: 'Download controls JSON', exact: true}).click();
  if (!(await page.locator('#message').textContent()).includes('explicitly supplied and finite')) throw new Error('Blank fields were silently converted to zero');
  await page.getByRole('button', {name: 'Remove blank-control', exact: true}).click();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download controls JSON', exact: true}).click();
  const file = await downloaded;
  await file.saveAs('/private/tmp/metesparser-raster-picker-browser/controls-picked.json');
  return {first, second, resized: page.viewportSize(), download: file.suggestedFilename(), picked: [[10, 0], [10, 10]], sceneCoordinatesUnchanged: true, subpixel, blankFieldsBlocked: true};
}
