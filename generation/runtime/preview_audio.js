// Preview-only host controls. Saved games and offline exports are not modified.
((config) => {
  'use strict';
  let muted = true;
  const outputs = new Map();
  const media = new Set();
  const requestedMute = new WeakMap();
  const mediaPrototype = HTMLMediaElement.prototype;
  const muteProperty = Object.getOwnPropertyDescriptor(mediaPrototype, 'muted');
  const play = mediaPrototype.play;

  function track(element) {
    if (!media.has(element)) {
      media.add(element);
      if (!requestedMute.has(element)) requestedMute.set(element, muteProperty.get.call(element));
      element.addEventListener('ended', () => {
        if (!element.isConnected) media.delete(element);
      }, { once: true });
    }
    muteProperty.set.call(element, muted || requestedMute.get(element));
    return element;
  }
  Object.defineProperty(mediaPrototype, 'muted', {
    ...muteProperty,
    set(value) {
      requestedMute.set(this, Boolean(value));
      track(this);
    },
  });
  mediaPrototype.play = function (...args) {
    track(this);
    return play.apply(this, args);
  };
  const autoplay = Object.getOwnPropertyDescriptor(mediaPrototype, 'autoplay');
  Object.defineProperty(mediaPrototype, 'autoplay', {
    ...autoplay,
    set(value) { track(this); autoplay.set.call(this, value); },
  });
  window.Audio = new Proxy(window.Audio, {
    construct(target, args, newTarget) { return track(Reflect.construct(target, args, newTarget)); },
  });
  new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) {
      if (!(node instanceof Element)) continue;
      if (node instanceof HTMLMediaElement) track(node);
      node.querySelectorAll('audio,video').forEach(track);
    }
  }).observe(document, { childList: true, subtree: true });

  // A master gain silences Web Audio without stopping its clock or the game loop.
  if (window.AudioNode) {
    const connect = AudioNode.prototype.connect;
    const disconnect = AudioNode.prototype.disconnect;
    AudioNode.prototype.connect = function (...args) {
      const context = this.context;
      const destination = args[0];
      if (destination === context.destination && !('startRendering' in context)) {
        let output = outputs.get(context);
        if (!output) {
          output = context.createGain();
          output.gain.value = muted ? 0 : 1;
          connect.call(output, context.destination);
          outputs.set(context, output);
          context.addEventListener('statechange', () => {
            if (context.state === 'closed') outputs.delete(context);
          });
        }
        args[0] = output;
        connect.apply(this, args);
        return destination;
      }
      return connect.apply(this, args);
    };
    AudioNode.prototype.disconnect = function (...args) {
      if (args[0] === this.context.destination && outputs.has(this.context))
        args[0] = outputs.get(this.context);
      return disconnect.apply(this, args);
    };
  }
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (event.source !== window.parent || event.origin !== config.origin || !data ||
        data.type !== 'gameforge:audio' || data.artifactKey !== config.artifactKey ||
        typeof data.muted !== 'boolean') return;
    muted = data.muted;
    window.GameForgeExperience?.setHostControl(muted);
    for (const [context, output] of outputs) {
      if (context.state === 'closed') continue;
      const now=context.currentTime, gain=output.gain;
      gain.cancelScheduledValues(now);
      if(context.state!=='running') gain.setValueAtTime(muted?0:1,now);
      else {gain.setValueAtTime(gain.value,now);gain.linearRampToValueAtTime(muted?0:1,now+.025);}
    }
    media.forEach(track);
  });
  window.addEventListener('gameforge:experience-ready', () => window.GameForgeExperience?.setHostControl(muted));
  // Keyboard events inside the isolated game do not bubble to the host dialog.
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !event.repeat)
      window.parent.postMessage({ type: 'gameforge:escape', artifactKey: config.artifactKey }, config.origin);
  }, true);
  window.parent.postMessage({ type: 'gameforge:audio-ready', artifactKey: config.artifactKey }, config.origin);
})(__GAMEFORGE_AUDIO_CONFIG__);
