import datetime as dt
import json
import struct
import pytest
from legiongobar.learned_games import LearnedGames
from legiongobar.native.rtss_memory import SharedBuffer,SIGNATURE


def test_game_learning_age_target_confidence_and_roundtrip(tmp_path):
    store=LearnedGames(tmp_path)
    now=dt.datetime(2026,10,13,tzinfo=dt.timezone.utc)
    game=r'C:\Games\Sample.exe'
    store.record(game,15,60,now)
    assert store.get(game.lower(),60,now)==15
    assert store.get(game,90,now)==0
    assert store.get(game,60,now+dt.timedelta(days=30))==0
    store.record(game,10,60,now)
    assert store.games[store.key(game)]['learnedTDP']==14
    assert store.games[store.key(game)]['confidence']==pytest.approx(.28)
    store.save(force=True)
    restored=LearnedGames(tmp_path)
    assert restored.games==store.games and restored.heatmaps==store.heatmaps
    restored.unreliable(game)
    assert restored.get(game,60,now)==0
    restored.record(game,20,90,now)
    assert restored.games[store.key(game)]['stableCount']==1


def test_invalid_learning_file_is_preserved(tmp_path):
    path=tmp_path/'learned_game_tdp.json'
    path.write_text('{invalid')
    store=LearnedGames(tmp_path)
    assert store.error and not store.games
    store.record(r'C:\Game.exe',15,60)
    store.save(force=True)
    assert path.read_text()=='{invalid'


def test_rtss_recent_frame_ring_wraps_and_filters_invalid_samples():
    size=5028
    data=bytearray(40+size+1024)
    struct.pack_into('<8I',data,0,SIGNATURE,0x20005,size,40,1,512,40+size,2)
    struct.pack_into('<I',data,40,123)
    struct.pack_into('<5I',data,40+264,0,100,1100,60,16667)
    ring=[16667]*1024
    ring[1023]=17000
    ring[0]=0
    ring[1]=1000001
    struct.pack_into('<1024I',data,40+924,*ring)
    struct.pack_into('<I',data,40+5020,2)
    sample=SharedBuffer(data).samples(1100)[0]
    assert len(sample['frame_times'])==256
    assert sample['frame_min']==16.667 and sample['frame_max']==17
    assert sample['frame_variance']==pytest.approx(.333)
