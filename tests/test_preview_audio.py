import os

import pytest

from generation.preview import with_audio_control


def test_audio_control_preserves_doctype_and_runs_before_game_scripts():
    html = '<!DOCTYPE html><html><head><script>startGame()</script></head></html>'
    controlled = with_audio_control(html, artifact_hash='fixture', app_origin='http://app.test')
    assert controlled.startswith('<!DOCTYPE html><script>')
    assert controlled.endswith(html.removeprefix('<!DOCTYPE html>'))
    assert controlled.index('gameforge:audio-ready') < controlled.index('startGame()')
    assert '__GAMEFORGE_AUDIO_CONFIG__' not in controlled


@pytest.mark.browser
def test_audio_control_mutes_existing_and_future_sources_without_resetting_the_game():
    from playwright.sync_api import sync_playwright

    instrument = """<script>
      window.outputs=[];
      const createGain=AudioContext.prototype.createGain;
      AudioContext.prototype.createGain=function(){const g=createGain.call(this);outputs.push(g);return g};
    </script>"""
    game = """<!doctype html><button id="play">Play</button><script>
      window.media=new Audio(); window.authored=new Audio(); authored.muted=true;
      window.video=document.createElement('video'); video.autoplay=true; document.body.append(video);
      window.hits=0;
      play.onclick=()=>{
        hits++; window.context=new AudioContext(); window.tone=context.createOscillator();
        tone.connect(context.destination); tone.start(); context.resume();
      };
    </script>"""
    controlled = with_audio_control(game, artifact_hash='fixture', app_origin='http://app.test')
    # Observe the real master gain without replacing any native audio behavior.
    controlled = controlled.replace('<!doctype html>', '<!doctype html>' + instrument, 1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get('GAMEFORGE_TEST_BROWSER_CHANNEL'))
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            if route.request.url.startswith('http://preview.test/'):
                route.fulfill(content_type='text/html', body=controlled)
            elif route.request.url == 'http://app.test/':
                route.fulfill(content_type='text/html', body='<iframe sandbox="allow-scripts" src="http://preview.test/game"></iframe>')
            else:
                route.abort()
        page.route('**/*', serve)
        page.goto('http://app.test/')
        frame = page.frames[1]
        frame.locator('#play').click()
        frame.wait_for_function('context.state === "running"')
        assert frame.evaluate('[media.muted,video.muted,authored.muted,outputs[0].gain.value]') == [True, True, True, 0]

        def control(muted, artifact='fixture'):
            page.evaluate("""([muted,artifactKey]) => document.querySelector('iframe').contentWindow.postMessage(
              {type:'gameforge:audio', artifactKey, muted}, '*')""", [muted, artifact])

        control(False)
        frame.wait_for_function('outputs[0].gain.value === 1')
        assert frame.evaluate('[media.muted,video.muted,authored.muted,hits]') == [False, False, True, 1]
        control(True)
        frame.wait_for_function('outputs[0].gain.value === 0')
        frame.evaluate("""() => {
          media.muted=false;
          window.later=new Audio(); later.muted=false;
          window.second=new AudioContext(); second.createOscillator().connect(second.destination);
          tone.disconnect(context.destination); tone.connect(context.destination);
          window.postMessage({type:'gameforge:audio',artifactKey:'fixture',muted:false}, '*');
        }""")
        control(False, artifact='wrong-version')
        page.wait_for_timeout(60)
        assert frame.evaluate('[media.muted,later.muted,outputs[0].gain.value,outputs[1].gain.value,hits]') == [True, True, 0, 0, 1]
        before = frame.evaluate('context.currentTime')
        page.wait_for_timeout(100)
        assert frame.evaluate('context.currentTime') > before
        control(False)
        frame.wait_for_function('outputs[1].gain.value === 1')
        assert frame.evaluate('[media.muted,later.muted,authored.muted,hits]') == [False, False, True, 1]
        assert not errors
        browser.close()
