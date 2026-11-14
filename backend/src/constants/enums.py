from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class DeliveryStatus(str, Enum):
    pending = 'pending'      # 待领取
    claimed = 'claimed'      # 处理中
    completed = 'completed'  # 已归档
    repair = 'repair'        # 待修复
    failed = 'failed'        # 待重试
