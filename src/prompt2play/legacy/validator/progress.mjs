// Only the trusted Node harness writes these files; the game has no filesystem API.
import fs from 'node:fs';

export function createProgress(requestHash, directory = '/evidence') {
  let completed = 0;
  let active = {kind: 'infrastructure', phase: 'launch'};
  const write = (name, value) => {
    const temporary = `${directory}/${name}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(value));
    fs.renameSync(temporary, `${directory}/${name}`);
  };
  const publish = () => write('progress.json', {version: 1, request_sha256: requestHash, completed, active});
  const begin = details => { active = {...active, ...details}; publish(); };
  const complete = () => { completed++; publish(); };
  publish();
  return {
    begin, complete,
    checkpoint: checks => write('partial-results.json', {request_sha256: requestHash, checks: checks.filter(check => check.status === 'failed')}),
    async run(details, operation) {
      const parent = active;
      begin(details);
      try { return await operation(); }
      finally { active = parent; complete(); }
    },
  };
}
