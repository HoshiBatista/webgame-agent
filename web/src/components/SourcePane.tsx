import { useState } from 'react';
import { Copy, FileCode2 } from 'lucide-react';
import type { VersionDetail } from '../types';
import { copyText, numbers } from '../lib/format';
import { errorMessage } from '../lib/api';
import { useToast } from './ui';

export default function SourcePane({ version }: { version: VersionDetail }) {
  const files = { ...version.files, 'index.html': version.html, 'spec.json': JSON.stringify(version.spec, null, 2), 'validation.json': JSON.stringify(version.validation, null, 2) };
  const names = Object.keys(files);
  const [selected, setSelected] = useState(names.includes('engine.js') ? 'engine.js' : names[0]);
  const name = names.includes(selected) ? selected : names[0];
  const code = files[name as keyof typeof files] || '';
  const toast = useToast();
  const copy = async () => { try { await copyText(code); toast(`${name} скопирован`); } catch (e) { toast(errorMessage(e), 'error'); } };
  return <div className="source-pane"><div className="source-toolbar"><label className="source-select"><FileCode2 size={16}/><select aria-label="Файл исходного кода" value={name} onChange={event => setSelected(event.target.value)}>{names.map(file => <option key={file}>{file}</option>)}</select></label><button className="text-button" onClick={() => void copy()}><Copy size={14}/>Скопировать</button></div><pre className="source-code" tabIndex={0} aria-label={`Содержимое ${name}`}><code>{code}</code></pre><div className="source-footer"><span>{numbers(code.split('\n').length)} строк · {numbers(new TextEncoder().encode(code).length)} байт</span><span>Сохранённая версия · только чтение</span></div></div>;
}
