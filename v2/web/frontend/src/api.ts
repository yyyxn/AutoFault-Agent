export const API = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:38081'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export async function request(path: string, init?: RequestInit) {
  const response = await fetch(API + path, {
    headers: {'Content-Type': 'application/json'},
    ...init,
  })
  if (!response.ok) {
    const body = (await response.text()).slice(0, 300)
    let message = body || `HTTP ${response.status}`
    try {
      const parsed = JSON.parse(body)
      message = String(parsed.detail || parsed.message || message)
    } catch {
      // Keep the bounded response text when the server did not return JSON.
    }
    throw new ApiError(response.status, message)
  }
  return response.json()
}

export type RequestFunction = (path: string, init?: RequestInit) => Promise<any>
export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export async function resolveSession(currentSessionId: string, storage: StorageLike, call: RequestFunction = request) {
  if (currentSessionId) {
    try {
      await call('/api/sessions/' + currentSessionId)
      return currentSessionId
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error
      storage.removeItem('mvp2_session_id')
    }
  }
  const created = await call('/api/sessions', {method: 'POST', body: JSON.stringify({name: '浏览器演示'})})
  storage.setItem('mvp2_session_id', created.session_id)
  return created.session_id as string
}

export async function restoreTask(taskId: string | null, storage: StorageLike, call: RequestFunction = request) {
  if (!taskId) return null
  try {
    return await call('/api/tasks/' + taskId)
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
    storage.removeItem('mvp2_task_id')
    return null
  }
}
