import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ChatTitle from './ChatTitle';

describe('chat title editor', () => {
  it('saves a normalized name with Enter and keeps the draft through polling updates', async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const view = render(<ChatTitle title="Новая игра" onSave={save} />);
    fireEvent.click(screen.getByRole('button', { name: 'Переименовать чат' }));
    const input = screen.getByRole('textbox', { name: 'Название чата' });
    fireEvent.change(input, { target: { value: '  Мой   сад ' } });
    view.rerender(<ChatTitle title="Название модели" onSave={save} />);
    expect(input).toHaveValue('  Мой   сад ');
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith('Мой сад'));
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Переименовать чат' })).toHaveFocus();
  });

  it('rejects whitespace and preserves the draft when the server rejects a save', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Не удалось сохранить'));
    render(<ChatTitle title="Игра" onSave={save} />);
    fireEvent.click(screen.getByRole('button', { name: 'Переименовать чат' }));
    const input = screen.getByRole('textbox', { name: 'Название чата' });
    expect(input).toHaveAttribute('maxlength', '160');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить название' }));
    expect(screen.getByRole('alert')).toHaveTextContent('не должно быть пустым');
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'Мой мир' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить название' }));
    await screen.findByText('Не удалось сохранить');
    expect(input).toHaveValue('Мой мир');
  });

  it('cancels with Escape without saving and uses the latest server title on reopening', () => {
    const save = vi.fn();
    const view = render(<ChatTitle title="Первое" onSave={save} />);
    fireEvent.click(screen.getByRole('button', { name: 'Переименовать чат' }));
    view.rerender(<ChatTitle title="Обновлённое" onSave={save} />);
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
    expect(screen.getByRole('heading')).toHaveTextContent('Обновлённое');
    fireEvent.click(screen.getByRole('button', { name: 'Переименовать чат' }));
    expect(screen.getByRole('textbox')).toHaveValue('Обновлённое');
    expect(save).not.toHaveBeenCalled();
  });

  it('saves even an unchanged name to mark it as the user choice', async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<ChatTitle title="Новая игра" onSave={save} />);
    fireEvent.click(screen.getByRole('button', { name: 'Переименовать чат' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить название' }));
    await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith('Новая игра'));
  });
});
