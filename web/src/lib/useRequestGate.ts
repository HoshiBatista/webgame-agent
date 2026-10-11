import { useEffect, useState } from 'react';
import { RequestGate } from './requests.ts';

export function useRequestGate() {
  const [gate] = useState(() => new RequestGate());
  useEffect(() => { gate.open(); return () => gate.close(); }, [gate]);
  return gate;
}
