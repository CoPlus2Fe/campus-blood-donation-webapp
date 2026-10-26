import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

DB_DIR = tempfile.TemporaryDirectory(prefix='blood-drive-tests-')
DB_PATH = Path(DB_DIR.name) / 'test.db'
os.environ['DEMO_MODE'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:///' + str(DB_PATH)
os.environ['APP_SECRET'] = 'local-test-secret-abc1234567890123456789'
os.environ['SUPERADMIN_PASSWORD'] = 'local-test-admin-password'
os.environ['PUBLIC_BASE_URL'] = 'http://testserver'
from app import main as app_main
from app.main import app
from app.core import SessionLocal
from app.models import Participant, Ledger, Draw, DrawAudit, BoostAudit, StaffUser, TaskClaim
from sqlalchemy import select

H = {'X-Requested-With': 'BloodQuest'}

@pytest.fixture(autouse=True)
def event_clock(monkeypatch):
    monkeypatch.setattr(app_main, 'now', lambda: datetime(2026, 10, 28, 7, 1, tzinfo=timezone.utc))

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c


def player(c):
    r = c.post('/api/auth/demo?student_id=DEMO001', headers=H)
    assert r.status_code == 200, r.text


def staff(c):
    r = c.post('/api/admin/login', json={'username':'管理员','password':'local-test-admin-password'}, headers=H)
    assert r.status_code == 200, r.text


def test_player_draw_only_once_and_real_balance(client):
    player(client)
    initial=client.get('/api/me').json()
    assert client.get('/api/draw').json()['can_spin'] is True
    first=client.post('/api/draw', headers=H)
    assert first.status_code == 200, first.text
    amount=first.json()['blood']
    assert amount in [10, 15, 20, 25, 30]
    again=client.post('/api/draw', headers=H)
    assert again.status_code == 409
    assert client.get('/api/me').json()['blood'] == initial['blood'] + amount
    with SessionLocal() as db:
        p=db.scalar(select(Participant).where(Participant.student_id == 'DEMO001'))
        assert len(db.scalars(select(Draw).where(Draw.participant_id==p.id)).all()) == 1
        assert len(db.scalars(select(Ledger).where(Ledger.participant_id==p.id, Ledger.source=='draw')).all())==1


def test_task_staff_verification_and_blood_check(client):
    player(client)
    tasks=client.get('/api/tasks').json()
    health=next(x for x in tasks if x['title']=='健康检测站 · 健康体检')
    assert client.post(f"/api/tasks/{health['id']}/claim", headers=H).status_code==200
    assert client.post(f"/api/tasks/{health['id']}/claim", headers=H).status_code==409
    staff(client)
    claim=next(x for x in client.get('/api/admin/claims').json() if x['title']=='健康检测站 · 健康体检')
    assert client.post(f"/api/admin/claims/{claim['id']}/complete", json={'attempts':0,'successes':0},headers=H).status_code==200
    assert client.post(f"/api/admin/claims/{claim['id']}/complete", json={'attempts':0,'successes':0},headers=H).status_code==409
    player(client)
    assert client.get('/api/me').json()['blood']>=2
    task=next(x for x in client.get('/api/tasks').json() if x['title']=='血脉圈住爱')
    assert client.post(f"/api/tasks/{task['id']}/claim",headers=H).status_code==200
    staff(client)
    game=next(x for x in client.get('/api/admin/claims').json() if x['title']=='血脉圈住爱')
    huge=client.post(f"/api/admin/claims/{game['id']}/complete",json={'attempts':200,'successes':200},headers=H)
    assert huge.status_code==409
    assert client.post(f"/api/admin/claims/{game['id']}/complete",json={'attempts':2,'successes':3},headers=H).status_code==400
    good=client.post(f"/api/admin/claims/{game['id']}/complete",json={'attempts':2,'successes':2},headers=H)
    assert good.status_code==200 and good.json()['blood_delta']==-2 and good.json()['energy_delta']==2


def test_donation_awards_both_resources_once(client):
    player(client)
    before=client.get('/api/me').json()
    tasks=client.get('/api/tasks').json()
    donation=next(x for x in tasks if x['title']=='生命传递门')
    assert client.post(f"/api/tasks/{donation['id']}/claim",headers=H).status_code==200
    assert client.post(f"/api/tasks/{donation['id']}/claim",headers=H).status_code==409
    staff(client)
    claim=next(x for x in client.get('/api/admin/claims').json() if x['title']=='生命传递门')
    result=client.post(f"/api/admin/claims/{claim['id']}/complete",json={},headers=H)
    assert result.status_code==200 and result.json()['blood_delta']==50 and result.json()['energy_delta']==35
    player(client)
    after=client.get('/api/me').json()
    assert after['blood']==before['blood']+50 and after['energy']==before['energy']+35
    assert after['energy_boost_available'] is True


def test_redemption_idempotency_and_insufficient(client):
    player(client)
    prize=client.get('/api/prizes').json()[0]
    p_before=client.get('/api/me').json()
    key='req-unique-test-12345678'
    a=client.post('/api/redemptions',json={'prize_id':prize['id'],'request_key':key},headers=H)
    assert a.status_code==200,a.text
    b=client.post('/api/redemptions',json={'prize_id':prize['id'],'request_key':key},headers=H)
    assert b.status_code==200 and b.json()['code']==a.json()['code']
    assert client.get('/api/me').json()['energy']==p_before['energy']-prize['price']
    assert len(client.get('/api/me/redemptions').json())==1
    remaining=client.get('/api/me').json()['energy']
    for index in range(remaining // prize['price']):
        another=client.post('/api/redemptions',json={'prize_id':prize['id'],'request_key':f'req-unique-test-{index:08d}'},headers=H)
        assert another.status_code==200
    exhausted=client.post('/api/redemptions',json={'prize_id':prize['id'],'request_key':'req-unique-test-exhausted'},headers=H)
    assert exhausted.status_code==409
    staff(client)
    r=client.get('/api/admin/redemptions').json()[0]
    assert client.post(f"/api/admin/redemptions/{r['id']}/fulfill",headers=H).status_code==200
    assert client.post(f"/api/admin/redemptions/{r['id']}/fulfill",headers=H).status_code==409


def test_admin_create_binding_code(client):
    staff(client)
    payload={'identity':'student','college':'计算机科学与工程学院',
             'student_id':'202600000101','name':'测试参与者','class_name':'测试班','phone':'13800000101'}
    r=client.post('/api/admin/participants',json=payload,headers=H)
    assert r.status_code==200
    assert len(r.json()['bind_code'])>=8
    with SessionLocal() as db:
        p=db.scalar(select(Participant).where(Participant.student_id=='202600000101'))
        assert p.bind_hash is not None and p.bind_hash != r.json()['bind_code']
        assert p.phone == '13800000101'
    assert client.post('/api/admin/participants',json={**payload,'name':'重复'},headers=H).status_code==409


def test_csrf_guard(client):
    assert client.post('/api/auth/demo?student_id=DEMO001').status_code==403


def test_darts_and_rank_isolation(client):
    player(client)
    task = next(t for t in client.get('/api/tasks').json() if t['title']=='热血飞镖')
    assert client.post(f"/api/tasks/{task['id']}/claim",headers=H).status_code==200
    staff(client)
    claim = next(c for c in client.get('/api/admin/claims').json() if c['title']=='热血飞镖')
    bad=client.post(f"/api/admin/claims/{claim['id']}/complete",json={'attempts':2,'rings10':2,'rings9':1},headers=H)
    assert bad.status_code==400
    good=client.post(f"/api/admin/claims/{claim['id']}/complete",json={'attempts':3,'rings10':1,'rings9':1,'rings8':1},headers=H)
    assert good.status_code==200 and good.json()['energy_delta']==6
    player(client)
    a=client.get('/api/me').json()
    assert a['student_id']=='DEMO001'
    assert client.post('/api/auth/demo?student_id=DEMO002',headers=H).status_code==200
    b=client.get('/api/me').json()
    assert b['student_id']=='DEMO002' and b['energy_earned'] != a['energy_earned']
    ranks=client.get('/api/leaderboard').json()['players']
    assert all('student_id' not in row for row in ranks)


def test_real_bind_only_with_issued_code(client):
    staff(client)
    r=client.post('/api/admin/participants',json={'identity':'student','college':'机械与能源工程学院',
                 'student_id':'202600000102','name':'绑定演示','class_name':'测试班','phone':'13800000102'},headers=H)
    issued=r.json()['bind_code']
    from app.core import sign
    client.cookies.set('bq_pending', sign({'kind':'pending','openid':'mock-test-openid-xyz'},10))
    assert client.post('/api/auth/bind',json={'student_id':'202600000102','code':'WRONGCODE'},headers=H).status_code==400
    success=client.post('/api/auth/bind',json={'student_id':'202600000102','code':issued},headers=H)
    assert success.status_code==200,success.text
    assert client.get('/api/me').json()['student_id']=='202600000102'
    with SessionLocal() as db:
        p=db.scalar(select(Participant).where(Participant.student_id=='202600000102'))
        assert p.openid == 'mock-test-openid-xyz' and p.bind_hash is None


def test_signup_validation_search_draw_and_bulk_redemption(client):
    payload = {'identity':'student','college':'材料科学与工程学院',
               'class_name':'测试班','name':'活动测试','student_id':'202600000103','phone':'13800000103'}
    assert client.post('/api/auth/signup',json={**payload,'student_id':'20260000103'},headers=H).status_code==422
    assert client.post('/api/auth/signup',json={**payload,'phone':'1380000103'},headers=H).status_code==422
    signed=client.post('/api/auth/signup',json=payload,headers=H)
    assert signed.status_code==200 and signed.json()['first_checkin'] is True
    assert client.post('/api/auth/login',json={'name':payload['name'],'student_id':'20260000103'},headers=H).status_code==401
    pid=client.get('/api/me').json()['id']
    donation=next(t for t in client.get('/api/tasks').json() if t['title']=='生命传递门')
    assert client.post(f"/api/tasks/{donation['id']}/claim",headers=H).status_code==200

    staff(client)
    assert client.post('/api/admin/participants',json={**payload,'student_id':'202600000104','phone':'123'},headers=H).status_code==422
    person=next(p for p in client.get('/api/admin/participants').json() if p['id']==pid)
    assert person['phone']==payload['phone']
    found=client.get('/api/admin/claims',params={'q':'活动测试'}).json()
    assert len(found)==1 and found[0]['student_id']==payload['student_id']
    assert client.get('/api/admin/claims',params={'q':'不存在的同学'}).json()==[]
    completed=client.post(f"/api/admin/claims/{found[0]['id']}/complete",json={},headers=H)
    assert completed.status_code==200

    login=client.post('/api/auth/login',json={'name':payload['name'],'student_id':payload['student_id']},headers=H)
    assert login.status_code==200
    draw=client.post('/api/draw',headers=H)
    assert draw.status_code==200 and draw.json()['blood'] in (10,15,20,25,30)
    assert client.post('/api/draw',headers=H).status_code==409
    assert client.get('/api/draw').json()['result']==draw.json()['blood']
    prize=client.get('/api/prizes').json()[0]
    before=client.get('/api/me').json()['energy']
    key='bulk-test-request-202600000103'
    request={'prize_id':prize['id'],'quantity':2,'request_key':key}
    first=client.post('/api/redemptions',json=request,headers=H)
    assert first.status_code==200 and first.json()['quantity']==2
    repeated=client.post('/api/redemptions',json=request,headers=H)
    assert repeated.status_code==200 and repeated.json()['id']==first.json()['id']
    assert client.post('/api/redemptions',json={**request,'quantity':1},headers=H).status_code==409
    assert client.get('/api/me').json()['energy']==before-2*prize['price']
    assert client.get('/api/me/redemptions').json()[0]['quantity']==2
    assert client.get('/api/prizes').json()[0]['stock']==prize['stock']-2
    assert client.post('/api/redemptions',json={'prize_id':prize['id'],'quantity':100,'request_key':'bulk-too-many-test'},headers=H).status_code==409

    staff(client)
    results=client.get('/api/admin/redemptions',params={'q':first.json()['code']}).json()
    assert len(results)==1 and results[0]['quantity']==2


def test_teacher_registration_and_beijing_draw_gate(client, monkeypatch):
    teacher = {'identity':'staff','college':None,
               'name':'教师测试','student_id':'T-28','phone':'13800000128'}
    assert client.post('/api/auth/signup',json=teacher,headers=H).status_code==422
    assert client.post('/api/auth/signup',json={**teacher,'college':'校外单位'},headers=H).status_code==422
    signup=client.post('/api/auth/signup',json={**teacher,'college':'其他'},headers=H)
    assert signup.status_code==200 and signup.json()['first_checkin'] is True
    me=client.get('/api/me').json()
    assert me['identity']=='staff' and me['college']=='其他' and me['student_id']=='T-28'
    assert me['class_name']==''
    monkeypatch.setattr(app_main,'now',lambda: datetime(2026,10,28,6,59,tzinfo=timezone.utc))
    assert client.get('/api/draw').json()['can_spin'] is False
    assert client.post('/api/draw',headers=H).status_code==409
    monkeypatch.setattr(app_main,'now',lambda: datetime(2026,10,28,7,0,tzinfo=timezone.utc))
    assert client.get('/api/draw').json()['can_spin'] is True
    assert client.post('/api/draw',headers=H).status_code==200
    assert client.post('/api/auth/login',json={'name':'教师测试','student_id':'T-28'},headers=H).status_code==200


def test_optional_staff_department_and_student_transition_validation(client):
    teacher={'identity':'staff','college':'其他','name':'空部门教师','student_id':'T-29','phone':'13800000129','class_name':''}
    assert client.post('/api/auth/signup',json=teacher,headers=H).status_code==200
    assert client.get('/api/me').json()['class_name']=='' and client.get('/api/me').json()['college']=='其他'
    student={'identity':'student','college':'商学院','name':'班级必填',
             'student_id':'202600000110','phone':'13800000110'}
    assert client.post('/api/auth/signup',json=student,headers=H).status_code==422
    assert client.post('/api/auth/signup',json={**student,'class_name':'  '},headers=H).status_code==422
    assert client.post('/api/auth/signup',json={**student,'college':'其他','class_name':'一班'},headers=H).status_code==422

    staff(client)
    created=client.post('/api/admin/participants',json={
        'identity':'staff','college':'商学院','name':'后台新增教师','student_id':'T-30','phone':'13800000130'},headers=H)
    assert created.status_code==200,created.text
    empty=client.post('/api/admin/participants',json={
        'identity':'staff','college':'其他','name':'空部门新增','student_id':'T-31','phone':'13800000131','class_name':''},headers=H)
    assert empty.status_code==200,empty.text
    assert client.post('/api/admin/participants',json={
        'identity':'staff','name':'无学院教师','student_id':'T-32','phone':'13800000132'},headers=H).status_code==422
    assert client.post('/api/admin/participants',json=student,headers=H).status_code==422
    staff_rows=client.get('/api/admin/participants',params={'q':'T-3'}).json()
    assert all(row['class_name']=='' and row['college'] in {'商学院','其他'} for row in staff_rows)

    initial=client.post('/api/admin/participants',json={**student,'student_id':'202600000109',
        'name':'身份切换','class_name':'旧班级'},headers=H)
    assert initial.status_code==200,initial.text
    pid=initial.json()['id']
    assert client.patch(f'/api/admin/participants/{pid}',json={
        'identity':'staff','student_id':'T-109'},headers=H).status_code==400
    switched=client.patch(f'/api/admin/participants/{pid}',json={
        'identity':'staff','student_id':'T-109','college':'其他','class_name':'旧班级'},headers=H)
    assert switched.status_code==200,switched.text
    row=next(p for p in client.get('/api/admin/participants',params={'q':'T-109'}).json() if p['id']==pid)
    assert row['identity']=='staff' and row['college']=='其他' and row['class_name']==''
    assert client.patch(f'/api/admin/participants/{pid}',json={'class_name':''},headers=H).status_code==200
    assert client.patch(f'/api/admin/participants/{pid}',json={
        'identity':'student','student_id':'202600000109','college':'商学院'},headers=H).status_code==400
    assert client.patch(f'/api/admin/participants/{pid}',json={
        'identity':'student','student_id':'202600000109','college':'其他','class_name':'新班级'},headers=H).status_code==400
    restored=client.patch(f'/api/admin/participants/{pid}',json={
        'identity':'student','student_id':'202600000109','college':'商学院','class_name':'新班级'},headers=H)
    assert restored.status_code==200,restored.text
    assert client.patch(f'/api/admin/participants/{pid}',json={'class_name':''},headers=H).status_code==400
    row=next(p for p in client.get('/api/admin/participants',params={'q':'202600000109'}).json() if p['id']==pid)
    assert row['identity']=='student' and row['college']=='商学院' and row['class_name']=='新班级'

    with SessionLocal() as db:
        legacy=Participant(student_id='T-LEGACY-1',name='历史教职工',identity='staff',college=None,
                           class_name='',phone='13800000133')
        db.add(legacy)
        db.commit()
        legacy_id=legacy.id
    row=next(p for p in client.get('/api/admin/participants',params={'q':'T-LEGACY-1'}).json() if p['id']==legacy_id)
    assert row['college'] is None
    assert client.patch(f'/api/admin/participants/{legacy_id}',json={'phone':'13800000134'},headers=H).status_code==200
    assert client.patch(f'/api/admin/participants/{legacy_id}',json={'identity':'staff'},headers=H).status_code==400
    assert client.patch(f'/api/admin/participants/{legacy_id}',json={'college':'其他'},headers=H).status_code==200


def test_project_scope_and_claim_audit(client):
    payload={'identity':'student','college':'商学院','class_name':'核验班',
             'name':'权限测试','student_id':'202600000105','phone':'13800000105'}
    assert client.post('/api/auth/signup',json=payload,headers=H).status_code==200
    claims=[]
    for title in ('健康检测站 · 健康体检','气血调养室'):
        task=next(x for x in client.get('/api/tasks').json() if x['title']==title)
        result=client.post(f"/api/tasks/{task['id']}/claim",headers=H)
        assert result.status_code==200
        claims.append((task,result.json()['claim_id']))
    (health,health_claim),(wellness,wellness_claim)=claims

    staff(client)
    create=client.post('/api/admin/staff',json={'username':'项目核验员','password':'project-pass-123',
        'role':'project','task_ids':[health['id']]},headers=H)
    assert create.status_code==200,create.text
    assert create.json()['task_ids']==[health['id']]
    assert client.post('/api/admin/logout',headers=H).status_code==200
    scoped=client.post('/api/admin/login',json={'username':'项目核验员','password':'project-pass-123'},headers=H)
    assert scoped.status_code==200
    assert client.get('/api/me').status_code==200  # participant and staff sessions are distinct
    own=client.get('/api/admin/claims',params={'status':'pending'}).json()
    assert any(x['id']==health_claim for x in own)
    assert all(x['task_id']==health['id'] for x in own)
    assert client.post(f'/api/admin/claims/{wellness_claim}/complete',json={},headers=H).status_code==403
    assert client.get('/api/admin/participants').status_code==403
    assert client.get('/api/admin/staff').status_code==403
    assert client.get('/api/admin/claim-audit').status_code==403
    done=client.post(f'/api/admin/claims/{health_claim}/complete',json={},headers=H)
    assert done.status_code==200 and done.json()['blood_delta']==2
    assert client.post(f'/api/admin/claims/{health_claim}/adjust',json={
        'blood_delta':5,'energy_delta':0,'reason':'核验更正'},headers=H).status_code==403

    staff(client)
    audit=client.get('/api/admin/claim-audit',params={'task_id':health['id']}).json()['items']
    assert any(x['claim_id']==health_claim and x['actor']=='项目核验员' and x['action']=='complete' for x in audit)
    adjusted=client.post(f'/api/admin/claims/{health_claim}/adjust',json={
        'blood_delta':5,'energy_delta':0,'reason':'核验更正'},headers=H)
    assert adjusted.status_code==200 and adjusted.json()['blood_delta']==5
    reversed_claim=client.post(f'/api/admin/claims/{health_claim}/reverse',json={'reason':'记录撤回'},headers=H)
    assert reversed_claim.status_code==200 and reversed_claim.json()['status']=='reversed'
    assert client.get('/api/me').json()['blood']==0
    audit=client.get('/api/admin/claim-audit',params={'task_id':health['id']}).json()['items']
    assert {'complete','adjust','reverse'} <= {x['action'] for x in audit if x['claim_id']==health_claim}
    ledger=client.get('/api/me/ledger').json()
    assert sum('任务修正' in x['reason'] for x in ledger)>=2


def test_super_reverses_donation_boost_with_history(client):
    payload={'identity':'student','college':'食品科学与工程学院','class_name':'回滚班',
             'name':'撤回测试','student_id':'202600000106','phone':'13800000106'}
    assert client.post('/api/auth/signup',json=payload,headers=H).status_code==200
    donation=next(x for x in client.get('/api/tasks').json() if x['title']=='生命传递门')
    claim=client.post(f"/api/tasks/{donation['id']}/claim",headers=H).json()['claim_id']
    staff(client)
    assert client.post(f'/api/admin/claims/{claim}/complete',json={},headers=H).status_code==200
    assert client.post('/api/energy-boost/use',headers=H).status_code==200
    assert client.get('/api/me').json()['energy_earned']==105
    result=client.post(f'/api/admin/claims/{claim}/reverse',json={'reason':'现场记录确认有误'},headers=H)
    assert result.status_code==200,result.text
    after=client.get('/api/me').json()
    assert after['blood']==0 and after['energy_earned']==0 and after['energy_boost_used'] is False
    assert client.get('/api/admin/claim-audit',params={'task_id':donation['id']}).json()['items'][0]['action']=='reverse'


def test_super_corrects_draw_without_erasing_original_result(client):
    payload={'identity':'student','college':'商学院','class_name':'抽奖班',
             'name':'抽奖修正','student_id':'202600000107','phone':'13800000107'}
    assert client.post('/api/auth/signup',json=payload,headers=H).status_code==200
    pid=client.get('/api/me').json()['id']
    drawn=client.post('/api/draw',headers=H)
    assert drawn.status_code==200,drawn.text
    original=drawn.json()['blood']
    corrected=next(value for value in (10,15,20,25,30) if value!=original)
    staff(client)
    assert client.patch(f'/api/admin/draws/{pid}',json={'blood':corrected,'reason':'现场复核'},headers=H).status_code==200
    details=client.get(f'/api/admin/draws/{pid}').json()
    assert details['original_blood']==original and details['blood']==corrected
    assert details['history'][0]['before_blood']==original and details['history'][0]['after_blood']==corrected
    assert client.get('/api/draw').json()['result']==corrected
    assert client.get('/api/me').json()['blood']==corrected
    assert client.patch(f'/api/admin/draws/{pid}',json={'blood':12,'reason':'无效奖项'},headers=H).status_code==422
    assert client.patch(f'/api/admin/draws/{pid}',json={'blood':corrected,'reason':'无变化'},headers=H).status_code==409
    reversed_draw=client.post(f'/api/admin/draws/{pid}/reverse',json={'reason':'奖项撤回'},headers=H)
    assert reversed_draw.status_code==200,reversed_draw.text
    assert reversed_draw.json()['blood_delta']==-corrected
    state=client.get('/api/draw').json()
    assert state['already_drawn'] and state['status']=='reversed' and state['result'] is None and not state['can_spin']
    assert client.post('/api/draw',headers=H).status_code==409
    assert client.get('/api/me').json()['blood']==0
    assert client.post(f'/api/admin/draws/{pid}/reverse',json={'reason':'重复撤回'},headers=H).status_code==409
    with SessionLocal() as db:
        original_row=db.scalar(select(Draw).where(Draw.participant_id==pid))
        audits=db.scalars(select(DrawAudit).where(DrawAudit.draw_id==original_row.id).order_by(DrawAudit.id)).all()
        adjustments=db.scalars(select(Ledger).where(Ledger.participant_id==pid,Ledger.source=='draw_adjust')).all()
        assert original_row.prize_blood==original
        assert [a.action for a in audits]==['adjust','reverse']
        assert sum(row.delta for row in adjustments)==-original
    restored=client.patch(f'/api/admin/draws/{pid}',json={'blood':original,'reason':'撤回更正'},headers=H)
    assert restored.status_code==200 and restored.json()['status']=='drawn'
    assert client.get('/api/draw').json()['result']==original


def test_claim_audit_paginates_with_filters(client):
    staff(client)
    all_first=client.get('/api/admin/claim-audit',params={'limit':1}).json()
    assert len(all_first['items'])==1 and all_first['next_offset']==1
    all_second=client.get('/api/admin/claim-audit',params={'limit':1,'offset':1}).json()
    assert len(all_second['items'])==1 and all_second['items'][0]['id']!=all_first['items'][0]['id']
    assert client.get('/api/admin/claim-audit',params={'limit':101}).status_code==422
    tasks=client.get('/api/admin/tasks').json()
    health=next(x for x in tasks if x['code']=='health')
    first=client.get('/api/admin/claim-audit',params={'task_id':health['id'],'q':'权限测试','limit':1}).json()
    assert len(first['items'])==1 and first['next_offset']==1
    second=client.get('/api/admin/claim-audit',params={'task_id':health['id'],'q':'权限测试','limit':1,'offset':1}).json()
    assert len(second['items'])==1 and second['next_offset'] is not None
    assert first['items'][0]['id']!=second['items'][0]['id']
    assert all(row['task_id']==health['id'] and row['name']=='权限测试' for row in first['items']+second['items'])
    empty=client.get('/api/admin/claim-audit',params={'q':'不存在的参与者'}).json()
    assert empty=={'items':[],'next_offset':None}


def test_staff_login_rate_limit_is_account_scoped_and_expires(client,monkeypatch):
    staff(client)
    task=next(x for x in client.get('/api/admin/tasks').json() if x['code']=='health')
    created=client.post('/api/admin/staff',json={'username':'限流核验员','password':'correct-pass-123',
        'role':'project','task_ids':[task['id']]},headers=H)
    assert created.status_code==200,created.text
    assert client.post('/api/admin/logout',headers=H).status_code==200
    for _ in range(4):
        failed=client.post('/api/admin/login',json={'username':'限流核验员','password':'wrong-pass'},headers=H)
        assert failed.status_code==401,failed.text
    threshold=client.post('/api/admin/login',json={'username':'限流核验员','password':'wrong-pass'},headers=H)
    assert threshold.status_code==429 and threshold.headers['retry-after']=='300'
    assert client.post('/api/admin/login',json={'username':'限流核验员','password':'correct-pass-123'},headers=H).status_code==429
    assert client.post('/api/admin/login',json={'username':'管理员','password':'local-test-admin-password'},headers=H).status_code==200
    with SessionLocal() as db:
        account=db.scalar(select(StaffUser).where(StaffUser.username=='限流核验员'))
        assert account.login_failures==5 and account.login_locked_until is not None
    monkeypatch.setattr(app_main,'now',lambda: datetime(2026,10,28,7,6,tzinfo=timezone.utc))
    unlocked=client.post('/api/admin/login',json={'username':'限流核验员','password':'correct-pass-123'},headers=H)
    assert unlocked.status_code==200,unlocked.text
    assert client.post('/api/admin/login',json={'username':'限流核验员','password':'wrong-pass'},headers=H).status_code==401
    with SessionLocal() as db:
        account=db.scalar(select(StaffUser).where(StaffUser.username=='限流核验员'))
        assert account.login_failures==1 and account.login_locked_until is None


def test_explicit_null_updates_and_legacy_identifier_edit(client):
    staff(client)
    legacy=next(row for row in client.get('/api/admin/participants',params={'q':'DEMO001'}).json()
                if row['student_id']=='DEMO001')
    for change in ({'name':None},{'phone':None},{'active':None},{'identity':None}):
        assert client.patch(f"/api/admin/participants/{legacy['id']}",json=change,headers=H).status_code==422
    admin=client.get('/api/admin/me').json()
    for change in ({'task_ids':None},{'role':None},{'active':None}):
        assert client.patch(f"/api/admin/staff/{admin['id']}",json=change,headers=H).status_code==422
    edited=client.patch(f"/api/admin/participants/{legacy['id']}",json={'phone':'13800000999'},headers=H)
    assert edited.status_code==200,edited.text
    assert client.patch(f"/api/admin/participants/{legacy['id']}",json={'student_id':'DEMO001'},headers=H).status_code==400
    assert client.patch(f"/api/admin/participants/{legacy['id']}",json={'identity':'student'},headers=H).status_code==400
    row=next(row for row in client.get('/api/admin/participants',params={'q':'DEMO001'}).json()
             if row['id']==legacy['id'])
    assert row['phone']=='13800000999' and row['student_id']=='DEMO001'


def test_super_corrects_boost_with_audit_and_no_second_use(client):
    payload={'identity':'student','college':'计算机科学与工程学院','class_name':'道具班',
             'name':'道具修正','student_id':'202600000108','phone':'13800000108'}
    assert client.post('/api/auth/signup',json=payload,headers=H).status_code==200
    pid=client.get('/api/me').json()['id']
    donation=next(t for t in client.get('/api/tasks').json() if t['title']=='生命传递门')
    claim=client.post(f"/api/tasks/{donation['id']}/claim",headers=H).json()['claim_id']
    staff(client)
    assert client.get(f'/api/admin/energy-boosts/{pid}').status_code==404
    before_row=next(row for row in client.get('/api/admin/participants').json() if row['id']==pid)
    assert before_row['boost_recorded'] is False
    assert client.post(f'/api/admin/claims/{claim}/complete',json={},headers=H).status_code==200
    used=client.post('/api/energy-boost/use',headers=H)
    assert used.status_code==200,used.text
    after_row=next(row for row in client.get('/api/admin/participants').json() if row['id']==pid)
    assert after_row['boost_recorded'] is True
    original=used.json()['bonus']
    assert original==70 and client.get('/api/me').json()['energy_earned']==105
    detail=client.get(f'/api/admin/energy-boosts/{pid}').json()
    assert detail['original_bonus']==original and detail['bonus']==original
    assert detail['status']=='active' and detail['used'] is True and detail['history']==[]

    account=client.post('/api/admin/staff',json={'username':'道具项目核验员','password':'project-pass-boost',
        'role':'project','task_ids':[donation['id']]},headers=H)
    assert account.status_code==200,account.text
    assert client.post('/api/admin/login',json={'username':'道具项目核验员','password':'project-pass-boost'},headers=H).status_code==200
    assert client.get(f'/api/admin/energy-boosts/{pid}').status_code==403
    assert client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':original+7,'reason':'无权限'},headers=H).status_code==403
    assert client.post(f'/api/admin/energy-boosts/{pid}/reverse',json={'reason':'无权限'},headers=H).status_code==403
    staff(client)

    corrected=client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':original+7,'reason':'现场复核'},headers=H)
    assert corrected.status_code==200,corrected.text
    assert corrected.json()['energy_delta']==7 and corrected.json()['bonus']==77
    assert client.get('/api/me').json()['energy_earned']==112
    assert client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':77,'reason':'无变化'},headers=H).status_code==409
    assert client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':0,'reason':'需撤回'},headers=H).status_code==422

    # Explicit administrative bonus overrides are fixed until another administrative correction.
    adjusted_donation=client.post(f'/api/admin/claims/{claim}/adjust',json={
        'blood_delta':50,'energy_delta':40,'reason':'献血复核'},headers=H)
    assert adjusted_donation.status_code==200,adjusted_donation.text
    assert client.get('/api/me').json()['energy_earned']==117
    assert client.get(f'/api/admin/energy-boosts/{pid}').json()['bonus']==77

    reversed_boost=client.post(f'/api/admin/energy-boosts/{pid}/reverse',json={'reason':'道具发放有误'},headers=H)
    assert reversed_boost.status_code==200,reversed_boost.text
    assert reversed_boost.json()['energy_delta']==-77 and reversed_boost.json()['used'] is True
    assert client.get('/api/me').json()['energy_earned']==40
    assert client.get('/api/me').json()['energy_boost_available'] is False
    assert client.post('/api/energy-boost/use',headers=H).status_code==409
    assert client.post(f'/api/admin/energy-boosts/{pid}/reverse',json={'reason':'重复撤回'},headers=H).status_code==409
    restored=client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':80,'reason':'确认恢复'},headers=H)
    assert restored.status_code==200,restored.text
    assert client.get('/api/me').json()['energy_earned']==120
    detail=client.get(f'/api/admin/energy-boosts/{pid}').json()
    assert detail['bonus']==80 and detail['status']=='active'
    assert [item['action'] for item in detail['history']]==['adjust','reverse','adjust']
    assert [(item['before_bonus'],item['after_bonus']) for item in detail['history']]==[(0,80),(77,0),(70,77)]
    with SessionLocal() as db:
        original_row=db.scalar(select(Ledger).where(Ledger.participant_id==pid,Ledger.source=='boost_v2'))
        audits=db.scalars(select(BoostAudit).where(BoostAudit.boost_ledger_id==original_row.id)).all()
        corrections=db.scalars(select(Ledger).where(Ledger.participant_id==pid,Ledger.source=='boost_manual_adjust')).all()
        assert original_row.delta==original and len(audits)==3
        assert sum(row.delta for row in corrections)==10

    donor_reversal=client.post(f'/api/admin/claims/{claim}/reverse',json={'reason':'献血记录撤回'},headers=H)
    assert donor_reversal.status_code==200,donor_reversal.text
    assert client.get('/api/me').json()['energy_earned']==0
    assert client.get(f'/api/admin/energy-boosts/{pid}').json()['status']=='reversed'
    assert client.patch(f'/api/admin/energy-boosts/{pid}',json={'bonus':70,'reason':'恢复'},headers=H).status_code==409
