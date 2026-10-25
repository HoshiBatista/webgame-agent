import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PhonePreview } from './components';

const html =
  '<!doctype html>\r\n<script>\n// Keep the newline!\nconst text = "quotes \\" and 😀";\nconst value = 2;\u2028</script>';
const exportUrl = '/api/revisions/selected-version/export/';
let fetchHtml: ReturnType<typeof vi.fn>;
let writeText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchHtml = vi
    .fn()
    .mockResolvedValue(
      new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } }),
    );
  writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('fetch', fetchHtml);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  vi.stubGlobal('ClipboardItem', undefined);
});
afterEach(() => vi.unstubAllGlobals());

function setup() {
  render(
    <PhonePreview
      url="http://localhost:8001/preview/selected"
      title="Игра"
      exportUrl={exportUrl}
    />,
  );
  return screen.getByRole('button', { name: 'Скопировать HTML для WebView' });
}

it('copies the exact selected export as one pasteable string without breaking JS comments or remounting the game', async () => {
  const copy = setup();
  const frame = screen.getByTitle('Игра');
  expect(fetchHtml).not.toHaveBeenCalled();
  fireEvent.click(copy);
  await screen.findByText('HTML скопирован одной строкой для WebView');
  expect(fetchHtml).toHaveBeenCalledWith(
    exportUrl,
    expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }),
  );
  const value = writeText.mock.calls[0][0] as string;
  expect(JSON.parse(value)).toBe(html);
  expect(value).not.toMatch(/[\r\n\u2028\u2029]/u);
  expect(value).not.toContain('</script>');
  expect(value).toContain('\\n');
  expect(writeText).toHaveBeenCalledOnce();
  expect(screen.getByTitle('Игра')).toBe(frame);
  expect(screen.queryByRole('link', { name: 'Скачать HTML' })).not.toBeInTheDocument();
});

it('shows a failed export and leaves the clipboard untouched', async () => {
  fetchHtml.mockResolvedValue(new Response('{"error":"denied"}', { status: 403 }));
  const copy = setup();
  fireEvent.click(copy);
  await screen.findByRole('alert');
  expect(writeText).not.toHaveBeenCalled();
  expect(copy).toBeEnabled();
  expect(screen.queryByText('HTML скопирован одной строкой для WebView')).not.toBeInTheDocument();
});

it('starts the asynchronous ClipboardItem write during the click before the export arrives', async () => {
  class Item {
    constructor(public content: Record<string, Promise<Blob>>) {}
  }
  vi.stubGlobal('ClipboardItem', Item);
  const write = vi.fn(async (items: Item[]) => {
    await items[0].content['text/plain'];
  });
  vi.stubGlobal('navigator', { clipboard: { write } });
  let deliver!: (response: Response) => void;
  fetchHtml.mockReturnValue(
    new Promise<Response>((resolve) => {
      deliver = resolve;
    }),
  );
  fireEvent.click(setup());
  expect(write).toHaveBeenCalledOnce();
  deliver(new Response(html, { headers: { 'Content-Type': 'text/html' } }));
  await screen.findByText('HTML скопирован одной строкой для WebView');
  const content = await write.mock.calls[0][0][0].content['text/plain'];
  expect(content.type).toBe('text/plain');
  expect(writeText).not.toHaveBeenCalled();
});

it('reports denied clipboard access without claiming success', async () => {
  writeText.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
  const copy = setup();
  fireEvent.click(copy);
  await screen.findByRole('alert');
  await waitFor(() => expect(copy).toBeEnabled());
  expect(screen.queryByText('HTML скопирован одной строкой для WebView')).not.toBeInTheDocument();
});
