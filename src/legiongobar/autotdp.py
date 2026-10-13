"""Auto TDP 的保守 PID 路径；沿用上游增益、平滑窗口和逐瓦探测策略。"""
from collections import deque
import math

DEFAULTS={'AutoTDPSyncFPSLimit':False,'AutoTDPEnabled':False,'AutoTDPTargetFPS':60,'AutoTDPMinTDP':8,'AutoTDPMaxTDP':30,
          'AutoTDPPauseWhenUnfocused':True,'AutoTDPControllerType':0}


class AutoTdp:
    def __init__(self):
        self.history=deque(maxlen=10);self.deltas=deque(maxlen=5)
        self.last_smoothed=None;self.target=None;self.integral=0.0
        self.at_target=0;self.stable=0;self.probe=None;self.samples=0
        self.next_sample=0.0;self.status='Waiting for FPS data'
        self.learner=None;self.fallback=False
        self.ceiling=Ceiling()

    def decide(self, now, fps, current, target, minimum, maximum, learner=None, gpu=50., frametime_variance=0.):
        if not math.isfinite(fps) or fps<=0:
            self.status='Waiting for FPS data';return None
        if minimum>maximum:raise ValueError('Auto TDP minimum exceeds maximum')
        if now<self.next_sample:return None
        self.next_sample=now+0.25
        if target!=self.target:
            self.history.clear();self.deltas.clear();self.last_smoothed=None
            self.integral=0;self.at_target=0;self.probe=None;self.stable=0;self.target=target
        previous_fps=self.last_smoothed or 0
        if learner is not self.learner:
            self.learner=learner;self.fallback=False
            if learner:learner.reset_session()
        average=sum(self.history)/len(self.history) if self.history else fps
        if len(self.history)>=6 and fps>average*1.5 and fps>average+50:
            self.status='FPS spike ignored';return None
        self.history.append(fps)
        total=len(self.history)*(len(self.history)+1)/2
        smooth=sum(value*(index+1) for index,value in enumerate(self.history))/total
        if self.last_smoothed is not None:
            delta=smooth-self.last_smoothed;self.deltas.append(delta)
            self.stable=self.stable+1 if abs(delta)<2 else 0
        self.last_smoothed=smooth
        trend=sum(self.deltas)/len(self.deltas) if self.deltas else 0
        self.ceiling.update(now,smooth,current,target,maximum,gpu,len(self.history))
        user_target=target
        if self.ceiling.detected:target=self.ceiling.effective
        self.samples+=1
        if self.samples%2:return None
        error=target-smooth;predicted_error=target-(smooth+trend*2)
        if learner:
            if self.fallback and abs(error)<=10:
                self.fallback=False;learner.poor=0
            if not self.fallback:
                if not self.ceiling.detected and learner.fallback(error):
                    self.fallback=True;self.status='Learning fallback to PID'
                    return max(minimum,min(maximum,current))
                state=learner.encode(error,trend,current,minimum,maximum,gpu)
                delta=learner.select(state,error,current,minimum)
                percent=(current-minimum)/(maximum-minimum) if maximum>minimum else .5
                if delta<=-2 and percent<.3:delta=-1
                if learner.sarsa and delta<0 and frametime_variance>3:delta=0
                if learner.sarsa and delta>0 and fps>target*1.15 and smooth>target:delta=0
                exhausted=self.ceiling.detected or (current>=maximum-1 and gpu<95 and user_target-smooth>2)
                if exhausted and self.ceiling.optimal>0:
                    delta=max(delta,max(minimum,self.ceiling.optimal-3)-current)
                    if smooth-self.ceiling.locked < -5 and delta<=0:delta=max(1,delta+2)
                candidate=max(minimum,min(maximum,current+delta))
                reward=learner.reward(error,current,candidate,exhausted=exhausted,achievable=self.ceiling.achievable,
                    efficiency=self.ceiling.efficiency,minimum=minimum,maximum=maximum,fps=smooth,
                    previous_change=learner.previous_change,previous_fps=previous_fps,frametime_variance=frametime_variance)
                learner.update(learner.encode(error,trend,candidate,minimum,maximum,gpu),reward)
                self.status='Learning power control'
                return candidate
        if self.ceiling.detected and self.ceiling.optimizing:
            ceiling_error=self.ceiling.achievable-smooth
            if abs(ceiling_error)<=2 and current>minimum and gpu<90:
                self.status='Optimizing ceiling power';return current-1
            if ceiling_error>3 and current<self.ceiling.optimal:
                self.status='Restoring ceiling power';return min(maximum,current+1)
            if abs(ceiling_error)<=1.5 and current<self.ceiling.optimal:self.ceiling.optimal=current
            if abs(ceiling_error)<=3:
                self.status='Ceiling power stable';return max(minimum,min(maximum,current))
        effective=(error+predicted_error)/2 if predicted_error>error else error
        if trend < -1 and error>-2:
            effective=max(effective,3);self.probe=None;self.at_target=0
        at_target=error<=1 and abs(trend)<1
        candidate=current
        if self.probe is not None:
            if error>2:
                candidate=self.probe;self.probe=None;self.at_target=0
                self.status='Restoring probe power'
                return max(minimum,min(maximum,candidate))
            if error<=1:
                self.at_target+=1
                if self.at_target>=3:self.probe=None;self.at_target=4
                self.status='Testing lower power';return max(minimum,min(maximum,current))
        elif at_target:
            self.at_target+=1
            if self.at_target>=6 and current>minimum:
                self.probe=current;self.at_target=0;self.status='Probing lower power'
                return current-1
        else:self.at_target=0
        if abs(error)<=2 and self.stable>=2:
            self.integral*=0.95;self.status='Target FPS reached'
            return max(minimum,min(maximum,current))
        self.integral=max(-30,min(30,self.integral+effective*0.25))
        adjustment=0.15*effective+0.02*self.integral-0.08*trend
        if adjustment>0:
            adjustment*=0.5;self.probe=None;self.at_target=0
        elif error>=0 or self.stable<1:adjustment=0
        else:adjustment=max(adjustment,-2 if error < -3 else -1)
        candidate=round(current+adjustment)
        candidate=max(current-(2 if error < -3 else 1),min(current+1,candidate))
        self.status='Adjusting power'
        return max(minimum,min(maximum,candidate))


class Ceiling:
    """按原版的预热、连续信号和退出迟滞识别不可达帧率。"""
    def __init__(self):
        self.started = None
        self.target = None
        self.warm_until = 0
        self.pending = None
        self.gains = deque(maxlen=4)
        self.reset()

    def reset(self):
        self.detected = False
        self.steady = self.hard = self.above = 0
        self.achievable = self.locked = 0.
        self.optimal = 0
        self.optimizing = False
        self.effective = self.target or 0

    @property
    def efficiency(self):
        return sum(self.gains)/len(self.gains) if self.gains else -1.

    def increase(self, fps, power):
        self.pending = fps,power

    def update(self, now, fps, power, target, maximum, gpu, samples):
        if self.started is None:
            self.started = now
            self.warm_until = now+12
        if target != self.target:
            self.target = target
            self.reset()
            self.warm_until = max(self.warm_until,now+6)
        if self.pending is not None and samples >= 3:
            before_fps,before_power = self.pending
            if power > before_power:self.gains.append((fps-before_fps)/(power-before_power))
            self.pending = None
        error = target-fps
        maximum_power = power >= maximum-1
        hard = maximum_power and error > 2 and (gpu < 95 or (len(self.gains)>=3 and self.efficiency<.3))
        self.steady = self.steady+1 if maximum_power and error>2 else 0
        self.hard = self.hard+1 if hard else 0
        if not self.detected and now < self.warm_until:
            self.steady = self.hard = 0
            return
        if not self.detected and (self.hard >= 8 or self.steady >= 12):
            self.detected = True
            self.achievable = self.locked = fps
            self.effective = max(30,int(fps-3))
            self.optimal = power
            self.above = self.hard = 0
        elif self.detected:
            self.achievable = max(self.achievable,.15*fps+.85*self.achievable)
            self.locked = max(self.locked,self.achievable)
            self.effective = max(self.effective,30,int(self.locked-3))
            if abs(self.locked-fps)<=2 and not self.optimizing:
                self.optimizing = True
                self.optimal = power
            self.above = self.above+1 if fps >= target-2 else 0
            if self.above >= 3:self.reset()
