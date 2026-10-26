from sqlalchemy import select
from .models import Task, Prize, Participant, TaskClaim, Ledger, Draw, StaffUser
from .core import DEMO_MODE, SUPERADMIN_PASSWORD, hash_staff_password
from .models import now

TASKS = [
    dict(code="checkin", title="爱心注册", category="checkin", description="登记信息后可在线参与幸运轮抽取初始血值", max_claims=1),
    dict(code="health", title="健康检测站 · 健康体检", category="volunteer", description="现场测量血压等简易体检，获得 2 血值", blood_reward=2, max_claims=1),
    dict(code="health_pre_donation", title="健康检测站 · 献血体检", category="volunteer", description="参加献血前置体检，获得 5 血值", blood_reward=5, max_claims=1),
    dict(code="wellness", title="气血调养室", category="volunteer", description="参加中医诊断或理疗任一项，获得 5 血值，不叠加", blood_reward=5, max_claims=1),
    dict(code="donate_blood", title="生命传递门", category="volunteer", description="完成献血后获得 50 血值、35 能量和一次三倍能量道具", blood_reward=50, energy_reward=35, max_claims=1, exclusive_group="donation"),
    dict(code="ring", title="血脉圈住爱", category="game", description="套圈：每套中 1 个获得 1 能量", blood_per_attempt=1, energy_per_success=1),
    dict(code="basket", title="热血投篮手", category="game", description="投篮：每投中 1 个获得 1 能量", blood_per_attempt=1, energy_per_success=1),
    dict(code="bowling", title="热血保龄", category="game", description="水瓶保龄球：每击倒 1 个获得 1 能量", blood_per_attempt=1, energy_per_success=1),
    dict(code="match", title="热血对对碰", category="game", description="记忆翻牌：每配对 1 组获得 1 能量，可配血型或献血知识", blood_per_attempt=1, energy_per_success=1),
    dict(code="pot", title="投出热血", category="game", description="投壶：每投中 1 次获得 2 能量", blood_per_attempt=1, energy_per_success=2),
    dict(code="relay", title="聚力传红", category="game", description="用筷子传递乒乓球：每成功 1 个获得 3 能量", blood_per_attempt=1, energy_per_success=3),
    dict(code="balloon", title="红细胞大迁徙", category="game", description="用吸管吹气球：每吹起 1 个获得 3 能量", blood_per_attempt=1, energy_per_success=3),
    dict(code="darts", title="热血飞镖", category="dart", description="命中 10 环得 3 能量，9 环得 2 能量，8 环得 1 能量", blood_per_attempt=1),
]


def init_seed(db):
    for record in TASKS:
        task = db.scalar(select(Task).where(Task.code == record["code"]))
        if not task:
            db.add(Task(**record))
        elif record["code"] == "checkin" and task.description == "登记信息后到现场幸运轮抽取初始血值":
            task.title = "爱心注册"
            task.description = "登记信息后可在线参与幸运轮抽取初始血值"
    if not db.scalar(select(Prize).where(Prize.code == "doll-coins")):
        db.add(Prize(code="doll-coins", title="娃娃机游戏币 ×5", description="活动现场凭兑换码找工作人员领取", energy_price=10, stock=1000, max_per_player=None))
    if SUPERADMIN_PASSWORD and not db.scalar(select(StaffUser).where(StaffUser.username == "管理员")):
        db.add(StaffUser(username="管理员", password_hash=hash_staff_password(SUPERADMIN_PASSWORD), role="super"))
    db.commit()
    if DEMO_MODE:
        for sid, name, cls in [("DEMO001", "演示玩家·星火", "演示班级"), ("DEMO002", "演示玩家·远航", "演示班级")]:
            if not db.scalar(select(Participant).where(Participant.student_id == sid)):
                db.add(Participant(student_id=sid, name=name, class_name=cls))
        db.commit()
        checkin = db.scalar(select(Task).where(Task.code == "checkin"))
        for i, sid in enumerate(["DEMO001", "DEMO002"]):
            player = db.scalar(select(Participant).where(Participant.student_id == sid))
            if not db.scalar(select(TaskClaim).where(TaskClaim.participant_id == player.id, TaskClaim.task_id == checkin.id)):
                db.add(TaskClaim(participant_id=player.id, task_id=checkin.id, status="completed", completed_at=now()))
                # Initial leaderboard sample; records are auditable and appear in personal ledger.
                player.energy = player.energy_earned = 25 + 10 * i
                db.add(Ledger(participant_id=player.id, kind="energy", delta=player.energy, reason="演示数据初始能量", source="seed", source_id=player.id))
        db.commit()
