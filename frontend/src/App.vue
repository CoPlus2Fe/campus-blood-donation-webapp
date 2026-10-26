<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  Activity, ArrowLeft, ArrowRight, CheckCircle2, ChevronRight,
  Droplets, Gift, Heart, LogOut, Medal, Minus, Plus, RefreshCw,
  Sparkles, Ticket, Trophy, User, X, Zap,
} from 'lucide-vue-next'
import { api, type DrawState, type Ledger, type Prize, type Profile, type Ranking, type Redemption, type Task } from './api'
import AdminCenter from './AdminCenter.vue'
import WheelResult from './WheelResult.vue'

const isAdminPage = location.pathname.startsWith('/admin')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const success = ref('')
const bootstrap = ref({
  draw_prizes: [] as { blood: number; probability: number }[],
  leaderboard_limit: 100,
})
const profile = ref<Profile | null>(null)
const authMode = ref<'entry' | 'signup' | 'login'>('entry')
const signupClass = ref('')
const signupName = ref('')
const signupStudent = ref('')
const signupPhone = ref('')
const signupIdentity = ref<'student' | 'staff'>('student')
const signupCollege = ref('')
const colleges = [
  '计算机科学与工程学院', '机械与能源工程学院', '材料科学与工程学院',
  '食品科学与工程学院', '商学院',
]
const staffColleges = [...colleges, '其他']
const loginName = ref('')
const loginStudent = ref('')
const tab = ref('home')
const tasks = ref<Task[]>([])
const prizes = ref<Prize[]>([])
const ledger = ref<Ledger[]>([])
const redemptions = ref<Redemption[]>([])
const ranking = ref<Ranking>({ players: [], my_rank: 0, my_position: { rank: 0, name: '', score: 0 }, limit: 100 })
const draw = ref<DrawState>({ can_spin: false, available_at: null, already_drawn: false, result: null, status: 'not_drawn' })
const drawSpinKey = ref(0)
const drawSpinning = ref(false)
const selectedTask = ref<Task | null>(null)

const redeemQuantity = ref<Record<number, number>>({})

const bloodTasks = computed(() => tasks.value.filter(t => t.category === 'volunteer'))
const arenaTasks = computed(() => tasks.value.filter(t => t.category === 'game' || t.category === 'dart'))
const selectedTaskRules = computed(() => {
  const task = selectedTask.value
  if (!task) return []
  const rules: string[] = []
  if (task.category === 'game') {
    rules.push(`每次尝试消耗 ${task.blood_per_attempt} 血值。`)
    rules.push(`每成功 1 次获得 ${task.energy_per_success} 能量，按实际成功次数计分。`)
  } else if (task.category === 'dart') {
    rules.push('每次投掷消耗 1 血值。10 环得 3 能量，9 环得 2 能量，8 环得 1 能量。')
  } else {
    rules.push('请在现场完成项目后，由工作人员核验并录入奖励。')
  }
  if (task.blood_reward) rules.push(`完成后获得 ${task.blood_reward} 血值。`)
  if (task.energy_reward) rules.push(`完成后获得 ${task.energy_reward} 能量。`)
  if (task.title === '生命传递门') rules.push('另获一次三倍能量道具，可在兑换页使用。')
  if (task.max_claims !== null) rules.push(`每人最多完成 ${task.max_claims} 次。`)
  return rules
})

let toastTimer: number | undefined
let pollTimer: number | undefined
function clearToast() {
  if (toastTimer !== undefined) window.clearTimeout(toastTimer)
  error.value = ''
  success.value = ''
}
function showToast(kind: 'error' | 'success', message: string) {
  clearToast()
  if (kind === 'error') error.value = message
  else success.value = message
  toastTimer = window.setTimeout(() => { error.value = ''; success.value = '' }, 3000)
}
async function safe(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  clearToast()
  try { await action() } catch (e: any) { showToast('error', e?.message || '操作失败，请重试') }
  finally { busy.value = false }
}
async function fetchAll() {
  const [p, t, d, pr, r, l, rd] = await Promise.all([
    api<Profile>('/me'), api<Task[]>('/tasks'), api<DrawState>('/draw'), api<Prize[]>('/prizes'),
    api<Ranking>('/leaderboard'), api<Ledger[]>('/me/ledger'), api<Redemption[]>('/me/redemptions'),
  ])
  profile.value = p; tasks.value = t; draw.value = d; prizes.value = pr
  ranking.value = r; ledger.value = l; redemptions.value = rd
}
async function init() {
  try {
    bootstrap.value = await api('/bootstrap')
    try { await fetchAll() } catch { profile.value = null }
  } catch (e: any) { showToast('error', e?.message || '连接失败') }
  finally { loading.value = false }
}
onMounted(() => {
  if (!isAdminPage) void init()
  pollTimer = window.setInterval(async () => {
    if (!profile.value || document.visibilityState !== 'visible') return
    try {
      const [p, r, d] = await Promise.all([api<Profile>('/me'), api<Ranking>('/leaderboard'), api<DrawState>('/draw')])
      profile.value = p; ranking.value = r; draw.value = d
    } catch { /* A transient refresh failure does not interrupt the page. */ }
  }, 10000)
})
onUnmounted(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  if (toastTimer !== undefined) window.clearTimeout(toastTimer)
})

function signup() {
  void safe(async () => {
    await api('/auth/signup', 'POST', {
      class_name: signupIdentity.value === 'student' ? signupClass.value : '', name: signupName.value,
      student_id: signupStudent.value, phone: signupPhone.value,
      identity: signupIdentity.value,
      college: signupCollege.value,
    })
    await fetchAll()
    signupClass.value = ''; signupName.value = ''; signupStudent.value = ''; signupPhone.value = ''
    signupCollege.value = ''; signupIdentity.value = 'student'
    authMode.value = 'entry'; tab.value = 'draw'
    showToast('success', '注册成功，欢迎参加活动')
  })
}
function loginPlayer() {
  void safe(async () => {
    await api('/auth/login', 'POST', { name: loginName.value, student_id: loginStudent.value })
    await fetchAll()
    loginName.value = ''; loginStudent.value = ''
    authMode.value = 'entry'; tab.value = 'home'
    showToast('success', '登录成功')
  })
}
function logout() { void safe(async () => { await api('/auth/logout', 'POST'); location.href = '/' }) }
function refreshScreen() { void safe(async () => { await fetchAll(); showToast('success', '数据已更新') }) }
function spinWheel() {
  if (drawSpinning.value || busy.value || !draw.value.can_spin || draw.value.already_drawn) return
  void safe(async () => {
    const result = await api<{ result: number }>('/draw', 'POST')
    draw.value = { ...draw.value, can_spin: false, already_drawn: true, result: result.result, status: 'drawn' }
    drawSpinning.value = true
    drawSpinKey.value += 1
    window.setTimeout(() => { drawSpinning.value = false; void fetchAll().catch(() => {}) }, 2600)
  })
}
function openTab(next: string) {
  tab.value = next
  window.scrollTo({ top: 0, behavior: 'smooth' })
  if (profile.value) void fetchAll().catch(() => {})
}
function claimSelectedTask() {
  const task = selectedTask.value
  if (!task || task.status !== 'available') return
  selectedTask.value = null
  void safe(async () => {
    await api(`/tasks/${task.id}/claim`, 'POST')
    await fetchAll()
    showToast('success', '申请已提交，完成后请找工作人员核验')
  })
}
function redeem(prize: Prize) {
  const quantity = redeemQuantity.value[prize.id] ?? 1
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > maxQuantity(prize)) {
    showToast('error', '请选择有效的兑换份数')
    return
  }
  if (!confirm(`确认消耗 ${prize.price * quantity} 能量兑换 ${quantity} 份「${prize.title}」吗？`)) return
  void safe(async () => {
    const requestKey = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
    const r = await api<{ code: string }>('/redemptions', 'POST', { prize_id: prize.id, request_key: requestKey, quantity })
    await fetchAll()
    redeemQuantity.value[prize.id] = 1
    showToast('success', `已兑换 ${quantity} 份，凭证码：${r.code}`)
  })
}
function maxQuantity(prize: Prize) {
  return Math.min(100, prize.stock, Math.floor((profile.value?.energy ?? 0) / prize.price))
}
function changeQuantity(prize: Prize, delta: number) {
  redeemQuantity.value[prize.id] = Math.max(1, Math.min(maxQuantity(prize), (redeemQuantity.value[prize.id] ?? 1) + delta))
}
function useBoost() {
  if (!profile.value?.energy_boost_available) return
  if (!confirm(`现在使用三倍能量道具？当前累计 ${profile.value.energy_earned} 能量将增加两倍，达到 ${profile.value.energy_earned * 3}。道具只能使用一次，后续获得的能量正常计分。`)) return
  void safe(async () => {
    const r = await api<{ bonus: number }>('/energy-boost/use', 'POST')
    await fetchAll()
    showToast('success', `已增加 ${r.bonus} 能量`)
  })
}
const navItems = [
  { id: 'home', label: '首页', icon: Heart }, { id: 'tasks', label: '项目', icon: Activity },
  { id: 'draw', label: '幸运轮', icon: Sparkles }, { id: 'shop', label: '兑换', icon: Gift },
  { id: 'rank', label: '榜单', icon: Trophy },
]
</script>

<template>
  <div class="site-shell">
    <div v-if="!isAdminPage && loading" class="center-screen"><Heart :size="28"/><p>正在加载活动信息…</p></div>
    <AdminCenter v-else-if="isAdminPage"/>

    <template v-else-if="!profile">
      <main class="welcome">
        <div class="welcome-art"><img src="/volunteer-fair.jpg" alt="校园公益活动中的志愿者与同学"/></div>
        <div class="welcome-body"><h1>热血行动</h1><p class="welcome-sub">热血青春・与爱同行<br/>广东海洋大学阳江校区2026年无偿献血健康公益嘉年华</p>
          <div class="auth-panel">
            <template v-if="authMode === 'entry'"><h2>参与活动</h2><p>首次参与请先注册，已有账号可通过姓名和学号或工号登录。</p><button class="btn primary wide" :disabled="busy" @click="authMode = 'signup'"><CheckCircle2 :size="18"/> 注册</button><button class="btn outline wide" :disabled="busy" @click="authMode = 'login'"><User :size="18"/> 登录</button></template>
            <template v-else-if="authMode === 'signup'"><button class="text-link back-link" @click="authMode = 'entry'"><ArrowLeft :size="16"/> 返回</button><h2>注册</h2><p>填写信息后进入幸运轮，获取初始血值。</p><form class="auth-form" @submit.prevent="signup">
              <fieldset class="identity-picker"><legend>身份</legend><label><input v-model="signupIdentity" type="radio" value="student" @change="signupCollege = ''"/> 学生</label><label><input v-model="signupIdentity" type="radio" value="staff" @change="signupCollege = ''"/> 教职工</label></fieldset>
              <label v-if="signupIdentity === 'student'">班级<input v-model="signupClass" placeholder="填写班级" required/></label>
              <label>姓名<input v-model="signupName" placeholder="填写姓名" autocomplete="name" required/></label>
              <label>{{ signupIdentity === 'student' ? '学号' : '工号' }}<input v-model="signupStudent" :placeholder="signupIdentity === 'student' ? '填写学号' : '填写工号'" :inputmode="signupIdentity === 'student' ? 'numeric' : 'text'" :pattern="signupIdentity === 'student' ? '[0-9]{12}' : undefined" :maxlength="signupIdentity === 'student' ? 12 : 40" :title="signupIdentity === 'student' ? '学号应为12位数字' : undefined" required/></label>
              <label>学院<select v-model="signupCollege" required><option value="" disabled>选择学院</option><option v-for="college in signupIdentity === 'student' ? colleges : staffColleges" :key="college" :value="college">{{ college }}</option></select></label>
              <label>联系电话<input v-model="signupPhone" placeholder="填写联系电话" type="tel" autocomplete="tel" inputmode="numeric" pattern="[0-9]{11}" minlength="11" maxlength="11" title="联系电话应为11位数字" required/></label>
              <button class="btn primary wide" :disabled="busy">完成注册 <ArrowRight :size="17"/></button>
            </form></template>
            <template v-else><button class="text-link back-link" @click="authMode = 'entry'"><ArrowLeft :size="16"/> 返回</button><h2>登录</h2><p>使用注册时填写的姓名与学号或工号。</p><form class="auth-form" @submit.prevent="loginPlayer"><label>姓名<input v-model="loginName" placeholder="填写姓名" autocomplete="name" required/></label><label>学号或工号<input v-model="loginStudent" placeholder="填写学号或工号" maxlength="40" required/></label><button class="btn primary wide" :disabled="busy">登录 <ArrowRight :size="17"/></button></form></template>
          </div><a class="staff-link text-link" href="/admin">工作人员入口 <ChevronRight :size="16"/></a>
        </div>
      </main>
    </template>

    <template v-else>
      <div class="app-container">
        <header class="topbar"><div class="brand"><span class="brand-mark"><Heart :size="17" fill="currentColor"/></span><span class="brand-title">热血行动</span></div><div class="topbar-actions"><span class="player-number" :aria-label="`参与者编号 ${profile.id} 号`">编号 <strong>{{ profile.id }}</strong></span><button class="icon-button" title="退出登录" aria-label="退出登录" @click="logout"><LogOut :size="19"/></button></div></header>

        <main v-if="tab === 'home'" class="page-content home-page">
          <section class="home-hero"><img src="/volunteer-fair.jpg" alt="校园公益活动中的志愿者与同学"/><div class="home-hero-shade"></div><div class="home-hero-copy"><h1>热血青春・与爱同行</h1><p>广东海洋大学阳江校区2026年<br/>无偿献血健康公益嘉年华</p></div></section>
          <section class="character-sheet" aria-label="我的活动档案">
            <div class="character-head">
              <div class="character-avatar" aria-hidden="true"><User :size="27"/></div>
              <div class="character-name"><span>参与者档案</span><h2>{{ profile.name }}</h2><p>{{ profile.identity === 'staff' ? '教职工' : '学生' }} · {{ profile.identity === 'staff' ? '工号' : '学号' }} {{ profile.student_id }}</p></div>
              <div class="character-rank"><Trophy :size="17"/><span>当前排名</span><strong>{{ profile.rank > 0 ? `第 ${profile.rank} 名` : '暂未上榜' }}</strong></div>
            </div>
            <p v-if="profile.college || profile.class_name" class="character-affiliation"><span v-if="profile.college">{{ profile.college }}</span><span v-if="profile.class_name">{{ profile.class_name }}</span></p>
            <div class="character-stats">
              <div class="character-stat blood"><span><Droplets :size="16"/> 当前血值</span><strong>{{ profile.blood }}</strong><small>竞技场参与机会</small></div>
              <div class="character-stat energy"><span><Zap :size="16"/> 可用能量</span><strong>{{ profile.energy }}</strong><small>用于兑换奖励</small></div>
              <div class="character-stat total"><span><Trophy :size="16"/> 累计能量</span><strong>{{ profile.energy_earned }}</strong><small>榜单排名依据</small></div>
            </div>
            <button class="character-leaderboard" @click="openTab('rank')">查看能量榜单 <ArrowRight :size="16"/></button>
          </section>
          <section class="resource-guide"><h2>血值与能量怎么用？</h2><div><span class="guide-symbol blood"><Droplets :size="17"/></span><p><strong>血值是参与机会。</strong>在线幸运轮给你初始血值，健康体验和献血也能获得血值；能量竞技场每尝试一次会消耗血值。血值不计入榜单。</p></div><div><span class="guide-symbol energy"><Zap :size="17"/></span><p><strong>能量是活动成绩。</strong>竞技场按实际成绩获得能量，献血也能获得能量。能量可兑换奖品，榜单按累计获得量排名，兑换不会降低排名。</p></div></section>
          <div class="section-heading"><h2>参与活动</h2><span>选择你的下一站</span></div>
          <div class="quick-links"><button @click="openTab('tasks')"><Activity :size="22"/><span><strong>活动项目</strong><small>获取血值 · 参与竞技场</small></span><ChevronRight :size="19"/></button><button @click="openTab('draw')"><Sparkles :size="22"/><span><strong>热血幸运轮</strong><small>{{ draw.status === 'reversed' ? '查看幸运轮状态' : draw.already_drawn ? '查看我的抽取结果' : '抽取初始血值' }}</small></span><ChevronRight :size="19"/></button><button @click="openTab('shop')"><Gift :size="22"/><span><strong>能量兑换</strong><small>道具使用 · 奖励领取</small></span><ChevronRight :size="19"/></button></div>
          <div class="section-heading"><h2>最近记录</h2><button class="icon-button" title="刷新" aria-label="刷新记录" @click="refreshScreen"><RefreshCw :size="16"/></button></div>
          <div class="history-list"><p v-if="!ledger.length" class="empty-state">暂无活动记录，去现场参与项目吧。</p><div v-for="entry in ledger.slice(0, 5)" :key="entry.id" class="history-row"><span class="history-icon" :class="entry.kind"><Droplets v-if="entry.kind === 'blood'" :size="16"/><Zap v-else :size="16"/></span><div><strong>{{ entry.reason }}</strong><small>{{ new Date(entry.created_at).toLocaleString('zh-CN') }}</small></div><b :class="entry.delta > 0 ? 'positive' : 'negative'">{{ entry.delta > 0 ? '+' : '' }}{{ entry.delta }}</b></div></div>
        </main>

        <main v-if="tab === 'tasks'" class="page-content"><div class="page-heading with-action"><div><h1>活动项目</h1><p>参加健康体验获取血值，再到能量竞技场挑战。</p></div><button class="icon-button" title="刷新项目" aria-label="刷新项目" :disabled="busy" @click="refreshScreen"><RefreshCw :size="18"/></button></div>
          <section class="task-section"><div class="task-section-head blood-section"><span><Droplets :size="19"/></span><div><h2>爱心补给 · 获取血值</h2><p>健康体验与生命传递</p></div></div><div class="task-list"><article v-for="task in bloodTasks" :key="task.id" class="task-row"><button class="task-detail" @click="selectedTask = task"><strong>{{ task.title }}</strong><small>{{ task.description }}</small><span>查看活动内容与规则 <ChevronRight :size="14"/></span></button><div class="task-side"><b>+{{ task.blood_reward }} <Droplets :size="13"/></b><button :disabled="busy" @click="selectedTask = task">{{ task.status === 'done' ? '已完成' : task.status === 'pending' ? '待核验' : '查看' }}</button></div></article></div></section>
          <section class="task-section"><div class="task-section-head energy-section"><span><Zap :size="19"/></span><div><h2>能量竞技场</h2><p>每次尝试消耗 1 血值，按成绩获得能量</p></div></div><div class="task-list"><article v-for="task in arenaTasks" :key="task.id" class="task-row"><button class="task-detail" @click="selectedTask = task"><strong>{{ task.title }}</strong><small>{{ task.description }}</small><span>查看游戏规则 <ChevronRight :size="14"/></span></button><div class="task-side"><b><Zap :size="13"/> {{ task.category === 'dart' ? '1–3' : task.energy_per_success }}/次</b><button :disabled="busy" @click="selectedTask = task">{{ task.status === 'pending' ? '待核验' : '查看' }}</button></div></article></div></section>
        </main>

        <main v-if="tab === 'draw'" class="page-content draw-page"><div class="page-heading with-action"><div><h1>热血幸运轮</h1><p>每人可在线抽取一次初始血值。</p></div><button class="icon-button" title="刷新幸运轮" aria-label="刷新幸运轮" :disabled="busy" @click="refreshScreen"><RefreshCw :size="18"/></button></div><div class="wheel-wrap"><WheelResult :result="draw.result" :spin-key="drawSpinKey"/></div><div class="draw-result" :class="{ recorded: draw.status === 'drawn' }"><Sparkles :size="22"/><div><strong>{{ draw.status === 'reversed' ? '幸运轮奖励已撤回' : draw.status === 'drawn' ? `已获得 ${draw.result} 血值` : draw.can_spin ? '幸运轮已开放' : '幸运轮尚未开放' }}</strong><p>{{ draw.status === 'reversed' ? '结果已由工作人员撤回，如有疑问请联系现场工作人员' : draw.status === 'drawn' ? '结果已计入账户，再次打开页面将直接显示' : draw.can_spin ? '每人仅可抽取一次，结果将计入账户' : '温馨提示：活动尚未开启，幸运轮将于 10 月 28 日（星期三）下午 15:00 准时开放，届时即可抽取初始血值，敬请期待！' }}</p></div></div><button v-if="!draw.already_drawn" class="btn primary wide spin-button" :disabled="busy || drawSpinning || !draw.can_spin" @click="spinWheel">{{ drawSpinning ? '抽取中…' : draw.can_spin ? '开始抽取' : '开放后可抽取' }}</button><section class="odds"><h2>幸运轮分布</h2><div v-for="item in bootstrap.draw_prizes" :key="item.blood"><span>{{ item.blood }} 血值</span><span>{{ item.probability }}%</span></div></section></main>

        <main v-if="tab === 'shop'" class="page-content">
          <div class="page-heading"><h1>能量兑换</h1><p>用可用能量兑换奖励，在现场凭兑换码领取。</p></div>
          <div class="balance-banner"><span>可用能量</span><strong>{{ profile.energy }} <Zap :size="21"/></strong></div>
          <section class="boost-panel"><div class="boost-icon"><Zap :size="25"/></div><div><h2>三倍能量道具</h2><p>完成献血可获得一次。使用时将当前累计能量增加两倍，后续新获得的能量正常计分。</p><small v-if="profile.energy_boost_available">当前累计 {{ profile.energy_earned }} → 使用后 {{ profile.energy_earned * 3 }} 能量</small><small v-else-if="profile.energy_boost_used">本次活动已使用</small><small v-else>完成献血并由工作人员核验后解锁</small></div><button class="btn primary" :disabled="busy || !profile.energy_boost_available || profile.energy_earned <= 0" @click="useBoost">{{ profile.energy_boost_used ? '已使用' : '使用' }}</button></section>
          <div class="section-heading"><h2>现场奖励</h2></div>
          <article v-for="prize in prizes" :key="prize.id" class="product-row">
            <div class="product-icon"><Ticket :size="27"/></div>
            <div class="product-info"><h3>{{ prize.title }}</h3><p>{{ prize.description }}</p><small>剩余 {{ prize.stock }} 份 · 每份 {{ prize.price }} 能量</small></div>
            <div class="product-buy"><label :for="'quantity-' + prize.id">兑换份数</label><div class="quantity-stepper"><button type="button" :disabled="busy || (redeemQuantity[prize.id] ?? 1) <= 1" :aria-label="`减少${prize.title}兑换份数`" @click="changeQuantity(prize, -1)"><Minus :size="14"/></button><input :id="'quantity-' + prize.id" v-model.number="redeemQuantity[prize.id]" type="number" min="1" :max="maxQuantity(prize)" step="1" inputmode="numeric"/><button type="button" :disabled="busy || (redeemQuantity[prize.id] ?? 1) >= maxQuantity(prize)" :aria-label="`增加${prize.title}兑换份数`" @click="changeQuantity(prize, 1)"><Plus :size="14"/></button></div><strong>合计 {{ prize.price * (redeemQuantity[prize.id] ?? 1) }} <Zap :size="14"/></strong><button class="btn primary" :disabled="busy || maxQuantity(prize) < 1 || !Number.isInteger(redeemQuantity[prize.id] ?? 1) || (redeemQuantity[prize.id] ?? 1) < 1 || (redeemQuantity[prize.id] ?? 1) > maxQuantity(prize)" @click="redeem(prize)">兑换</button></div>
          </article>
          <div class="section-heading"><h2>我的兑换凭证</h2><span>{{ redemptions.length }} 条</span></div><div class="voucher-list"><p v-if="!redemptions.length" class="empty-state">暂无兑换记录。</p><div v-for="r in redemptions" :key="r.id" class="voucher"><div><strong>{{ r.title }} × {{ r.quantity }} 份</strong><small>凭证码 {{ r.code }} · {{ r.price }} 能量</small></div><span>{{ r.status === 'fulfilled' ? '已领取' : '待领取' }}</span></div></div>
        </main>

        <main v-if="tab === 'rank'" class="page-content"><div class="page-heading"><h1>能量榜单</h1><p>展示累计能量前 {{ ranking.limit }} 名；同分时，先达到该分数者排名更高。</p></div><div class="my-rank"><span>我的当前名次</span><strong>第 {{ ranking.my_rank }} 名</strong><small>{{ ranking.my_position.score }} 能量</small></div><div class="ranking-list"><div v-for="row in ranking.players" :key="row.rank" class="ranking-row" :class="{ 'is-me': row.me, top: row.rank <= 3 }"><span class="rank-number"><Medal v-if="row.rank <= 3" :size="18"/>{{ row.rank }}</span><strong>{{ row.name }} <em v-if="row.me">我</em></strong><span>{{ row.score }} <Zap :size="14"/></span></div><p v-if="!ranking.players.length" class="empty-state">暂无能量记录。</p></div><div v-if="ranking.my_rank > ranking.limit" class="my-rank-row"><span>我的排名</span><strong>第 {{ ranking.my_rank }} 名</strong><span>{{ ranking.my_position.score }} 能量</span></div><p class="rank-note">兑换只扣可用能量，不影响累计能量排名。</p></main>

        <nav class="bottom-nav" aria-label="主导航"><button v-for="item in navItems" :key="item.id" :class="{ active: tab === item.id }" @click="openTab(item.id)"><component :is="item.icon" :size="20"/><span>{{ item.label }}</span></button></nav>
      </div>
      <div v-if="selectedTask" class="modal-backdrop" @click.self="selectedTask = null"><section class="task-modal" role="dialog" aria-modal="true" :aria-label="selectedTask.title"><button class="modal-close icon-button" aria-label="关闭" @click="selectedTask = null"><X :size="20"/></button><span class="modal-label">{{ selectedTask.category === 'volunteer' ? '爱心补给' : '能量竞技场' }}</span><h2>{{ selectedTask.title }}</h2><p>{{ selectedTask.description }}</p><h3>活动内容与规则</h3><ul><li v-for="rule in selectedTaskRules" :key="rule">{{ rule }}</li></ul><div class="modal-actions"><button class="btn quiet" @click="selectedTask = null">关闭</button><button v-if="selectedTask.status === 'available'" class="btn primary" :disabled="busy" @click="claimSelectedTask">申请核验</button><span v-else>{{ selectedTask.status === 'pending' ? '等待工作人员核验' : '已完成' }}</span></div></section></div>
    </template>

    <transition name="toast"><div v-if="error" class="flash error" role="alert" @click="clearToast">{{ error }} <X :size="16"/></div><div v-else-if="success" class="flash success" role="status" @click="clearToast">{{ success }} <X :size="16"/></div></transition>
  </div>
</template>
