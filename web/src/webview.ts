/** A pasteable string literal: decoding it restores the exact exported HTML. */
export function webViewString(html: string) {
  return JSON.stringify(html)
    .replace(/</g, '\\u003c')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

async function exportedString(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      signal: controller.signal,
      headers: { Accept: 'text/html' },
    });
    if (!response.ok || !response.headers.get('content-type')?.includes('text/html'))
      throw new Error('Не удалось получить HTML игры. Обновите страницу и попробуйте ещё раз.');
    return webViewString(await response.text());
  } finally {
    clearTimeout(timer);
  }
}

export async function copyGameHtml(url: string) {
  if (!navigator.clipboard?.write && !navigator.clipboard?.writeText)
    throw new Error('Копирование недоступно. Откройте приложение по HTTPS или на localhost.');
  // Start the clipboard operation during the click, preserving Safari's user activation.
  if (navigator.clipboard.write && typeof ClipboardItem !== 'undefined') {
    const content = exportedString(url).then((text) => new Blob([text], { type: 'text/plain' }));
    void content.catch(() => {});
    await navigator.clipboard.write([new ClipboardItem({ 'text/plain': content })]);
  } else {
    await navigator.clipboard.writeText(await exportedString(url));
  }
}
