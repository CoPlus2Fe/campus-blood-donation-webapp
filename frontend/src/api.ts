export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const resp = await fetch('/api' + path, {
    method,
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'BloodQuest'},
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  let data: any = null
  try { data = await resp.json() } catch { data = {} }
  if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败（' + resp.status + '）')
  return data as T
}
export type Profile = {id:number; student_id:string; name:string;class_name:string;identity?:'student'|'staff';college?:string|null;blood:number;energy:number;energy_earned:number;rank:number;energy_boost_available:boolean;energy_boost_used:boolean}
export type Task = {id:number;title:string;description:string;category:string;blood_reward:number;energy_reward:number;blood_per_attempt:number;energy_per_success:number;min_success:number;max_claims:number|null;exclusive_group:string|null;completed_count:number;status:'pending'|'done'|'available';pending_id:number|null}
export type Prize = {id:number;title:string;description:string;price:number;stock:number;max_per_player:number|null}
export type Ranking = {players:{rank:number;name:string;score:number;me:boolean}[];my_rank:number;my_position:{rank:number;name:string;score:number};limit:number}
export type DrawState = {unlocked?:boolean;can_spin:boolean;available_at:string|null;already_drawn:boolean;result:number|null;status:'not_drawn'|'drawn'|'reversed'}
export type Ledger = {id:number;kind:string;delta:number;reason:string;created_at:string}
export type Redemption = {id:number;title:string;code:string;price:number;quantity:number;status:string}
