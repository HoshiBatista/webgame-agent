from copy import deepcopy

import pytest

from generation.artifacts import sha256
from generation.schema import validate_checks
from validation.check_program import compile_check
from validation.runner import compare
from validation.service import validate


def threshold(operator='gte', value=75):
    return {'id':'position','category':'regression','requirement':'Достичь нужного положения',
            'viewport':'desktop','steps':[],
            'observation':{'source':'attribute_number','selector':'#position','attribute':'data-x'},
            'expect':{'operator':operator,'value':value}}


@pytest.mark.parametrize('operator,actual,expected', [('gte',74,False),('gte',75,True),('gte',85,True),
                                                       ('lte',74,True),('lte',75,True),('lte',85,False)])
def test_numeric_thresholds_are_inclusive(operator, actual, expected):
    check=threshold(operator)
    assert compile_check(check).issue is None
    validate_checks([check], require_complete=False)
    assert compare(None,actual,check['expect']) is expected


@pytest.mark.parametrize('value', [True,False,'75',None])
@pytest.mark.parametrize('operator', ['gte','lte'])
def test_thresholds_reject_non_numeric_expectations(value, operator):
    assert compile_check(threshold(operator,value)).issue
    assert compare(None,75,{'operator':operator,'value':value}) is False
    assert compare(None,value,{'operator':operator,'value':75}) is False


@pytest.mark.parametrize('value', [float('inf'),float('-inf'),float('nan')])
def test_thresholds_reject_nonfinite_values(value):
    assert not compare(None,value,{'operator':'gte','value':75})
    assert not compare(None,75,{'operator':'lte','value':value})


def test_threshold_leaf_schema_and_boolean_player_fields():
    condition={'action':'await_condition','ms':1500,'observation':threshold()['observation'],
               'expect':threshold()['expect']}
    check=threshold()
    check['steps']=[condition]
    assert compile_check(check).issue is None
    validate_checks([check],require_complete=False)
    boolean=deepcopy(check)
    boolean['steps'][0]['observation']={'source':'experience','field':'muted'}
    assert compile_check(boolean).issue


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('broken', [False,True])
def test_route_waits_for_crossed_coordinate_and_still_requires_final_input(monkeypatch,broken):
    monkeypatch.setenv('VALIDATOR_BACKEND','native')
    html='''<canvas width="200" height="100"></canvas><p id="status">Игра</p>
    <div id="position" data-x="0">Робот</div><script>
    const ctx=document.querySelector('canvas').getContext('2d');ctx.fillRect(10,10,30,30);
    let x=0, timer=null;
    window.addEventListener('keydown',e=>{
      if(e.key==='ArrowRight'&&!timer)timer=setInterval(()=>{x+=17;position.dataset.x=x},45);
      if(e.key==='Enter'&&x>=75&&BROKEN===false)document.querySelector('#status').textContent='Победа';
    });
    window.addEventListener('keyup',()=>{clearInterval(timer);timer=null});
    </script>'''.replace('BROKEN','true' if broken else 'false')
    check=threshold()
    check.update(category='outcome',steps=[
        {'action':'key_down','key':'ArrowRight'},
        {'action':'await_condition','ms':1500,'observation':check['observation'],'expect':check['expect']},
        {'action':'key_up','key':'ArrowRight'},{'action':'checkpoint'},
        {'action':'press','key':'Enter'}],
        observation={'source':'text','selector':'#status'},expect={'operator':'eq','value':'Победа'})
    result=validate(html,[check],artifact_hash=sha256(html))
    fact=result['facts'][0]
    assert fact['status']==('failed' if broken else 'passed'), result
    assert not any(f['code']=='invalid_check' for f in result['findings']), result
    if not broken:
        assert fact['counterfactual']['after']=='Игра'


@pytest.mark.parametrize('operator', ['gte','lte'])
def test_compact_thresholds_round_trip_through_schema_and_compiler(operator):
    from generation.compact import compile_checks, validate_wire
    from tests.test_compact_generation import compact_response

    response=compact_response()
    probe=response['probes'][1]
    probe.update(operator=operator,value=1)
    probe['steps'].append({'action':'assert','observation':'hits','operator':operator,'value':1,'ms':0})
    validate_wire(response,{'operation':'create'})
    check=compile_checks(response)[1]
    assert compile_check(check).issue is None
    assert check['expect']=={'operator':operator,'value':1}
    assert check['steps'][-1]['expect']==check['expect']
