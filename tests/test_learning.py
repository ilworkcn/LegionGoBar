import json
import math
import random
import pytest
from legiongobar.learning import LearningController
from legiongobar.autotdp import AutoTdp


def test_state_bins_and_cold_start(tmp_path):
    learner=LearningController(tmp_path)
    assert len(learner.table)==840
    assert learner.encode(-11,-2,8,8,30,0)==0
    assert learner.encode(11,2,30,8,30,100)==839
    assert learner.encode(2,1,8,8,30,50)==401
    assert learner.table[0]==pytest.approx([1.2,1.8,0,-1,-1.7])
    with pytest.raises(ValueError):learner.encode(math.nan,0,8,8,30,50)


def test_q_update_uses_next_state_maximum(tmp_path):
    learner=LearningController(tmp_path)
    learner.last_state,learner.last_action=0,2
    learner.table[0]=[0,0,1,0,0]
    learner.table[1]=[1,2,3,4,5]
    learner.update(1,2)
    assert learner.table[0][2]==pytest.approx(1+.2*(2+.9*5-1))
    assert learner.updates==1 and learner.visits[0]==1
    assert learner.alpha==pytest.approx(.1998)


def test_sarsa_uses_selected_next_action_and_deferred_reward(tmp_path):
    learner=LearningController(tmp_path,sarsa=True)
    learner.table[0]=[0,0,1,0,0]
    learner.table[1]=[1,2,3,4,9]
    learner.last_state,learner.last_action=0,2
    learner.update(1,2)
    assert learner.updates==0
    learner.last_state,learner.last_action=1,1
    learner.update(2,100)
    assert learner.table[0][2]==pytest.approx(1+.2*(2+.9*2-1))
    assert learner.cumulative==2


def test_sarsa_probe_and_recovery(tmp_path):
    learner=LearningController(tmp_path,sarsa=True,rng=random.Random(3))
    for _ in range(7):learner.select(400,0,20,8)
    assert learner.select(400,0,20,8)==-1
    assert learner.probe==20
    assert learner.select(400,5,19,8)==1
    assert learner.probe is None


def test_rewards_match_reference_examples(tmp_path):
    learner=LearningController(tmp_path)
    assert learner.reward(0,20,20)==pytest.approx(5+1+2+1.2+(.5-12/22)*2)
    assert learner.reward(20,20,21)==pytest.approx(-2.5+2)
    assert learner.reward(20,20,19,previous_change=1)==pytest.approx(-2.5-4-3)
    assert learner.reward(30,20,20,exhausted=True,achievable=40,fps=40)==pytest.approx(5+2+2+1.2)
    sarsa=LearningController(tmp_path,sarsa=True)
    assert sarsa.reward(0,20,20,previous_fps=80,fps=60,frametime_variance=1)==pytest.approx(5+1+4+1.2+(.5-12/22)*2+.5-10+2)


def test_persistence_and_corruption_do_not_destroy_data(tmp_path):
    learner=LearningController(tmp_path)
    learner.last_state,learner.last_action=0,1
    learner.update(1,3)
    learner.save()
    loaded=LearningController(tmp_path)
    assert loaded.table==learner.table and loaded.updates==1
    data=json.loads(learner.path.read_text())
    data['QTable']['0']=[float('nan')]*5
    learner.path.write_text(json.dumps(data))
    original=learner.path.read_bytes()
    invalid=LearningController(tmp_path)
    assert invalid.load_error
    invalid.save()
    assert learner.path.read_bytes()==original
    invalid.reset()
    assert learner.path.with_suffix('.json.invalid').read_bytes()==original
    assert not LearningController(tmp_path).load_error


@pytest.mark.parametrize('sarsa',[False,True])
def test_runtime_bounds_and_fallback_recovery(tmp_path,sarsa):
    learner=LearningController(tmp_path,sarsa=sarsa,rng=random.Random(7))
    controller=AutoTdp()
    current=15
    for index in range(40):
        result=controller.decide(index*.25,20,current,60,8,25,learner=learner)
        if result is not None:
            assert 8<=result<=25
            current=result
    assert controller.fallback and learner.updates>0
    for index in range(40,70):
        controller.decide(index*.25,60,current,60,8,25,learner=learner)
    assert not controller.fallback


def test_ceiling_warmup_hysteresis_and_locked_target():
    from legiongobar.autotdp import Ceiling
    ceiling=Ceiling()
    for index in range(48):ceiling.update(index*.25,40,30,60,30,50,10)
    assert not ceiling.detected
    for index in range(48,56):ceiling.update(index*.25,40,30,60,30,50,10)
    assert ceiling.detected and ceiling.effective==37 and ceiling.locked==40
    ceiling.update(14,30,28,60,30,50,10)
    assert ceiling.locked==40 and ceiling.effective==37
    for index in range(3):ceiling.update(15+index*.25,60,28,60,30,50,10)
    assert not ceiling.detected and ceiling.effective==60


def test_ceiling_target_change_and_efficiency():
    from legiongobar.autotdp import Ceiling
    ceiling=Ceiling()
    ceiling.update(0,40,20,60,30,99,10)
    ceiling.increase(40,20)
    ceiling.update(1,42,22,60,30,99,10)
    assert ceiling.efficiency==1
    ceiling.update(20,40,30,90,30,40,10)
    for index in range(20):ceiling.update(20+index*.25,40,30,90,30,40,10)
    assert not ceiling.detected
