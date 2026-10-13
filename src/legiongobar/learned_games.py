"""按可执行文件保存稳定功率及观察次数，兼容原版数据字段。"""
import datetime as dt
import json
import math
import ntpath
import os
from pathlib import Path
import tempfile
import time


class LearnedGames:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.games={}
        self.heatmaps={}
        self.dirty=False
        self.last_save=-math.inf
        self.error=''
        try:
            games=self.read('learned_game_tdp.json')
            maps=self.read('learned_game_tdp_heatmap.json')
            for path,record in games.items():
                if not ntpath.isabs(path) or not isinstance(record,dict):raise ValueError('Invalid learned game')
                for key in ('learnedTDP','targetFPS','stableCount'):
                    if type(record[key]) is not int or record[key]<0:raise ValueError('Invalid learned game number')
                if not 4<=record['learnedTDP']<=85 or not 1<=record['targetFPS']<=1000:raise ValueError('Invalid learned limits')
                if type(record['confidence']) not in (int,float) or not 0<=record['confidence']<=1:raise ValueError('Invalid confidence')
                self.timestamp(record['lastUpdated'])
                self.games[self.key(path)]=record
            for path,record in maps.items():
                if not ntpath.isabs(path) or not isinstance(record,dict):raise ValueError('Invalid heatmap')
                converted={int(power):count for power,count in record.items()}
                if any(not 4<=power<=85 or type(count) is not int or count<0 for power,count in converted.items()):raise ValueError('Invalid heatmap sample')
                self.heatmaps[self.key(path)]=converted
        except (ValueError,KeyError,TypeError,OSError) as error:
            self.games,self.heatmaps={},{}
            self.error=str(error)

    def read(self,name):
        path=self.directory/name
        if not path.exists():return {}
        if path.stat().st_size>8*1024*1024:raise ValueError('Learned game file too large')
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value,dict) or len(value)>10000:raise ValueError('Invalid learned game file')
        return value

    @staticmethod
    def key(path):return ntpath.normcase(ntpath.normpath(path))

    @staticmethod
    def timestamp(value):
        if not isinstance(value,str):raise ValueError('Invalid learned timestamp')
        result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return result.astimezone(dt.timezone.utc)

    def get(self,path,target,now=None):
        record=self.games.get(self.key(path))
        now=now or dt.datetime.now(dt.timezone.utc)
        if record and record['confidence']>=.2 and record['targetFPS']==target:
            age=(now-self.timestamp(record['lastUpdated'])).total_seconds()
            if 0<=age<30*86400:return record['learnedTDP']
        return 0

    def record(self,path,power,target,now=None):
        if self.error:return
        if not ntpath.isabs(path) or type(power) is not int or not 4<=power<=85:raise ValueError('Invalid stable power')
        key=self.key(path)
        now=now or dt.datetime.now(dt.timezone.utc)
        record=self.games.get(key)
        if not record or record['targetFPS']!=target:
            record=dict(learnedTDP=power,targetFPS=target,confidence=.2,stableCount=1)
            self.games[key]=record
        else:
            record['stableCount']+=1
            weight=min(.3,.1+record['stableCount']*.02)
            record['learnedTDP']=round((1-weight)*record['learnedTDP']+weight*power)
            record['confidence']=min(.95,record['confidence']+(1-record['confidence'])*.1)
        record.update(lastUpdated=now.isoformat(),gameName=ntpath.splitext(ntpath.basename(path))[0])
        heatmap=self.heatmaps.setdefault(key,{})
        heatmap[power]=heatmap.get(power,0)+1
        self.dirty=True
        self.save()

    def unreliable(self,path):
        record=self.games.get(self.key(path))
        if record:
            record['confidence']*=.5
            self.dirty=True
            self.save()

    def save(self,force=False):
        if not self.dirty or self.error or (not force and time.monotonic()-self.last_save<60):return
        self.directory.mkdir(parents=True,exist_ok=True)
        for name,data in (('learned_game_tdp.json',self.games),('learned_game_tdp_heatmap.json',self.heatmaps)):
            descriptor,temporary=tempfile.mkstemp(prefix=name,suffix='.tmp',dir=self.directory)
            try:
                with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                    json.dump(data,stream,ensure_ascii=False,allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary,self.directory/name)
            finally:Path(temporary).unlink(missing_ok=True)
        self.dirty=False
        self.last_save=time.monotonic()

    def summary(self,path,target):
        key=self.key(path)
        return dict(GamePath=path,TargetFPS=target,Record=dict(self.games.get(key,{})),Heatmap=dict(self.heatmaps.get(key,{})))
