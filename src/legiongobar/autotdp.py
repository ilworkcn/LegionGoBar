"""Auto TDP 的保守 PID 路径；沿用上游增益、平滑窗口和逐瓦探测策略。"""
from collections import deque
import math

DEFAULTS={'AutoTDPEnabled':False,'AutoTDPTargetFPS':60,'AutoTDPMinTDP':8,'AutoTDPMaxTDP':30,
          'AutoTDPPauseWhenUnfocused':True,'AutoTDPControllerType':0}


class AutoTdp:
    def __init__(self):
        self.history=deque(maxlen=10);self.deltas=deque(maxlen=5)
        self.last_smoothed=None;self.target=None;self.integral=0.0
        self.at_target=0;self.stable=0;self.probe=None;self.samples=0
        self.next_sample=0.0;self.status='Waiting for FPS data'

    def decide(self, now, fps, current, target, minimum, maximum):
        if not math.isfinite(fps) or fps<=0:
            self.status='Waiting for FPS data';return None
        if minimum>maximum:raise ValueError('Auto TDP minimum exceeds maximum')
        if now<self.next_sample:return None
        self.next_sample=now+0.25
        if target!=self.target:
            self.history.clear();self.deltas.clear();self.last_smoothed=None
            self.integral=0;self.at_target=0;self.probe=None;self.stable=0;self.target=target
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
        self.samples+=1
        if self.samples%2:return None
        error=target-smooth;predicted_error=target-(smooth+trend*2)
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
