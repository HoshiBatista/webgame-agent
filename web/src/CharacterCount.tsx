import { characterCount } from './textLimits';

export default function CharacterCount({
  value,
  limit,
  id,
}: {
  value: string;
  limit: number;
  id: string;
}) {
  const count = characterCount(value);
  return (
    <p id={id} className={`character-count ${count > limit ? 'over-limit' : ''}`}>
      <span>{count > limit ? `Уберите ${count - limit} симв.` : 'Символы'}</span>
      <span>
        {count} / {limit}
      </span>
    </p>
  );
}
