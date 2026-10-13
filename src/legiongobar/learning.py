"""移植 GoTweaks 的 Q-Learning／SARSA 控制器，共用状态编码及奖励计算。"""
from collections import deque
import json
import math
import os
from pathlib import Path
import random
import tempfile


class LearningController:
    def __init__(self, directory, sarsa=False, rng=None):
        self.sarsa = sarsa
        self.path = Path(directory) / ('autotdp_sarsa_table.json' if sarsa else 'autotdp_qtable.json')
        self.rng = rng or random.Random()
        self.load_error = ''
        self.reset_session()
        self.initialize()
        if self.path.exists():
            try:
                self.load()
            except (ValueError, TypeError, KeyError, OSError) as error:
                # 保留损坏文件，避免自动保存覆盖用户原来的学习数据。
                self.load_error = str(error)

    def reset_session(self):
        self.last_state = self.last_action = -1
        self.pending = None
        self.previous_change = self.current_change = 0
        self.poor = self.stays = self.at_target = 0
        self.probe = None
        self.rewards = deque(maxlen=50)

    def initialize(self):
        self.table, self.visits = {}, {}
        for error in range(7):
            for trend in range(3):
                for level in range(10):
                    for gpu in range(4):
                        values = ([1, 1.5, 0, -1.5, -2] if error <= 2 else
                                  [.5, 1, .5, -.5, -1] if error == 3 else [-2, -1.5, 0, 1.5, 1])
                        if trend == 0:
                            values[3] += .5
                            values[4] += .3
                        elif trend == 2:
                            values[0] += .3
                            values[1] += .5
                        if gpu == 3:
                            values[3] -= .3
                            values[4] -= .5
                        elif gpu <= 1:
                            values[0] += .2
                            values[1] += .3
                        self.table[((error*3+trend)*10+level)*4+gpu] = values
        self.updates, self.alpha, self.epsilon, self.cumulative = 0, .2, .3, 0.
        self.dirty = True

    @staticmethod
    def encode(error, trend, current, minimum, maximum, gpu):
        if not all(math.isfinite(value) for value in (error,trend,current,minimum,maximum,gpu)):
            raise ValueError('Non-finite learning input')
        error_bin = 0 if error < -10 else 1 if error < -5 else 2 if error < -2 else 3 if error <= 2 else 4 if error <= 5 else 5 if error <= 10 else 6
        trend_bin = 0 if trend < -1 else 2 if trend > 1 else 1
        level = max(0,min(9,int((current-minimum)/(maximum-minimum)*10))) if maximum > minimum else 5
        gpu_bin = 0 if gpu < 50 else 1 if gpu < 80 else 2 if gpu < 95 else 3
        return ((error_bin*3+trend_bin)*10+level)*4+gpu_bin

    def q(self, state):
        if type(state) is not int or not 0 <= state < 840:
            raise ValueError('Invalid learning state')
        return self.table.setdefault(state, [-.5,-.2,.5,-.2,-.5])

    def select(self, state, error=0., current=0, minimum=4):
        self.q(state)
        action = None
        if self.sarsa:
            if abs(error) <= 2:
                self.at_target += 1
                if self.probe is None and self.at_target >= 8 and current > minimum:
                    self.probe, self.at_target, action = current, 0, 1
                elif self.probe is not None:
                    self.probe = None
            else:
                if self.probe is not None and error > 2:
                    recovery = self.probe-current
                    self.probe = None
                    if recovery > 0:
                        action = 4 if recovery >= 2 else 3
                self.at_target = 0
        if action is None:
            epsilon = max(self.epsilon,.15) if self.visits.get(state,0) < 10 else self.epsilon
            if self.rng.random() < epsilon:
                value = self.rng.random()
                limits, actions = ((.35,.55,.80,.92), (1,0,2,3,4)) if error < -3 else (((.35,.55,.80,.92),(3,4,2,1,0)) if error > 3 else ((.50,.70,.85,.93),(2,1,3,0,4)))
                action = actions[sum(value >= limit for limit in limits)]
            else:
                values = self.q(state)
                action = max(range(5),key=values.__getitem__)
        self.last_state,self.last_action = state,action
        self.previous_change,self.current_change = self.current_change,action-2
        return action-2

    def update(self, next_state, reward):
        self.q(next_state)
        if not math.isfinite(reward): raise ValueError('Non-finite learning reward')
        if self.last_state < 0 or self.last_action < 0: return
        if self.sarsa:
            pending = self.pending
            self.pending = (self.last_state,self.last_action,reward)
            if pending is None: return
            state,action,reward = pending
            next_q = self.q(self.last_state)[self.last_action]
        else:
            state,action = self.last_state,self.last_action
            next_q = max(self.q(next_state))
        values = self.q(state)
        values[action] += self.alpha*(reward+.9*next_q-values[action])
        self.visits[state] = self.visits.get(state,0)+1
        self.updates += 1
        self.alpha = max(.05,self.alpha*.999)
        self.epsilon = max(.05,self.epsilon*.995)
        self.cumulative += reward
        self.rewards.append(reward)
        self.dirty = True
        if self.updates % 100 == 0: self.save()

    def reward(self, error, previous, current, exhausted=False, achievable=0., fps=0., minimum=8, maximum=30,
               previous_change=0, efficiency=-1., previous_fps=0., frametime_variance=0.):
        change,absolute = current-previous,abs(error)
        percent = (current-minimum)/(maximum-minimum) if maximum > minimum else .5
        ceiling = exhausted and achievable > 0 and fps > 0
        delta = fps-achievable
        if ceiling:
            fps_reward = 5 if -2 <= delta <= 5 else 4 if delta > 5 else 3+delta*.4 if delta >= -5 else max(-3,delta*.3)
            direction = 2 if (delta < -3 and change > 0) or (delta >= -2 and change <= 0) else -4 if delta < -3 and change < 0 else 0
            stable = (4 if self.sarsa and delta >= -1 else 2) if delta >= -2 and change == 0 else 1 if delta >= -2 and abs(change) == 1 else 0
            near = delta >= -2
        else:
            fps_reward = 5 if absolute <= 2 else 3-(absolute-2)*.6 if absolute <= 5 else 1-(absolute-5)*.3 if absolute <= 15 else -2-min(absolute-15,30)*.1
            direction = (2 if error*change > 0 else -4 if error*change < 0 else 0) if absolute > 5 else 1 if change == 0 else 0
            stable = (4 if self.sarsa and absolute < 1 else 2) if absolute <= 3 and change == 0 else 1 if absolute <= 3 and abs(change) == 1 else 0
            near = absolute <= 2
        power = max(.2,2-current*.04) if near else 0
        if near and change < 0: power += max(.5,2.5*min(1,percent*2))
        efficiency_reward = 0
        if ceiling:
            if near and efficiency >= 0:
                if efficiency < .5:
                    efficiency_reward = -3*change if change > 0 else 2*abs(change) if change < 0 else -(percent-.5)*2 if percent > .5 else 0
                elif change == 0: efficiency_reward = 1
        elif efficiency >= 0:
            if efficiency < .5:
                efficiency_reward = -4*change if change > 0 else 3*abs(change) if change < 0 else -(percent-.3)*3 if near and percent > .3 else 0
            elif near and change == 0: efficiency_reward = 1 if efficiency < 1.5 else 2
        elif near and change == 0: efficiency_reward = (.5-percent)*2
        result = fps_reward+direction+stable+power+efficiency_reward+(-3 if previous_change*change < 0 else 0)
        if self.sarsa:
            self.stays = min(5,self.stays+1) if change == 0 and absolute <= 2 else 0
            drop = previous_fps-fps if previous_fps > 0 and fps > 0 else 0
            result += self.stays*.5 + (-10 if drop >= 15 else -6 if drop >= 10 else 0)
            if absolute <= 2 and frametime_variance > 0:
                result += 2 if frametime_variance < 2 else -1 if frametime_variance > 3 else 0
        return result

    def fallback(self, error):
        self.poor = self.poor+1 if abs(error) > 20 else 0
        return self.poor >= 7

    def reset(self):
        self.reset_session()
        self.initialize()
        if self.load_error and self.path.exists():
            backup = self.path.with_suffix('.json.invalid')
            if backup.exists(): raise FileExistsError('Previous invalid learning backup already exists')
            self.path.replace(backup)
        self.load_error = ''
        self.save()

    def save(self):
        if not self.dirty or self.load_error: return
        data = dict(Version=1,TotalUpdates=self.updates,Epsilon=self.epsilon,Alpha=self.alpha,
                    CumulativeReward=self.cumulative,QTable=self.table,StateVisits=self.visits)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        descriptor,temporary = tempfile.mkstemp(prefix=self.path.stem,suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump(data,stream,allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,self.path)
            self.dirty = False
        finally:
            Path(temporary).unlink(missing_ok=True)

    def load(self):
        if self.path.stat().st_size > 2*1024*1024: raise ValueError('Learning file is too large')
        data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if data['Version'] != 1: raise ValueError('Unsupported learning table version')
        if not isinstance(data['QTable'],dict) or not isinstance(data['StateVisits'],dict):raise ValueError('Invalid learning dictionaries')
        table = {int(key):value for key,value in data['QTable'].items()}
        visits = {int(key):value for key,value in data['StateVisits'].items()}
        if len(table) > 840 or len(visits) > 840: raise ValueError('Invalid learning table size')
        for key,row in table.items():
            if not 0 <= key < 840 or not isinstance(row,list) or len(row) != 5 or not all(type(value) in (int,float) and math.isfinite(value) for value in row):
                raise ValueError('Invalid learning table row')
        if any(not 0 <= key < 840 or type(count) is not int or count < 0 for key,count in visits.items()): raise ValueError('Invalid visit count')
        for key,low,high in (('Alpha',.05,.2),('Epsilon',.05,.3),('CumulativeReward',-1e100,1e100)):
            if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or not low <= data[key] <= high: raise ValueError('Invalid learning parameter')
        if type(data['TotalUpdates']) is not int or data['TotalUpdates'] < 0: raise ValueError('Invalid update count')
        self.table,self.visits = table,visits
        self.alpha,self.epsilon = data['Alpha'],data['Epsilon']
        self.updates,self.cumulative = data['TotalUpdates'],data['CumulativeReward']
        self.dirty = False
