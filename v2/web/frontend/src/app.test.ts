import {afterEach,describe,expect,it,vi} from 'vitest'
import {API,ApiError,request,resolveSession,restoreTask} from './api'

function storage() {
  const values = new Map<string,string>()
  return {values,getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>values.set(key,value),removeItem:(key:string)=>values.delete(key)}
}

afterEach(()=>vi.unstubAllGlobals())

describe('MVP-2.1 HTTP and recovery safety',()=>{
  it('uses local MVP-2.1 API by default',()=>expect(API).toBe('http://127.0.0.1:38081'))
  it('preserves HTTP status and server detail',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail:'session not found'}),{status:404})))
    await expect(request('/missing')).rejects.toMatchObject({name:'ApiError',status:404,message:'session not found'})
  })
  it('reuses an existing session',async()=>{
    const call=vi.fn(async()=>({session_id:'s_old'}));expect(await resolveSession('s_old',storage(),call)).toBe('s_old');expect(call).toHaveBeenCalledTimes(1)
  })
  it('recreates only a missing session',async()=>{
    const store=storage();store.setItem('mvp2_session_id','s_old');const call=vi.fn().mockRejectedValueOnce(new ApiError(404,'missing')).mockResolvedValueOnce({session_id:'s_new'})
    expect(await resolveSession('s_old',store,call)).toBe('s_new');expect(store.getItem('mvp2_session_id')).toBe('s_new');expect(call).toHaveBeenCalledTimes(2)
  })
  it('does not recreate a session after HTTP 500',async()=>{
    const call=vi.fn().mockRejectedValue(new ApiError(500,'server error'));await expect(resolveSession('s_old',storage(),call)).rejects.toMatchObject({status:500});expect(call).toHaveBeenCalledTimes(1)
  })
  it('does not reinterpret a network failure as 404',async()=>{
    const failure=new TypeError('network failed');const call=vi.fn().mockRejectedValue(failure);await expect(resolveSession('s_old',storage(),call)).rejects.toBe(failure);expect(call).toHaveBeenCalledTimes(1)
  })
  it('clears a missing task id',async()=>{
    const store=storage();store.setItem('mvp2_task_id','t_old');const call=vi.fn().mockRejectedValue(new ApiError(404,'missing'));expect(await restoreTask('t_old',store,call)).toBeNull();expect(store.getItem('mvp2_task_id')).toBeNull()
  })
  it('restores an existing task',async()=>{
    const call=vi.fn(async()=>({task_id:'t_ok'}));expect(await restoreTask('t_ok',storage(),call)).toEqual({task_id:'t_ok'})
  })
  it('shows scripted-runtime and token-scope boundaries',async()=>{
    const text=await import('./App.vue?raw').then(x=>String(x.default));expect(text).toContain('启动合成 Runtime');expect(text).toContain('token_count_scope');expect(text).toContain('不代表 Chat Template 后的实际 Prompt Token 数')
  })
})
