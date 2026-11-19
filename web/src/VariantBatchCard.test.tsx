import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { GameVariant, VariantBatch } from './types';
import { VariantBatchCard } from './VariantBatchCard';

function variant(index: number, status: GameVariant['status']): GameVariant {
  return {
    index,
    run_id: `run-${index}`,
    root_run_id: `run-${index}`,
    status,
    stage: status,
    message: '',
    can_confirm: false,
    revision: {
      id: `revision-${index}`,
      title: `Игра ${index}`,
      accepted: status === 'succeeded',
      artifact_hash: `hash-${index}`,
      preview_url: `/preview/${index}/`,
      export_url: `/export/${index}/`,
    },
  };
}

it('waits for each active slot to finish before offering play, even with a saved candidate', () => {
  const batch: VariantBatch = {
    id: 'batch',
    prompt: 'Игра',
    created_at: '',
    selected_revision_id: null,
    variants: [
      variant(1, 'checking'),
      variant(2, 'generating'),
      variant(3, 'queued'),
      variant(4, 'unverified'),
    ],
  };
  const props = {
    batch,
    busy: false,
    choicePending: false,
    onPlay: vi.fn(),
    onCancel: vi.fn(),
    onChoose: vi.fn(),
    onReview: vi.fn(),
  };
  const { rerender } = render(<VariantBatchCard {...props} />);
  for (const index of [1, 2, 3]) {
    const row = within(screen.getByRole('listitem', { name: `Вариант ${index}` }));
    expect(row.getAllByRole('button')).toHaveLength(1);
    expect(row.getByRole('button', { name: `Остановить вариант ${index}` })).toBeEnabled();
  }
  expect(screen.getByRole('status')).toHaveTextContent('Доступно для игры 1 из 4');
  fireEvent.click(screen.getByRole('button', { name: 'Играть в вариант 4' }));
  expect(props.onPlay).toHaveBeenCalledWith(batch.variants[3]);

  const finished = [variant(1, 'succeeded'), variant(2, 'cancelled'), ...batch.variants.slice(2)];
  rerender(<VariantBatchCard {...props} batch={{ ...batch, variants: finished }} />);
  expect(screen.getByRole('status')).toHaveTextContent('Доступно для игры 2 из 4');
  expect(screen.queryByRole('button', { name: 'Остановить вариант 1' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Играть в вариант 1' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Предпросмотр варианта 2' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Остановить вариант 3' })).toBeEnabled();
});
