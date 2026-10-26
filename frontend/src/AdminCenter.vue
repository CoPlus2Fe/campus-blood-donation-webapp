<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ArrowLeft, Check, ChevronDown, CircleAlert, ClipboardList, FileClock, Gift,
  LogOut, Pencil, Plus, RefreshCw, Search, ShieldCheck, Users, X,
} from 'lucide-vue-next'
import { api } from './api'
import './admin.css'

type Identity = 'student' | 'staff'
type ClaimStatus = 'pending' | 'completed' | 'rejected' | 'reversed'
type Role = 'super' | 'project'
type Tab = 'claims' | 'audit' | 'people' | 'redemptions' | 'tasks' | 'prizes' | 'accounts'

interface AdminMe { id: number; username: string; role: Role; task_ids: number[] }
interface AdminSummary { participants: number | null; pending_claims: number; pending_redemptions: number | null }
interface Task {
  id: number; code: string; title: string; description: string; category: string;
  blood_reward: number; energy_reward: number; blood_per_attempt: number;
  energy_per_success: number; min_success: number; max_claims: number | null;
  exclusive_group: string | null; active: boolean
}
interface Prize { id: number; code: string; title: string; description: string; energy_price: number; stock: number; max_per_player: number | null; active: boolean }
interface Claim {
  id: number; task_id: number; title: string; description: string; category: string;
  participant_id: number; name: string; student_id: string; status: ClaimStatus;
  created_at: string; completed_at: string | null; blood_delta: number; energy_delta: number;
  attempts: number; successes: number; blood_reward: number; energy_reward: number;
  blood_per_attempt: number; energy_per_success: number; min_success: number;
  rings10?: number; rings9?: number; rings8?: number;
}
interface Participant {
  id: number; name: string; student_id: string; identity: Identity; college: string | null;
  class_name: string; phone: string; blood: number; energy: number;
  energy_earned: number; active: boolean; draw_blood: number | null;
  draw_status: 'not_drawn' | 'drawn' | 'reversed'; boost_recorded: boolean
}
interface Redemption { id: number; participant_id: number; name: string; student_id: string; title: string; code: string; price: number; quantity: number; status: string }
interface StaffAccount { id: number; username: string; role: Role; task_ids: number[]; active: boolean }
interface AuditEvent {
  id: number; claim_id: number; task_id: number; participant_id: number; task: string; name: string; staff_name: string;
  action: string; reason: string; before_status: string; after_status: string;
  before_blood: number | null; after_blood: number | null;
  before_energy: number | null; after_energy: number | null; created_at: string
}
interface AuditPage { items: AuditEvent[]; next_offset: number | null }
interface DrawHistory { id: number; action: string; reason: string; before_blood: number; after_blood: number; staff_name: string; created_at: string }
interface DrawDetail { participant_id: number; draw_id: number; original_blood: number; blood: number | null; status: 'drawn' | 'reversed'; history: DrawHistory[] }
interface BoostHistory { id: number; action: string; reason: string; before_bonus: number; after_bonus: number; staff_name: string; created_at: string }
interface BoostDetail { participant_id: number; boost_ledger_id: number; original_bonus: number; bonus: number; status: 'active' | 'reversed'; used: boolean; history: BoostHistory[] }
const auditLabels: Record<string, string> = { complete: '确认完成', reject: '拒绝申请', adjust: '修改分数', reverse: '撤回结算' }
interface ClaimEntry { attempts: number; successes: number; rings10: number; rings9: number; rings8: number }
interface ClaimCorrection { blood_delta: number; energy_delta: number; reason: string }
interface ParticipantDraft { identity: Identity; college: string; class_name: string; name: string; student_id: string; phone: string }
interface TaskDraft {
  code: string; title: string; description: string; category: string;
  blood_reward: number; energy_reward: number; blood_per_attempt: number;
  energy_per_success: number; min_success: number; max_claims: number | null;
  exclusive_group: string; active: boolean
}
interface PrizeDraft { code: string; title: string; description: string; energy_price: number; stock: number; max_per_player: number | null; active: boolean }

const colleges = [
  '计算机科学与工程学院', '机械与能源工程学院', '材料科学与工程学院',
  '食品科学与工程学院', '商学院',
]
const staffColleges = [...colleges, '其他']
const claimStatuses: { id: ClaimStatus; label: string }[] = [
  { id: 'pending', label: '待核验' }, { id: 'completed', label: '已完成' },
  { id: 'rejected', label: '已拒绝' }, { id: 'reversed', label: '已撤回' },
]
const roleLabels: Record<Role, string> = { super: '最高级权限', project: '项目权限' }
const categoryLabels: Record<string, string> = { checkin: '注册', volunteer: '血值项目', game: '能量竞技场', dart: '能量竞技场' }
const emptyParticipant = (): ParticipantDraft => ({ identity: 'student', college: '', class_name: '', name: '', student_id: '', phone: '' })
const emptyTask = (): TaskDraft => ({ code: '', title: '', description: '', category: 'volunteer', blood_reward: 0, energy_reward: 0, blood_per_attempt: 0, energy_per_success: 0, min_success: 0, max_claims: 1, exclusive_group: '', active: true })
const emptyPrize = (): PrizeDraft => ({ code: '', title: '', description: '', energy_price: 0, stock: 0, max_per_player: null, active: true })

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const success = ref('')
const username = ref('')
const password = ref('')
const me = ref<AdminMe | null>(null)
const summary = ref<AdminSummary | null>(null)
const tab = ref<Tab>('claims')
const status = ref<ClaimStatus>('pending')
const search = ref('')
const taskFilter = ref(0)
const tasks = ref<Task[]>([])
const prizes = ref<Prize[]>([])
const claims = ref<Claim[]>([])
const auditEvents = ref<AuditEvent[]>([])
const auditNextOffset = ref<number | null>(null)
const participants = ref<Participant[]>([])
const drawEditor = ref<number | null>(null)
const drawDetail = ref<DrawDetail | null>(null)
const drawValue = ref(10)
const drawReason = ref('')
const boostEditor = ref<number | null>(null)
const boostDetail = ref<BoostDetail | null>(null)
const boostValue = ref(1)
const boostReason = ref('')
const redemptions = ref<Redemption[]>([])
const redemptionStatus = ref('pending')
const accounts = ref<StaffAccount[]>([])
const entries = ref<Record<number, ClaimEntry>>({})
const corrections = ref<Record<number, ClaimCorrection>>({})
const correctionClaim = ref<number | null>(null)
const personSearch = ref('')
const editingParticipant = ref<number | null>(null)
const person = ref<ParticipantDraft>(emptyParticipant())
const generated = ref<{ id: number; student_id: string; bind_code: string } | null>(null)
const editingTask = ref<number | null>(null)
const taskDraft = ref<TaskDraft>(emptyTask())
const editingPrize = ref<number | null>(null)
const prizeDraft = ref<PrizeDraft>(emptyPrize())
const editingAccount = ref<number | null>(null)
const accountUsername = ref('')
const accountPassword = ref('')
const accountRole = ref<Role>('project')
const accountTaskIds = ref<number[]>([])
const accountActive = ref(true)

const isSuper = computed(() => me.value?.role === 'super')
const allowedTasks = computed(() => tasks.value.filter(t => t.category !== 'checkin' && (isSuper.value || me.value?.task_ids.includes(t.id))))
const visibleTabs = computed(() => {
  const claimTab = [{ id: 'claims' as Tab, label: '项目核验', icon: ClipboardList }]
  return isSuper.value ? [
    ...claimTab, { id: 'audit' as Tab, label: '处理流水', icon: FileClock },
    { id: 'people' as Tab, label: '参与者', icon: Users },
    { id: 'redemptions' as Tab, label: '兑换核销', icon: Gift },
    { id: 'tasks' as Tab, label: '项目配置', icon: ClipboardList },
    { id: 'prizes' as Tab, label: '奖品配置', icon: Gift },
    { id: 'accounts' as Tab, label: '工作人员', icon: ShieldCheck },
  ] : claimTab
})
let toastTimeout: number | undefined
function notify(kind: 'error' | 'success', message: string) {
  if (toastTimeout) window.clearTimeout(toastTimeout)
  error.value = kind === 'error' ? message : ''
  success.value = kind === 'success' ? message : ''
  toastTimeout = window.setTimeout(() => { error.value = ''; success.value = '' }, 3000)
}
function time(iso: string | null) {
  return iso ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short', hour12: false }).format(new Date(iso)) : '—'
}
function query(path: string, values: Record<string, string | number>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value !== '' && value !== 0) params.set(key, String(value)) })
  return path + (params.size ? `?${params}` : '')
}
function claimEntry(id: number): ClaimEntry {
  if (!entries.value[id]) entries.value[id] = { attempts: 0, successes: 0, rings10: 0, rings9: 0, rings8: 0 }
  return entries.value[id]
}
async function action(fn: () => Promise<void>, message?: string) {
  if (busy.value) return
  busy.value = true
  try {
    await fn()
    if (message) notify('success', message)
  } catch (cause) { notify('error', cause instanceof Error ? cause.message : '操作失败，请重试') }
  finally { busy.value = false }
}
async function loadClaims() {
  claims.value = await api<Claim[]>(query('/admin/claims', { status: status.value, q: search.value.trim(), task_id: taskFilter.value }))
}
async function loadAudit() {
  const page = await api<AuditPage>(query('/admin/claim-audit', { task_id: taskFilter.value, q: search.value.trim(), limit: 50 }))
  auditEvents.value = page.items
  auditNextOffset.value = page.next_offset
}
function loadMoreAudit() {
  if (auditNextOffset.value === null) return
  void action(async () => {
    const page = await api<AuditPage>(query('/admin/claim-audit', {
      task_id: taskFilter.value, q: search.value.trim(), offset: auditNextOffset.value ?? 0, limit: 50,
    }))
    const ids = new Set(auditEvents.value.map(event => event.id))
    auditEvents.value.push(...page.items.filter(event => !ids.has(event.id)))
    auditNextOffset.value = page.next_offset
  })
}
async function loadParticipants() {
  participants.value = await api<Participant[]>(query('/admin/participants', { q: personSearch.value.trim() }))
}
async function loadTab() {
  if (tab.value === 'claims') await loadClaims()
  else if (tab.value === 'audit') await loadAudit()
  else if (tab.value === 'people') await loadParticipants()
  else if (tab.value === 'redemptions') redemptions.value = await api<Redemption[]>(query('/admin/redemptions', { q: search.value.trim(), status: redemptionStatus.value }))
  else if (tab.value === 'tasks') tasks.value = await api<Task[]>('/admin/tasks')
  else if (tab.value === 'prizes') prizes.value = await api<Prize[]>('/admin/prizes')
  else if (tab.value === 'accounts') accounts.value = await api<StaffAccount[]>('/admin/staff')
}
async function refresh() {
  tasks.value = await api<Task[]>('/admin/tasks')
  summary.value = await api<AdminSummary>(query('/admin/summary', { task_id: (tab.value === 'claims' || tab.value === 'audit') ? taskFilter.value : 0 }))
  await loadTab()
}
async function initialize() {
  try {
    me.value = await api<AdminMe>('/admin/me')
    await refresh()
  } catch (cause) {
    if (me.value) notify('error', cause instanceof Error ? cause.message : '管理数据暂时无法加载')
    else me.value = null
  } finally { loading.value = false }
}
function login() {
  void action(async () => {
    await api('/admin/login', 'POST', { username: username.value.trim(), password: password.value })
    password.value = ''
    me.value = await api<AdminMe>('/admin/me')
    tab.value = 'claims'; status.value = 'pending'; taskFilter.value = 0; search.value = ''; personSearch.value = ''
    await refresh()
  })
}
function logout() {
  void action(async () => {
    await api('/admin/logout', 'POST')
    me.value = null
    password.value = ''
    username.value = ''
    tab.value = 'claims'; status.value = 'pending'; taskFilter.value = 0; search.value = ''; personSearch.value = ''
    claims.value = []
    participants.value = []
  })
}
function chooseTab(next: Tab) {
  if (tab.value === next) return
  tab.value = next
  search.value = ''
  void action(refresh)
}
function chooseStatus(next: ClaimStatus) {
  if (status.value === next) return
  status.value = next
  void action(loadClaims)
}
function completeClaim(claim: Claim) {
  const entry = entries.value[claim.id] ?? { attempts: 0, successes: 0, rings10: 0, rings9: 0, rings8: 0 }
  void action(async () => {
    await api(`/admin/claims/${claim.id}/complete`, 'POST', entry)
    await refresh()
  }, '已核验并录入分数')
}
function rejectClaim(claim: Claim) {
  if (!confirm(`拒绝 ${claim.name} 的“${claim.title}”申请？拒绝不会计分。`)) return
  void action(async () => {
    await api(`/admin/claims/${claim.id}/reject`, 'POST')
    await refresh()
  }, '申请已拒绝')
}
function adjustClaim(claim: Claim) {
  const draft = corrections.value[claim.id]
  if (!draft?.reason.trim()) return notify('error', '请填写改分原因')
  if (!confirm(`确认将 ${claim.name} 此项目的结算改为血值 ${draft.blood_delta}、能量 ${draft.energy_delta}？`)) return
  void action(async () => {
    await api(`/admin/claims/${claim.id}/adjust`, 'POST', { blood_delta: draft.blood_delta, energy_delta: draft.energy_delta, reason: draft.reason.trim() })
    correctionClaim.value = null
    await refresh()
  }, '分数已修改，处理记录已保存')
}
function reverseClaim(claim: Claim) {
  const reason = window.prompt(`撤回 ${claim.name} 的“${claim.title}”加分，请填写原因`)
  if (reason === null) return
  if (!reason.trim()) return notify('error', '请填写撤回原因')
  if (!confirm('确认撤回这次结算？参与者的血值和能量会同步调整。')) return
  void action(async () => {
    await api(`/admin/claims/${claim.id}/reverse`, 'POST', { reason: reason.trim() })
    await refresh()
  }, '结算已撤回，处理记录已保存')
}
function startCorrection(claim: Claim) {
  correctionClaim.value = correctionClaim.value === claim.id ? null : claim.id
  corrections.value[claim.id] = { blood_delta: claim.blood_delta, energy_delta: claim.energy_delta, reason: '' }
}
function resetParticipant() { editingParticipant.value = null; person.value = emptyParticipant(); generated.value = null }
function editParticipant(p: Participant) {
  editingParticipant.value = p.id
  person.value = { identity: p.identity, college: p.college ?? '', class_name: p.class_name, name: p.name, student_id: p.student_id, phone: p.phone }
  generated.value = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function saveParticipant() {
  const value = person.value
  const creating = editingParticipant.value === null
  if (value.identity === 'student' && !/^\d{12}$/.test(value.student_id)) return notify('error', '学号应为 12 位数字')
  if (!(value.identity === 'student' ? colleges : staffColleges).includes(value.college)) return notify('error', '请选择学院')
  if (!/^\d{11}$/.test(value.phone)) return notify('error', '联系电话应为 11 位数字')
  void action(async () => {
    const body = { ...value, class_name: value.identity === 'student' ? value.class_name : '',
      college: value.college, student_id: value.student_id.trim() }
    if (editingParticipant.value !== null) await api(`/admin/participants/${editingParticipant.value}`, 'PATCH', body)
    else generated.value = await api<{ id: number; student_id: string; bind_code: string }>('/admin/participants', 'POST', body)
    editingParticipant.value = null
    person.value = emptyParticipant()
    await loadParticipants()
    summary.value = await api<AdminSummary>('/admin/summary')
  }, creating ? '参与者已创建' : '参与者资料已更新')
}
function setParticipantActive(p: Participant) {
  if (!confirm(`${p.active ? '停用' : '启用'} ${p.name} 的参与者账号？`)) return
  void action(async () => {
    await api(`/admin/participants/${p.id}`, p.active ? 'DELETE' : 'PATCH', p.active ? undefined : { active: true })
    await loadParticipants()
  }, '账号状态已更新')
}
function toggleDrawEditor(p: Participant) {
  if (drawEditor.value === p.id) { drawEditor.value = null; drawDetail.value = null; return }
  drawEditor.value = p.id
  drawDetail.value = null
  drawReason.value = ''
  void action(async () => {
    drawDetail.value = await api<DrawDetail>(`/admin/draws/${p.id}`)
    drawValue.value = drawDetail.value.blood ?? drawDetail.value.original_blood
  })
}
function adjustDraw(p: Participant) {
  if (!drawReason.value.trim()) return notify('error', '请填写修正原因')
  if (drawValue.value === drawDetail.value?.blood) return notify('error', '请选择不同的幸运轮结果')
  if (!confirm(`将 ${p.name} 的幸运轮结果改为 ${drawValue.value} 血值？`)) return
  void action(async () => {
    await api(`/admin/draws/${p.id}`, 'PATCH', { blood: drawValue.value, reason: drawReason.value.trim() })
    await loadParticipants()
    drawDetail.value = await api<DrawDetail>(`/admin/draws/${p.id}`)
    drawReason.value = ''
  }, '幸运轮结果已修正，操作已记录')
}
function reverseDraw(p: Participant) {
  if (!drawReason.value.trim()) return notify('error', '请填写撤回原因')
  if (!confirm(`撤回 ${p.name} 的幸运轮加分？该参与者的血值会同步调整。`)) return
  void action(async () => {
    await api(`/admin/draws/${p.id}/reverse`, 'POST', { reason: drawReason.value.trim() })
    await loadParticipants()
    drawDetail.value = await api<DrawDetail>(`/admin/draws/${p.id}`)
    drawReason.value = ''
  }, '幸运轮加分已撤回，操作已记录')
}
function toggleBoostEditor(p: Participant) {
  if (boostEditor.value === p.id) { boostEditor.value = null; boostDetail.value = null; return }
  boostEditor.value = p.id
  boostDetail.value = null
  boostReason.value = ''
  void action(async () => {
    try { boostDetail.value = await api<BoostDetail>(`/admin/energy-boosts/${p.id}`) }
    catch (cause) { boostEditor.value = null; throw cause }
    boostValue.value = boostDetail.value.bonus || boostDetail.value.original_bonus
  })
}
function adjustBoost(p: Participant) {
  if (!Number.isInteger(boostValue.value) || boostValue.value < 1 || boostValue.value > 1_000_000) return notify('error', '奖励能量应为 1 至 1000000 的整数')
  if (!boostReason.value.trim()) return notify('error', '请填写修正原因')
  if (boostValue.value === boostDetail.value?.bonus) return notify('error', '请填写不同的奖励能量')
  if (!confirm(`将 ${p.name} 的三倍能量道具奖励修正为 ${boostValue.value} 能量？`)) return
  void action(async () => {
    await api(`/admin/energy-boosts/${p.id}`, 'PATCH', { bonus: boostValue.value, reason: boostReason.value.trim() })
    await loadParticipants()
    boostDetail.value = await api<BoostDetail>(`/admin/energy-boosts/${p.id}`)
    boostReason.value = ''
  }, '道具奖励已修正，操作已记录')
}
function reverseBoost(p: Participant) {
  if (!boostReason.value.trim()) return notify('error', '请填写撤回原因')
  if (!confirm(`撤回 ${p.name} 的三倍能量道具奖励？该参与者的能量会同步调整。`)) return
  void action(async () => {
    await api(`/admin/energy-boosts/${p.id}/reverse`, 'POST', { reason: boostReason.value.trim() })
    await loadParticipants()
    boostDetail.value = await api<BoostDetail>(`/admin/energy-boosts/${p.id}`)
    boostReason.value = ''
  }, '道具奖励已撤回，操作已记录')
}
function setRedemption(r: Redemption, operation: 'fulfill' | 'cancel') {
  if (!confirm(operation === 'fulfill' ? `确认核对 ${r.code} 并发放奖品？` : `取消 ${r.code} 的兑换并退回能量？`)) return
  void action(async () => {
    await api(`/admin/redemptions/${r.id}/${operation}`, 'POST')
    await refresh()
  }, operation === 'fulfill' ? '已核销' : '兑换已取消')
}
function editTask(t: Task) {
  editingTask.value = t.id
  taskDraft.value = { ...t, exclusive_group: t.exclusive_group ?? '' }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function saveTask() {
  const creating = editingTask.value === null
  void action(async () => {
    const body = { ...taskDraft.value, max_claims: taskDraft.value.max_claims || null, exclusive_group: taskDraft.value.exclusive_group || null }
    if (editingTask.value !== null) await api(`/admin/tasks/${editingTask.value}`, 'PATCH', body)
    else await api('/admin/tasks', 'POST', body)
    editingTask.value = null
    taskDraft.value = emptyTask()
    tasks.value = await api<Task[]>('/admin/tasks')
  }, creating ? '项目已创建' : '项目已更新')
}
function toggleTask(t: Task) {
  if (!confirm(`${t.active ? '下架' : '恢复'}“${t.title}”？`)) return
  void action(async () => {
    await api(`/admin/tasks/${t.id}`, t.active ? 'DELETE' : 'PATCH', t.active ? undefined : { active: true })
    tasks.value = await api<Task[]>('/admin/tasks')
  }, '项目状态已更新')
}
function editPrize(p: Prize) {
  editingPrize.value = p.id
  prizeDraft.value = { ...p }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function savePrize() {
  const creating = editingPrize.value === null
  void action(async () => {
    const body = { ...prizeDraft.value, max_per_player: prizeDraft.value.max_per_player || null }
    if (editingPrize.value !== null) await api(`/admin/prizes/${editingPrize.value}`, 'PATCH', body)
    else await api('/admin/prizes', 'POST', body)
    editingPrize.value = null
    prizeDraft.value = emptyPrize()
    prizes.value = await api<Prize[]>('/admin/prizes')
  }, creating ? '奖品已创建' : '奖品已更新')
}
function togglePrize(p: Prize) {
  if (!confirm(`${p.active ? '下架' : '恢复'}“${p.title}”？`)) return
  void action(async () => {
    await api(`/admin/prizes/${p.id}`, p.active ? 'DELETE' : 'PATCH', p.active ? undefined : { active: true })
    prizes.value = await api<Prize[]>('/admin/prizes')
  }, '奖品状态已更新')
}
function resetAccount() {
  editingAccount.value = null; accountUsername.value = ''; accountPassword.value = ''
  accountRole.value = 'project'; accountTaskIds.value = []; accountActive.value = true
}
function editAccount(account: StaffAccount) {
  editingAccount.value = account.id
  accountUsername.value = account.username
  accountPassword.value = ''
  accountRole.value = account.role
  accountTaskIds.value = account.task_ids.filter(id => tasks.value.some(task => task.id === id && task.active))
  accountActive.value = account.active
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function saveAccount() {
  if (accountRole.value === 'project' && accountTaskIds.value.length === 0) return notify('error', '请选择至少一个可核验项目')
  const creating = editingAccount.value === null
  const editingSelf = editingAccount.value !== null && editingAccount.value === me.value?.id
  void action(async () => {
    const body: { username: string; role: Role; task_ids: number[]; active: boolean; password?: string } = {
      username: accountUsername.value.trim(), role: accountRole.value,
      task_ids: accountRole.value === 'super' ? [] : accountTaskIds.value,
      active: accountActive.value,
    }
    if (accountPassword.value) body.password = accountPassword.value
    if (editingAccount.value !== null) await api(`/admin/staff/${editingAccount.value}`, 'PATCH', body)
    else await api('/admin/staff', 'POST', body)
    resetAccount()
    if (editingSelf) me.value = null
    else accounts.value = await api<StaffAccount[]>('/admin/staff')
  }, editingSelf ? '账号已更新，请重新登录' : creating ? '工作人员账号已创建' : '工作人员账号已更新')
}
function setAccountActive(account: StaffAccount) {
  if (!confirm(`${account.active ? '停用' : '启用'}账号“${account.username}”？`)) return
  void action(async () => {
    await api(`/admin/staff/${account.id}`, account.active ? 'DELETE' : 'PATCH', account.active ? undefined : { active: true })
    accounts.value = await api<StaffAccount[]>('/admin/staff')
  }, '账号状态已更新')
}
onMounted(() => { void initialize() })
onUnmounted(() => { if (toastTimeout) window.clearTimeout(toastTimeout) })
</script>

<template>
  <main class="staff-center">
    <header class="staff-head">
      <div><a href="/" class="staff-brand">热血行动</a><h1>工作人员中心</h1></div>
      <a href="/" class="staff-return"><ArrowLeft :size="16"/> 参与者页面</a>
    </header>

    <p v-if="loading" class="staff-loading" role="status">正在加载管理中心…</p>
    <section v-else-if="!me" class="staff-login" aria-labelledby="staff-login-title">
      <ShieldCheck :size="29" aria-hidden="true"/><h2 id="staff-login-title">工作人员登录</h2>
      <p>使用已分配权限的账号进入。</p>
      <form @submit.prevent="login">
        <label>用户名<input v-model.trim="username" autocomplete="username" required maxlength="80"/></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" required/></label>
        <button class="staff-button primary" :disabled="busy" type="submit">登录</button>
      </form>
    </section>

    <template v-else>
      <div class="staff-accountbar"><span><ShieldCheck :size="16"/> {{ me.username }} · {{ roleLabels[me.role] }}</span><button class="staff-icon" :disabled="busy" title="刷新数据" aria-label="刷新数据" @click="action(refresh)"><RefreshCw :size="17"/></button><button class="staff-logout" :disabled="busy" @click="logout"><LogOut :size="16"/> 退出</button></div>
      <div v-if="summary" class="staff-summary" aria-label="当前概况">
        <p v-if="isSuper"><span>参与者</span><strong>{{ summary.participants }}</strong></p>
        <p><span>待核验</span><strong>{{ summary.pending_claims }}</strong></p>
        <p v-if="isSuper"><span>待核销</span><strong>{{ summary.pending_redemptions }}</strong></p>
      </div>

      <nav class="staff-tabs" aria-label="管理功能">
        <button v-for="item in visibleTabs" :key="item.id" :class="{ active: tab === item.id }" :aria-current="tab === item.id ? 'page' : undefined" @click="chooseTab(item.id)"><component :is="item.icon" :size="16"/> {{ item.label }}</button>
      </nav>

      <template v-if="tab === 'claims' || tab === 'audit'">
        <div class="staff-tools">
          <label class="staff-select">项目<span class="staff-select-wrap"><select v-model.number="taskFilter" @change="action(refresh)"><option :value="0">{{ isSuper ? '全部项目' : '已授权项目' }}</option><option v-for="t in allowedTasks" :key="t.id" :value="t.id">{{ t.title }}</option></select><ChevronDown :size="15"/></span></label>
          <form class="staff-search" @submit.prevent="action(loadTab)"><label class="visually-hidden" for="staff-search-input">搜索编号、姓名、学号/工号或项目</label><Search :size="17"/><input id="staff-search-input" v-model="search" placeholder="编号、姓名或项目"/><button type="submit" class="staff-button secondary" :disabled="busy">搜索</button></form>
        </div>
      </template>

      <template v-if="tab === 'claims'">
        <div class="staff-segments" role="group" aria-label="申请状态"><button v-for="s in claimStatuses.filter(s => isSuper || s.id !== 'reversed')" :key="s.id" :class="{ active: status === s.id }" @click="chooseStatus(s.id)">{{ s.label }}</button></div>
        <p v-if="!claims.length" class="staff-empty">没有符合条件的申请。</p>
        <div v-else class="staff-rows">
          <article v-for="claim in claims" :key="claim.id" class="staff-row">
            <div class="staff-row-heading"><div><h2>{{ claim.title }}</h2><p>{{ claim.name }} · 编号 {{ claim.participant_id }} · {{ claim.student_id }}</p></div><span class="staff-status" :class="claim.status">{{ claimStatuses.find(s => s.id === claim.status)?.label ?? claim.status }}</span></div>
            <div class="staff-meta"><span>申请 {{ time(claim.created_at) }}</span><span v-if="claim.completed_at">结算 {{ time(claim.completed_at) }}</span><span v-if="claim.status === 'completed'">血值 {{ claim.blood_delta > 0 ? '+' : '' }}{{ claim.blood_delta }} · 能量 {{ claim.energy_delta > 0 ? '+' : '' }}{{ claim.energy_delta }}</span></div>
            <template v-if="claim.status === 'pending'">
              <div v-if="claim.category === 'game' || claim.category === 'dart'" class="staff-numbers">
                <label>尝试次数<input v-model.number="claimEntry(claim.id).attempts" type="number" min="1" max="200" step="1" inputmode="numeric"/></label>
                <label v-if="claim.category === 'game'">成功次数<input v-model.number="claimEntry(claim.id).successes" type="number" min="0" max="200" step="1" inputmode="numeric"/></label>
                <template v-else><label>10 环<input v-model.number="claimEntry(claim.id).rings10" type="number" min="0" max="200" step="1" inputmode="numeric"/></label><label>9 环<input v-model.number="claimEntry(claim.id).rings9" type="number" min="0" max="200" step="1" inputmode="numeric"/></label><label>8 环<input v-model.number="claimEntry(claim.id).rings8" type="number" min="0" max="200" step="1" inputmode="numeric"/></label></template>
              </div>
              <div class="staff-actions"><button class="staff-button secondary" :disabled="busy" @click="rejectClaim(claim)">拒绝</button><button class="staff-button primary" :disabled="busy" @click="completeClaim(claim)"><Check :size="16"/> 确认完成</button></div>
            </template>
            <template v-if="isSuper && claim.status === 'completed'">
              <div class="staff-actions"><button class="staff-button secondary" :disabled="busy" @click="startCorrection(claim)"><Pencil :size="15"/> 修改分数</button><button class="staff-button danger" :disabled="busy" @click="reverseClaim(claim)">撤回结算</button></div>
              <form v-if="correctionClaim === claim.id" class="staff-correction" @submit.prevent="adjustClaim(claim)">
                <label>血值变化<input v-model.number="corrections[claim.id]!.blood_delta" type="number" step="1" required/></label>
                <label>能量变化<input v-model.number="corrections[claim.id]!.energy_delta" type="number" step="1" required/></label>
                <label class="wide">修改原因<input v-model.trim="corrections[claim.id]!.reason" maxlength="200" required placeholder="填写原因，留存处理记录"/></label>
                <button class="staff-button primary" type="submit" :disabled="busy">保存修改</button>
              </form>
            </template>
          </article>
        </div>
      </template>

      <section v-else-if="tab === 'audit'" class="staff-section" aria-labelledby="audit-title">
        <h2 id="audit-title">任务核验流水</h2>
        <p v-if="!auditEvents.length" class="staff-empty">没有符合条件的处理记录。</p>
        <ol v-else class="staff-timeline"><li v-for="event in auditEvents" :key="event.id"><span class="staff-time">{{ time(event.created_at) }}</span><div><strong>{{ auditLabels[event.action] ?? event.action }}</strong><p>{{ event.task }} · {{ event.name }} · 编号 {{ event.participant_id }}</p><small>{{ event.staff_name }} · {{ event.reason }} · {{ event.before_status }} → {{ event.after_status }}<template v-if="event.before_blood !== null"> · 血值 {{ event.before_blood }} → {{ event.after_blood }}，能量 {{ event.before_energy }} → {{ event.after_energy }}</template></small></div></li></ol>
        <button v-if="auditNextOffset !== null" type="button" class="staff-button secondary staff-load-more" :disabled="busy" @click="loadMoreAudit">加载更多记录</button>
      </section>

      <section v-else-if="tab === 'people'" class="staff-section" aria-labelledby="people-title">
        <div class="staff-section-heading"><h2 id="people-title">参与者资料</h2><span>{{ participants.length }} 人</span></div>
        <form class="staff-editor" @submit.prevent="saveParticipant"><h3>{{ editingParticipant === null ? '新增参与者' : '编辑参与者' }}</h3>
          <div class="staff-fields">
            <label>身份<select v-model="person.identity" @change="person.college = ''; person.class_name = ''"><option value="student">学生</option><option value="staff">教职工</option></select></label>
            <label>姓名<input v-model.trim="person.name" autocomplete="name" maxlength="80" required/></label>
            <label v-if="person.identity === 'student'">班级<input v-model.trim="person.class_name" maxlength="80" required/></label>
            <label>{{ person.identity === 'student' ? '学号' : '工号' }}<input v-model.trim="person.student_id" :inputmode="person.identity === 'student' ? 'numeric' : 'text'" :pattern="person.identity === 'student' ? '[0-9]{12}' : undefined" :maxlength="person.identity === 'student' ? 12 : 40" :placeholder="person.identity === 'student' ? '填写学号' : '填写工号'" required/></label>
            <label>学院<select v-model="person.college" required><option value="" disabled>请选择学院</option><option v-for="college in person.identity === 'student' ? colleges : staffColleges" :key="college" :value="college">{{ college }}</option></select></label>
            <label>联系电话<input v-model.trim="person.phone" type="tel" autocomplete="tel" inputmode="numeric" pattern="[0-9]{11}" maxlength="11" placeholder="填写联系电话" required/></label>
          </div>
          <div class="staff-actions"><button v-if="editingParticipant !== null" type="button" class="staff-button secondary" @click="resetParticipant">取消</button><button type="submit" class="staff-button primary" :disabled="busy">{{ editingParticipant === null ? '新增参与者' : '保存资料' }}</button></div>
          <p v-if="generated" class="staff-reveal">新增成功：编号 {{ generated.id }} · {{ generated.student_id }}<br/>绑定码：<strong>{{ generated.bind_code }}</strong><br/><small>绑定码只展示本次，请妥善交付本人。</small></p>
        </form>
        <form class="staff-search standalone" @submit.prevent="action(loadParticipants)"><Search :size="17"/><label class="visually-hidden" for="staff-person-search">搜索编号、姓名、学号/工号或联系电话</label><input id="staff-person-search" v-model="personSearch" placeholder="编号、姓名或学号/工号"/><button class="staff-button secondary" type="submit" :disabled="busy">搜索</button></form>
        <p v-if="!participants.length" class="staff-empty">未找到参与者。</p>
        <div v-else class="staff-rows">
          <article v-for="p in participants" :key="p.id" class="staff-row staff-listrow">
            <div><h3>{{ p.name }}</h3><p>编号 {{ p.id }} · {{ p.identity === 'staff' ? '教职工' : '学生' }} · {{ p.student_id }}<template v-if="p.college"> · {{ p.college }}</template><template v-else-if="p.identity === 'student'"> · {{ p.class_name }}</template></p><small>{{ p.phone }} · {{ p.blood }} 血值 · {{ p.energy }} 能量<template v-if="p.draw_status === 'drawn'"> · 幸运轮 {{ p.draw_blood }} 血值</template><template v-else-if="p.draw_status === 'reversed'"> · 幸运轮加分已撤回</template></small></div>
            <div class="staff-actions"><span v-if="!p.active" class="staff-status rejected">已停用</span><button v-if="p.draw_status !== 'not_drawn'" class="staff-button secondary" :disabled="busy" :aria-expanded="drawEditor === p.id" @click="toggleDrawEditor(p)">幸运轮结果</button><button v-if="p.boost_recorded" class="staff-button secondary" :disabled="busy" :aria-expanded="boostEditor === p.id" @click="toggleBoostEditor(p)">三倍道具奖励</button><button class="staff-icon" :aria-label="`编辑${p.name}`" title="编辑资料" @click="editParticipant(p)"><Pencil :size="16"/></button><button class="staff-button secondary" :disabled="busy" @click="setParticipantActive(p)">{{ p.active ? '停用' : '启用' }}</button></div>
            <div v-if="drawEditor === p.id && drawDetail" class="staff-draw-editor">
              <h4>幸运轮结果 · 初始 {{ drawDetail.original_blood }} 血值，当前 {{ drawDetail.blood ?? '已撤回' }}</h4>
              <form class="staff-draw-fields" @submit.prevent="adjustDraw(p)">
                <label>修正为<select v-model.number="drawValue"><option v-for="blood in [10, 15, 20, 25, 30]" :key="blood" :value="blood">{{ blood }} 血值</option></select></label>
                <label>处理原因<input v-model.trim="drawReason" maxlength="255" placeholder="填写原因，留存处理记录" required/></label>
                <button class="staff-button primary" type="submit" :disabled="busy">保存修正</button>
                <button v-if="drawDetail.status === 'drawn'" class="staff-button danger" type="button" :disabled="busy" @click="reverseDraw(p)">撤回加分</button>
              </form>
              <ol v-if="drawDetail.history.length" class="staff-draw-history"><li v-for="change in drawDetail.history" :key="change.id">{{ time(change.created_at) }} · {{ change.staff_name }} · {{ change.action === 'reverse' ? '撤回' : '修正' }} {{ change.before_blood }} → {{ change.after_blood }} 血值 · {{ change.reason }}</li></ol>
            </div>
            <div v-if="boostEditor === p.id && boostDetail" class="staff-draw-editor">
              <h4>三倍能量道具奖励 · 初始 +{{ boostDetail.original_bonus }} 能量，当前 {{ boostDetail.status === 'reversed' ? '已撤回' : `+${boostDetail.bonus} 能量` }}</h4>
              <form class="staff-draw-fields" @submit.prevent="adjustBoost(p)">
                <label>修正为<input v-model.number="boostValue" type="number" min="1" max="1000000" step="1" inputmode="numeric" required/></label>
                <label>处理原因<input v-model.trim="boostReason" maxlength="255" placeholder="填写原因，留存处理记录" required/></label>
                <button class="staff-button primary" type="submit" :disabled="busy">保存修正</button>
                <button v-if="boostDetail.status === 'active'" class="staff-button danger" type="button" :disabled="busy" @click="reverseBoost(p)">撤回奖励</button>
              </form>
              <ol v-if="boostDetail.history.length" class="staff-draw-history"><li v-for="change in boostDetail.history" :key="change.id">{{ time(change.created_at) }} · {{ change.staff_name }} · {{ change.action === 'reverse' ? '撤回' : '修正' }} {{ change.before_bonus }} → {{ change.after_bonus }} 能量 · {{ change.reason }}</li></ol>
            </div>
          </article>
        </div>
      </section>

      <section v-else-if="tab === 'redemptions'" class="staff-section" aria-labelledby="redemptions-title">
        <h2 id="redemptions-title">兑换核销</h2>
        <div class="staff-segments" role="group" aria-label="兑换状态"><button v-for="option in [{ id: 'pending', label: '待领取' }, { id: 'fulfilled', label: '已领取' }, { id: 'cancelled', label: '已取消' }]" :key="option.id" :class="{ active: redemptionStatus === option.id }" @click="redemptionStatus = option.id; action(loadTab)">{{ option.label }}</button></div>
        <form class="staff-search standalone" @submit.prevent="action(loadTab)"><Search :size="17"/><label class="visually-hidden" for="staff-voucher-search">搜索编号、姓名、奖品或凭证码</label><input id="staff-voucher-search" v-model="search" placeholder="编号、姓名或凭证码"/><button class="staff-button secondary" type="submit" :disabled="busy">搜索</button></form>
        <p v-if="!redemptions.length" class="staff-empty">当前没有符合条件的兑换。</p>
        <div v-else class="staff-rows"><article v-for="r in redemptions" :key="r.id" class="staff-row staff-listrow"><div><h3>{{ r.title }} × {{ r.quantity }}</h3><p>{{ r.name }} · 编号 {{ r.participant_id }} · {{ r.student_id }}</p><small>凭证 {{ r.code }} · {{ r.price }} 能量</small></div><div class="staff-actions"><span v-if="r.status !== 'pending'" class="staff-status" :class="r.status === 'fulfilled' ? 'completed' : 'rejected'">{{ r.status === 'fulfilled' ? '已领取' : '已取消' }}</span><template v-else><button class="staff-button secondary" :disabled="busy" @click="setRedemption(r, 'cancel')">取消兑换</button><button class="staff-button primary" :disabled="busy" @click="setRedemption(r, 'fulfill')">核对发放</button></template></div></article></div>
      </section>

      <section v-else-if="tab === 'tasks'" class="staff-section" aria-labelledby="tasks-title">
        <div class="staff-section-heading"><h2 id="tasks-title">项目配置</h2><span>{{ tasks.length }} 项</span></div>
        <form class="staff-editor" @submit.prevent="saveTask"><h3>{{ editingTask === null ? '新增项目' : '编辑项目' }}</h3><div class="staff-fields">
          <label>项目代码<input v-model.trim="taskDraft.code" maxlength="64" required :readonly="editingTask !== null"/></label><label>名称<input v-model.trim="taskDraft.title" maxlength="90" required/></label><label class="wide">项目说明<input v-model.trim="taskDraft.description" maxlength="255"/></label>
          <label>类别<select v-model="taskDraft.category"><option value="checkin">注册</option><option value="volunteer">血值项目</option><option value="game">能量竞技场</option><option value="dart">飞镖游戏</option></select></label>
          <label>血值奖励<input v-model.number="taskDraft.blood_reward" type="number" min="0" step="1" required/></label><label>能量奖励<input v-model.number="taskDraft.energy_reward" type="number" min="0" step="1" required/></label><label>每次消耗血值<input v-model.number="taskDraft.blood_per_attempt" type="number" min="0" step="1" required/></label><label>每次成功获能量<input v-model.number="taskDraft.energy_per_success" type="number" min="0" step="1" required/></label><label>最低成功次数<input v-model.number="taskDraft.min_success" type="number" min="0" step="1" required/></label><label>每人可完成次数<input v-model.number="taskDraft.max_claims" type="number" min="1" step="1" placeholder="留空为不限"/></label><label>互斥组<input v-model.trim="taskDraft.exclusive_group" maxlength="40" placeholder="留空为不互斥"/></label>
        </div><div class="staff-actions"><button v-if="editingTask !== null" type="button" class="staff-button secondary" @click="editingTask = null; taskDraft = emptyTask()">取消</button><button type="submit" class="staff-button primary" :disabled="busy">保存项目</button></div></form>
        <div class="staff-rows"><article v-for="t in tasks" :key="t.id" class="staff-row staff-listrow"><div><h3>{{ t.title }}</h3><p>{{ categoryLabels[t.category] ?? t.category }} · {{ t.code }}</p><small>{{ t.description }}</small></div><div class="staff-actions"><span v-if="!t.active" class="staff-status rejected">已下架</span><button class="staff-icon" :aria-label="`编辑${t.title}`" title="编辑项目" @click="editTask(t)"><Pencil :size="16"/></button><button class="staff-button secondary" :disabled="busy" @click="toggleTask(t)">{{ t.active ? '下架' : '恢复' }}</button></div></article></div>
      </section>

      <section v-else-if="tab === 'prizes'" class="staff-section" aria-labelledby="prizes-title">
        <div class="staff-section-heading"><h2 id="prizes-title">奖品配置</h2><span>{{ prizes.length }} 项</span></div>
        <form class="staff-editor" @submit.prevent="savePrize"><h3>{{ editingPrize === null ? '新增奖品' : '编辑奖品' }}</h3><div class="staff-fields">
          <label>奖品代码<input v-model.trim="prizeDraft.code" maxlength="64" required :readonly="editingPrize !== null"/></label><label>名称<input v-model.trim="prizeDraft.title" maxlength="90" required/></label><label class="wide">说明<input v-model.trim="prizeDraft.description" maxlength="255"/></label><label>每份能量<input v-model.number="prizeDraft.energy_price" type="number" min="1" step="1" required/></label><label>库存<input v-model.number="prizeDraft.stock" type="number" min="0" step="1" required/></label><label>每人最多兑换<input v-model.number="prizeDraft.max_per_player" type="number" min="1" step="1" placeholder="留空为不限"/></label>
        </div><div class="staff-actions"><button v-if="editingPrize !== null" type="button" class="staff-button secondary" @click="editingPrize = null; prizeDraft = emptyPrize()">取消</button><button type="submit" class="staff-button primary" :disabled="busy">保存奖品</button></div></form>
        <div class="staff-rows"><article v-for="p in prizes" :key="p.id" class="staff-row staff-listrow"><div><h3>{{ p.title }}</h3><p>{{ p.code }} · {{ p.energy_price }} 能量 · 库存 {{ p.stock }}</p><small>{{ p.description }}</small></div><div class="staff-actions"><span v-if="!p.active" class="staff-status rejected">已下架</span><button class="staff-icon" :aria-label="`编辑${p.title}`" title="编辑奖品" @click="editPrize(p)"><Pencil :size="16"/></button><button class="staff-button secondary" :disabled="busy" @click="togglePrize(p)">{{ p.active ? '下架' : '恢复' }}</button></div></article></div>
      </section>

      <section v-else-if="tab === 'accounts'" class="staff-section" aria-labelledby="accounts-title">
        <div class="staff-section-heading"><h2 id="accounts-title">工作人员账号</h2><span>{{ accounts.length }} 个</span></div>
        <form class="staff-editor" @submit.prevent="saveAccount"><h3>{{ editingAccount === null ? '新增账号' : '编辑账号' }}</h3>
          <div class="staff-fields">
            <label>用户名<input v-model.trim="accountUsername" maxlength="80" autocomplete="off" required/></label>
            <label>{{ editingAccount === null ? '密码' : '新密码（留空则不修改）' }}<input v-model="accountPassword" type="password" autocomplete="new-password" :required="editingAccount === null" minlength="8"/></label>
            <label>账号权限<select v-model="accountRole"><option value="project">项目权限</option><option value="super">最高级权限</option></select></label>
            <label v-if="editingAccount !== null" class="staff-toggle"><input v-model="accountActive" type="checkbox"/> 账号启用</label>
          </div>
          <fieldset v-if="accountRole === 'project'" class="staff-permissions"><legend>可查看与核验的项目（可多选）</legend><label v-for="t in tasks.filter(t => t.active && t.category !== 'checkin')" :key="t.id"><input v-model="accountTaskIds" type="checkbox" :value="t.id"/>{{ t.title }}</label></fieldset>
          <div class="staff-actions"><button v-if="editingAccount !== null" class="staff-button secondary" type="button" @click="resetAccount">取消</button><button class="staff-button primary" type="submit" :disabled="busy"><Plus v-if="editingAccount === null" :size="15"/>{{ editingAccount === null ? '新增账号' : '保存账号' }}</button></div>
        </form>
        <div class="staff-rows"><article v-for="account in accounts" :key="account.id" class="staff-row staff-listrow"><div><h3>{{ account.username }}</h3><p>{{ roleLabels[account.role] }}<template v-if="account.role === 'project'"> · {{ tasks.filter(t => account.task_ids.includes(t.id)).map(t => t.title).join('、') || '未分配项目' }}</template></p></div><div class="staff-actions"><span v-if="!account.active" class="staff-status rejected">已停用</span><button class="staff-icon" :aria-label="`编辑${account.username}`" title="编辑权限" @click="editAccount(account)"><Pencil :size="16"/></button><button v-if="account.id !== me?.id" class="staff-button secondary" :disabled="busy" @click="setAccountActive(account)">{{ account.active ? '停用' : '启用' }}</button></div></article></div>
      </section>
    </template>

    <div v-if="error || success" class="staff-toast" :class="error ? 'error' : 'success'" :role="error ? 'alert' : 'status'"><CircleAlert v-if="error" :size="17"/><Check v-else :size="17"/><span>{{ error || success }}</span><button class="staff-icon" aria-label="关闭提示" @click="error = ''; success = ''"><X :size="15"/></button></div>
  </main>
</template>
