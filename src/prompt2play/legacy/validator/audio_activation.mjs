// Trusted decision logic; the production adapter observes/clicks real browser UI.
// It never changes audio settings through the game's implementation or fake events.
export async function activateAudioControl(adapter, {required = true} = {}) {
  const evidence = {initial_state: 'unknown', final_state: 'unknown', clicked: false};
  try {
    const state = await adapter.readState();
    evidence.initial_state = state;
    evidence.final_state = state;
    if (state === 'on') return {status: 'passed', message: 'Master sound was already enabled; no toggle performed', evidence};
    if (state !== 'off') return {status: required ? 'failed' : 'skipped',
      message: 'Master sound must expose data-testid=sound and an observable aria-pressed or native checked state', evidence};
    await adapter.click();
    evidence.clicked = true;
    await adapter.waitForEnabled();
    evidence.final_state = await adapter.readState();
    return {status: evidence.final_state === 'on' ? 'passed' : 'failed',
      message: evidence.final_state === 'on' ? 'Enabled master sound through its actual visible UI control'
        : 'The sound control did not report enabled after its activation gesture', evidence};
  } catch (error) {
    return {status: 'failed', message: 'Sound-control activation failed: ' + String(error.message).slice(0, 900), evidence};
  }
}
