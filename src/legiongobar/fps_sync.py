"""AutoTDP 接管限帧时保存原值，只恢复本程序仍持有的设置。"""
class FpsSync:
    def __init__(self):self.previous=None;self.applied=None

    def update(self,enabled,target,rtss):
        if enabled:
            current=rtss.read()
            previous=current if self.previous is None else self.previous
            actual=rtss.set(target) if current!=target else current
            self.previous=previous;self.applied=actual
            return actual
        if self.previous is None:return None
        current=rtss.read()
        # 用户或其他软件已改过限帧时，保留其新设置。
        actual=rtss.set(self.previous) if current==self.applied else current
        self.previous=self.applied=None
        return actual
