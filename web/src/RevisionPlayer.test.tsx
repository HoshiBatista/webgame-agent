import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import RevisionPlayer from './RevisionPlayer';
import { request } from './api';

vi.mock('./api', () => ({ request: vi.fn(), errorText: (error: Error) => error.message }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
});
function setup() {
  render(
    <MemoryRouter initialEntries={['/play/revision']}>
      <Routes>
        <Route path="/play/:id" element={<RevisionPlayer />} />
      </Routes>
    </MemoryRouter>,
  );
}
it('loads only the authorized revision and labels unaccepted candidates', async () => {
  vi.mocked(request).mockResolvedValue({
    id: 'revision',
    number: 2,
    title: 'Моя игра',
    accepted: false,
    preview_url: 'http://localhost:8001/preview/signed',
    artifact_hash: 'hash',
    export_url: '/api/revisions/revision/export/',
  });
  setup();
  await screen.findByText('Кандидат — ещё не принят');
  expect(request).toHaveBeenCalledWith('/api/revisions/revision/');
  expect(screen.getByTitle('Моя игра')).toHaveAttribute('sandbox', 'allow-scripts');
  expect(screen.getByRole('link', { name: 'Скачать HTML' })).toHaveAttribute(
    'href',
    '/api/revisions/revision/export/',
  );
});
it('does not mount any game when private revision access is denied', async () => {
  vi.mocked(request).mockRejectedValue(new Error('Доступ закрыт'));
  setup();
  await screen.findByRole('alert');
  expect(document.querySelectorAll('iframe')).toHaveLength(0);
});
