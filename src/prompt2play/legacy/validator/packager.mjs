// Trusted compiler driver. No generated config, plugin, dependency install or game execution.
import {build, version} from 'esbuild';
import {existsSync} from 'node:fs';
import {resolve, relative, isAbsolute} from 'node:path';
try {
  if (version !== '0.25.12') throw new Error('Compiler version mismatch');
  const outputs = [];
  for (const entry of ['game.js', ...(existsSync('/input/style.css') ? ['style.css'] : [])]) {
    const result = await build({absWorkingDir:'/input', entryPoints:[entry], bundle:true,
      write:false, outfile:'/tmp/' + (entry === 'game.js' ? 'game.js' : 'style.css'),
      platform:'browser', target:'es2022', format:'iife', globalName:'__P2PProject',
      charset:'utf8', legalComments:'none', sourcemap:false, metafile:true,
      loader:{'.svg':'dataurl','.png':'dataurl'}, logLevel:'silent',
      plugins:[{name:'trusted-local-import-boundary', setup(builder) {
        builder.onResolve({filter:/.*/}, args => {
          if (args.kind !== 'entry-point' && !args.path.startsWith('./') && !args.path.startsWith('../'))
            return {errors:[{text:'Only relative local imports are allowed'}]};
          const path = resolve(args.resolveDir || '/input', args.path);
          const within = relative('/input', path);
          if (isAbsolute(within) || within === '..' || within.startsWith('../'))
            return {errors:[{text:'Import escapes the supplied project'}]};
          return null;
        });
      }}], tsconfigRaw:{}});
    if (Object.values(result.metafile.inputs).some(input => input.imports.some(i => i.external))) throw new Error('External dependency is forbidden');
    if (Object.keys(result.metafile.inputs).some(path => path.startsWith('../') || path.startsWith('/'))) throw new Error('Import escapes the supplied project');
    for (const file of result.outputFiles) outputs.push(file);
  }
  const script = outputs.filter(f => f.path.endsWith('.js')).map(f => f.text).join('\n');
  const css = outputs.filter(f => f.path.endsWith('.css')).map(f => f.text).join('\n');
  process.stdout.write(JSON.stringify({'game.js':script + '\nfunction createGame(ctx){return __P2PProject.createGame(ctx);}', 'style.css':css}));
} catch (error) {
  process.stderr.write(String(error.message).slice(0,1500)); process.exitCode=1;
}
